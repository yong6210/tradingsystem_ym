from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import select

from app.db.models import ExecutionFill, OrderSubmission, Plan
from app.db.session import SessionLocal, init_db
from app.services.strategy_engine import StrategyEngine
import scripts.run_market_state_rotation_v6_paper_bridge_tick as bridge
from scripts.run_market_state_rotation_v6_paper_bridge_tick import (
    EXPECTED_STRATEGY_FAMILY,
    _apply_add_snapshot,
    _apply_remove_snapshot,
    _create_sqlite_pre_apply_backup,
    _ensure_paper_rollout_policy,
    _execution_parity_preflight,
    _freshness_status,
    _plan_from_add_event,
    _runtime_event_cadence,
    _top_no_trade_reasons,
    build_runtime_decision_snapshot,
    run_paper_bridge_tick,
)


def _config() -> SimpleNamespace:
    return SimpleNamespace(
        reaction_usd=200.0,
        max_hold_bars=52,
        model_id="test_market_state_rotation_v6",
    )


def _add_event(ts: datetime, *, side: str = "short") -> dict:
    return {
        "ts": ts.isoformat(),
        "action": "add",
        "side": side,
        "qty": 1.0,
        "price": 100_000.0,
        "reason": "base_entry",
        "role": "base",
        "zone_score": 7,
        "regime": "downtrend" if side == "short" else "uptrend",
        "zone_key": f"{side}:100000:test_zone",
    }


def _snapshot(event: dict) -> dict:
    return {
        "created_at": datetime.now(UTC).isoformat(),
        "overall_status": "actionable",
        "symbol": "BTCUSDT",
        "strategy_family": EXPECTED_STRATEGY_FAMILY,
        "latest_event": event,
        "bridge_action": event["action"],
        "backtest_summary": {
            "trade_like_events": 120,
            "total_return_pct": 400.0,
            "max_drawdown_pct": 10.0,
        },
    }


def test_create_sqlite_pre_apply_backup_copies_db_and_avoids_overwrite(tmp_path) -> None:
    db_path = tmp_path / "runtime.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute("INSERT INTO sample (value) VALUES ('kept')")
        conn.commit()

    now = datetime(2026, 6, 5, 1, 2, 3, tzinfo=UTC)
    first = _create_sqlite_pre_apply_backup(
        backup_dir=tmp_path / "backups",
        database_url=f"sqlite:///{db_path}",
        now=now,
    )
    second = _create_sqlite_pre_apply_backup(
        backup_dir=tmp_path / "backups",
        database_url=f"sqlite:///{db_path}",
        now=now,
    )

    assert first["created"] is True
    assert first["quick_check"] == "ok"
    assert second["created"] is True
    assert second["quick_check"] == "ok"
    assert first["backup_path"] != second["backup_path"]
    with sqlite3.connect(first["backup_path"]) as conn:
        value = conn.execute("SELECT value FROM sample WHERE id = 1").fetchone()[0]
    assert value == "kept"


def test_freshness_status_blocks_stale_market_data_and_signal() -> None:
    now = datetime(2026, 1, 1, 1, 0, tzinfo=UTC)
    event = _add_event(now - timedelta(minutes=40))

    actionable, blockers, ages = _freshness_status(
        event=event,
        data_end=now - timedelta(minutes=45),
        now=now,
        max_signal_age_minutes=15,
        max_market_data_age_minutes=30,
    )

    assert actionable is False
    assert "market_data_stale" in blockers
    assert "signal_stale" in blockers
    assert ages["signal_age_minutes"] == 40.0


def test_runtime_event_cadence_flags_latest_signal_age_above_recent_gap() -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    events = [
        _add_event(base, side="long"),
        {**_add_event(base + timedelta(days=1), side="long"), "action": "remove"},
        _add_event(base + timedelta(days=2), side="short"),
    ]

    cadence = _runtime_event_cadence(
        bridge_events=events,
        data_meta={
            "exec_start": base.isoformat(),
            "exec_end": (base + timedelta(days=12)).isoformat(),
        },
        now=base + timedelta(days=12),
    )

    assert cadence["bridge_event_count"] == 3
    assert cadence["add_event_count"] == 2
    assert cadence["events_per_day"] == 0.25
    assert cadence["add_events_per_day"] == 0.1667
    assert cadence["expected_days_per_add"] == 6.0
    assert cadence["median_gap_hours"] == 24.0
    assert cadence["latest_event_age_hours"] == 240.0
    assert cadence["latest_age_to_median_gap"] == 10.0
    assert cadence["wait_state"] == "latest_signal_age_above_recent_median_gap"
    assert cadence["median_add_gap_hours"] == 48.0
    assert cadence["latest_add_age_hours"] == 240.0
    assert cadence["latest_add_age_to_median_gap"] == 5.0
    assert cadence["add_wait_state"] == "latest_add_age_above_recent_median_gap"


def test_top_no_trade_reasons_filters_context_breakdowns() -> None:
    reasons = _top_no_trade_reasons(
        {
            "no_trade_MC12_low_confluence": 10,
            "no_trade_context::MC12_low_confluence|long": 100,
            "no_trade_MC04_no_clear_first_touch": 30,
            "add": 3,
        },
        limit=2,
    )

    assert reasons == [
        {"reason": "no_trade_MC04_no_clear_first_touch", "count": 30},
        {"reason": "no_trade_MC12_low_confluence", "count": 10},
    ]


def test_runtime_snapshot_uses_runtime_load_window_and_fresh_cache_contract(monkeypatch) -> None:
    captured = {}
    now = datetime(2026, 6, 5, 3, 30, tzinfo=UTC)
    event = _add_event(now - timedelta(minutes=5), side="long")

    def fake_load_feature_sets(namespace):
        captured["namespace"] = namespace
        return object(), {}, {}, {
            "exec_start": (now - timedelta(days=120)).isoformat(),
            "exec_end": (now - timedelta(minutes=1)).isoformat(),
            "exec_rows": 100,
            "scenario_rows": {},
        }

    def fake_backtest_config(**kwargs):
        captured["backtest_kwargs"] = kwargs
        return {
            "recent_events": [event],
            "event_counts": {"no_trade_MC12_low_confluence": 3},
            "event_diagnostics": {
                "top_no_trade_contexts": {
                    "MC12_low_confluence|long|with_trend|uptrend|normal|score_0-3|edge_1-2|stack_1-2|ext_0-0.75|break_0-0.1": 3,
                },
                "no_trade_reason_side_counts": {"MC12_low_confluence|long": 3},
                "no_trade_reason_regime_counts": {"MC12_low_confluence|uptrend": 3},
            },
            "total_return_pct": 10.0,
            "max_drawdown_pct": 1.0,
            "trade_like_events": 1,
        }

    monkeypatch.setattr(bridge, "_load_feature_sets", fake_load_feature_sets)
    monkeypatch.setattr(bridge, "backtest_config", fake_backtest_config)
    monkeypatch.setattr(bridge, "_source_config", lambda _report: _config())

    report = {
        "args": {
            "load_days": 1825,
            "exec_interval": "5m",
            "scenario_intervals": "1h,4h",
            "cache_dir": "source/cache",
            "base_url": "https://source.example",
            "sleep_seconds": 0.0,
            "fee_bps_per_side": 4.0,
            "slippage_bps_per_side": 1.0,
            "min_periods": 5000,
        },
        "top_results": [{"config": {"model_id": "source_config", "reaction_usd": 200.0}}],
    }

    snapshot = build_runtime_decision_snapshot(
        source_backtest_report=report,
        now=now,
        max_signal_age_minutes=15,
        max_market_data_age_minutes=30,
    )

    namespace = captured["namespace"]
    assert namespace.load_days == 180
    assert namespace.max_cache_age_minutes == 30
    assert namespace.cache_dir == "source/cache"
    assert namespace.base_url == "https://source.example"
    assert snapshot["runtime_load_context"]["source_load_days"] == 1825
    assert snapshot["runtime_load_context"]["load_days"] == 180
    assert snapshot["runtime_load_context"]["max_cache_age_minutes"] == 30
    assert snapshot["overall_status"] == "actionable"
    assert snapshot["blockers"] == []
    assert snapshot["no_trade_hotspots"]["no_trade_reason_side_counts"] == {"MC12_low_confluence|long": 3}
    assert list(snapshot["no_trade_hotspots"]["top_no_trade_contexts"].values()) == [3]


def test_runtime_snapshot_reports_resolved_settings_base_url_when_source_is_blank(monkeypatch) -> None:
    captured = {}
    now = datetime(2026, 6, 5, 3, 30, tzinfo=UTC)
    event = _add_event(now - timedelta(minutes=5), side="short")

    def fake_load_feature_sets(namespace):
        captured["namespace"] = namespace
        return object(), {}, {}, {
            "exec_start": (now - timedelta(days=120)).isoformat(),
            "exec_end": (now - timedelta(minutes=1)).isoformat(),
            "exec_rows": 100,
            "scenario_rows": {},
        }

    monkeypatch.setattr(bridge, "_load_feature_sets", fake_load_feature_sets)
    monkeypatch.setattr(
        bridge,
        "backtest_config",
        lambda **_kwargs: {
            "recent_events": [event],
            "event_counts": {},
            "event_diagnostics": {},
            "total_return_pct": 10.0,
            "max_drawdown_pct": 1.0,
            "trade_like_events": 1,
        },
    )
    monkeypatch.setattr(bridge, "_source_config", lambda _report: _config())
    monkeypatch.setattr(bridge, "get_settings", lambda: SimpleNamespace(binance_rest_base_url="https://settings.example"))

    snapshot = build_runtime_decision_snapshot(
        source_backtest_report={
            "args": {
                "base_url": "",
                "cache_dir": "source/cache",
                "load_days": 1825,
                "sleep_seconds": 0.0,
            },
            "top_results": [{"config": {"model_id": "source_config", "reaction_usd": 200.0}}],
        },
        now=now,
        max_signal_age_minutes=15,
        max_market_data_age_minutes=30,
    )

    assert captured["namespace"].base_url == "https://settings.example"
    assert snapshot["runtime_load_context"]["base_url"] == "https://settings.example"


def test_plan_from_add_event_maps_short_levels_and_v6_validity() -> None:
    now = datetime.now(UTC)
    plan = _plan_from_add_event(
        symbol="BTCUSDT",
        event=_add_event(now, side="short"),
        config=_config(),
        now=now,
        valid_minutes=15,
    )

    assert plan.symbol == "BTCUSDT"
    assert plan.direction == "short"
    assert plan.sl > plan.entry_price
    assert plan.tp1 < plan.entry_price
    assert plan.validity["strategy_family"] == EXPECTED_STRATEGY_FAMILY
    assert plan.validity["recommended_risk_r"] == 0.0


def test_execution_parity_preflight_marks_fresh_add_snapshot_ready() -> None:
    now = datetime.now(UTC)
    event = _add_event(now, side="long")
    snapshot = {**_snapshot(event), "plan_candidate": {"plan_id": "candidate"}}

    preflight = _execution_parity_preflight(snapshot)

    assert preflight["status"] == "ready"
    assert preflight["passed"] is True
    assert preflight["expected_journal_action"] == "add"
    assert preflight["expected_journal_side"] == "long"
    assert preflight["will_increment_execution_parity_journal_after_apply"] is True
    assert preflight["no_live_order_sent"] is True


def test_paper_bridge_tick_blocks_apply_before_db_write_when_parity_preflight_fails(monkeypatch, tmp_path) -> None:
    source_report = tmp_path / "source.json"
    source_report.write_text('{"top_results": [{"config": {"model_id": "x"}}]}', encoding="utf-8")
    now = datetime.now(UTC)
    malformed_event = {**_add_event(now, side="long"), "ts": "", "price": 0.0}
    monkeypatch.setattr(
        bridge,
        "build_runtime_decision_snapshot",
        lambda **_kwargs: {**_snapshot(malformed_event), "plan_candidate": {"plan_id": "candidate"}},
    )

    report = run_paper_bridge_tick(
        source_backtest_report_path=source_report,
        apply_paper=True,
        pre_apply_backup_dir=tmp_path / "backup",
        require_pre_apply_backup=True,
    )

    assert report["overall_status"] == "execution_parity_preflight_failed"
    assert report["result"]["status"] == "blocked_before_db_write"
    assert "source_event_ts_missing_or_invalid" in report["execution_parity_preflight"]["blockers"]
    assert "source_event_price_missing_or_invalid" in report["execution_parity_preflight"]["blockers"]
    assert report["pre_apply_backup"] is None
    assert report["no_live_order_sent"] is True


def test_apply_add_snapshot_uses_existing_paper_lifecycle_without_live_orders() -> None:
    init_db()
    now = datetime.now(UTC)
    event = _add_event(now, side="long")
    plan = _plan_from_add_event(
        symbol="BTCUSDT",
        event=event,
        config=_config(),
        now=now,
        valid_minutes=15,
    )

    with SessionLocal() as db:
        engine = StrategyEngine(db)
        engine.settings.auto_trading_enabled = True
        _ensure_paper_rollout_policy(engine)
        db.commit()

        result = _apply_add_snapshot(db=db, engine=engine, snapshot=_snapshot(event), plan=plan)

        assert result["status"] == "submitted"
        submission = db.scalar(select(OrderSubmission).where(OrderSubmission.plan_id == plan.plan_id))
        assert submission is not None
        assert submission.adapter == "paper"
        assert submission.requested_live is False
        fill = db.scalar(select(ExecutionFill).where(ExecutionFill.plan_id == plan.plan_id))
        assert fill is not None
        assert fill.stage == "ENTRY"
        refreshed = db.get(Plan, plan.plan_id)
        assert refreshed is not None
        assert refreshed.state == "ENTERED"


def test_apply_remove_snapshot_closes_open_v6_paper_plan_from_current_remove_event() -> None:
    init_db()
    now = datetime.now(UTC)
    add_event = _add_event(now, side="long")
    plan = _plan_from_add_event(
        symbol="BTCUSDT",
        event=add_event,
        config=_config(),
        now=now,
        valid_minutes=15,
    )

    with SessionLocal() as db:
        engine = StrategyEngine(db)
        engine.settings.auto_trading_enabled = True
        _ensure_paper_rollout_policy(engine)
        db.commit()
        _apply_add_snapshot(db=db, engine=engine, snapshot=_snapshot(add_event), plan=plan)

        remove_event = {
            **add_event,
            "ts": (now + timedelta(minutes=5)).isoformat(),
            "action": "remove",
            "reason": "v6_reaction_inventory_trim",
            "price": 100_150.0,
        }
        result = _apply_remove_snapshot(db=db, engine=engine, snapshot=_snapshot(remove_event))

        assert result["status"] == "exit_recorded"
        assert result["closed_or_partial"][0]["stage"] == "CLOSED"
        refreshed = db.get(Plan, plan.plan_id)
        assert refreshed is not None
        assert refreshed.state == "CLOSED"
        fills = list(db.scalars(select(ExecutionFill).where(ExecutionFill.plan_id == plan.plan_id)))
        assert {fill.stage for fill in fills} == {"ENTRY", "CLOSED"}
