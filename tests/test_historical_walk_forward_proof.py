from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

from app.db.models import Candle, Plan
from app.db.repositories import CandleRepository
from app.db.session import SessionLocal, init_db
from app.services.historical_walk_forward_proof import HistoricalWalkForwardProofService
from app.services.plan_generator import RankedPlan


def _candle(
    *,
    symbol: str,
    timeframe: str,
    ts: datetime,
    o: float,
    h: float,
    c: float,
    low: float | None = None,
    **kwargs: Any,
) -> Candle:
    low = float(kwargs.get("l", 0.0) if low is None else low)
    return Candle(
        symbol=symbol,
        timeframe=timeframe,
        ts=ts,
        o=o,
        h=h,
        l=low,
        c=c,
        v=1000.0,
        source="test",
        is_final=True,
    )


class _DummyContextEngine:
    def build_snapshot(self, symbol: str, candles_5m, candles_15m):  # noqa: ANN001
        return SimpleNamespace(symbol=symbol, regime_label="range")


class _DummyZoneEngine:
    def refresh(self, symbol: str, candles_15m, existing):  # noqa: ANN001
        return list(existing or [])


class _DummyPlanGenerator:
    def __init__(
        self,
        *,
        trigger_ts: datetime | tuple[datetime, ...],
        time_stop_bars: int = 10,
        extra_validity: dict[str, Any] | None = None,
    ):
        if isinstance(trigger_ts, tuple):
            self.trigger_ts_values = set(trigger_ts)
        else:
            self.trigger_ts_values = {trigger_ts}
        self.time_stop_bars = time_stop_bars
        self.extra_validity = dict(extra_validity or {})

    def generate(self, symbol: str, zones, context, candles_5m, active_thesis_clusters: int, now):  # noqa: ANN001
        if now not in self.trigger_ts_values:
            return []
        plan = Plan(
            plan_id=f"seed_plan_{now.strftime('%H%M')}",
            zone_id=f"zone_seed_plan_{now.strftime('%H%M')}",
            symbol=symbol,
            timeframe="5m",
            direction="long",
            entry_model="LIMIT",
            entry_price=100.0,
            entry_condition="touch_limit",
            sl=99.0,
            tp1=101.0,
            tp2=102.0,
            tp3=103.0,
            split={"tp1": 0.4, "tp2": 0.3, "runner": 0.3},
            rr_min=1.0,
            rr_base=2.0,
            rr_opt=3.0,
            ev=0.85,
            cost_est=0.01,
            confidence=0.7,
            validity={
                "strategy_family": "sweep_reversal",
                "strategy_grade": "A",
                "strategy_family_time_stop_max_bars": self.time_stop_bars,
                "thesis_cluster_id": f"cluster_{now.strftime('%H%M')}",
                **self.extra_validity,
            },
            state="PLANNED",
            valid_from=now,
            valid_until=now + timedelta(minutes=30),
            strategy_version="test",
        )
        return [RankedPlan(plan=plan, final_rank_score=91.0, friction_penalty=0.0)]


class _TwoPlanGenerator:
    def __init__(self, *, trigger_ts: datetime):
        self.trigger_ts = trigger_ts

    def generate(self, symbol: str, zones, context, candles_5m, active_thesis_clusters: int, now):  # noqa: ANN001
        if now != self.trigger_ts:
            return []
        losing_plan = Plan(
            plan_id=f"seed_limit_long_{now.strftime('%H%M')}",
            zone_id=f"zone_limit_long_{now.strftime('%H%M')}",
            symbol=symbol,
            timeframe="5m",
            direction="long",
            entry_model="LIMIT",
            entry_price=100.0,
            entry_condition="touch_limit",
            sl=99.0,
            tp1=101.0,
            tp2=102.0,
            tp3=103.0,
            split={"tp1": 0.4, "tp2": 0.3, "runner": 0.3},
            rr_min=1.0,
            rr_base=2.0,
            rr_opt=3.0,
            ev=0.4,
            cost_est=0.01,
            confidence=0.7,
            validity={
                "strategy_family": "sweep_reversal",
                "strategy_grade": "A",
                "strategy_family_time_stop_max_bars": 10,
                "thesis_cluster_id": f"cluster_limit_{now.strftime('%H%M')}",
            },
            state="PLANNED",
            valid_from=now,
            valid_until=now + timedelta(minutes=30),
            strategy_version="test",
        )
        winning_plan = Plan(
            plan_id=f"seed_confirm_short_{now.strftime('%H%M')}",
            zone_id=f"zone_confirm_short_{now.strftime('%H%M')}",
            symbol=symbol,
            timeframe="5m",
            direction="short",
            entry_model="CONFIRM",
            entry_price=100.0,
            entry_condition="confirm_break",
            sl=101.0,
            tp1=99.0,
            tp2=98.0,
            tp3=97.0,
            split={"tp1": 0.4, "tp2": 0.3, "runner": 0.3},
            rr_min=1.0,
            rr_base=2.0,
            rr_opt=3.0,
            ev=0.6,
            cost_est=0.01,
            confidence=0.75,
            validity={
                "strategy_family": "sweep_reversal",
                "strategy_grade": "A",
                "strategy_family_time_stop_max_bars": 10,
                "thesis_cluster_id": f"cluster_confirm_{now.strftime('%H%M')}",
            },
            state="PLANNED",
            valid_from=now,
            valid_until=now + timedelta(minutes=30),
            strategy_version="test",
        )
        return [
            RankedPlan(plan=losing_plan, final_rank_score=99.0, friction_penalty=0.0),
            RankedPlan(plan=winning_plan, final_rank_score=88.0, friction_penalty=0.0),
        ]


def test_historical_walk_forward_service_replays_limit_trade(tmp_path) -> None:
    init_db()
    symbol = "BTCUSDC"
    start = datetime(2026, 4, 18, 0, 0, tzinfo=timezone.utc)
    trigger_ts = start + timedelta(minutes=435)

    with SessionLocal() as db:
        repo = CandleRepository(db)
        for offset in range(90):
            ts = start + timedelta(minutes=5 * offset)
            close = 100.0 + (0.05 * (offset % 3))
            if ts == trigger_ts + timedelta(minutes=5):
                candle = _candle(
                    symbol=symbol,
                    timeframe="5m",
                    ts=ts,
                    o=100.0,
                    h=100.2,
                    l=99.8,
                    c=100.1,
                )
            elif ts == trigger_ts + timedelta(minutes=10):
                candle = _candle(
                    symbol=symbol,
                    timeframe="5m",
                    ts=ts,
                    o=100.2,
                    h=103.4,
                    l=100.2,
                    c=103.0,
                )
            else:
                candle = _candle(
                    symbol=symbol,
                    timeframe="5m",
                    ts=ts,
                    o=close - 0.1,
                    h=close + 0.2,
                    l=close - 0.2,
                    c=close,
                )
            repo.upsert(candle)
        for offset in range(30):
            ts = start + timedelta(minutes=15 * offset)
            close = 100.0 + (0.1 * (offset % 4))
            repo.upsert(
                _candle(
                    symbol=symbol,
                    timeframe="15m",
                    ts=ts,
                    o=close - 0.2,
                    h=close + 0.4,
                    l=close - 0.4,
                    c=close,
                )
            )
        db.commit()

        service = HistoricalWalkForwardProofService(
            candle_repo=repo,
            settings=SimpleNamespace(
                strategy_version="test",
                validation_report_dir=str(tmp_path),
                auto_trading_historical_walk_forward_cache_hours=0.0,
                auto_trading_historical_walk_forward_warmup_5m_bars=3,
                auto_trading_historical_walk_forward_min_15m_bars=2,
                auto_trading_historical_walk_forward_max_5m_window_bars=12,
                auto_trading_historical_walk_forward_max_15m_window_bars=6,
                thesis_time_bucket_minutes=30,
            ),
            context_engine=_DummyContextEngine(),
            zone_engine=_DummyZoneEngine(),
            plan_generator=_DummyPlanGenerator(trigger_ts=trigger_ts),
        )
        payload = service.generate(
            eligible_symbols=(symbol,),
            eligible_families=("sweep_reversal",),
            eligible_entry_models=("LIMIT",),
            contract_scope="historical_walk_forward_limit_only",
            cache_key="unit_walk_forward",
        )

    assert payload["simulation_start_ts"] == start.isoformat()
    assert payload["simulation_end_ts"] == (start + timedelta(minutes=5 * 89)).isoformat()
    assert len(payload["trade_rows"]) == 1
    row = payload["trade_rows"][0]
    assert row["symbol"] == symbol
    assert row["entry_model"] == "LIMIT"
    assert row["final_exit_reason"] == "target_tp3"
    assert row["final_exit_realized_r"] == 1.9
    assert payload["symbol_summaries"][0]["selected_contract_candidate_count"] == 1


def test_historical_walk_forward_preselection_filters_fallback_to_next_candidate(tmp_path) -> None:
    init_db()
    symbol = "BTCUSDC"
    start = datetime(2026, 4, 18, 0, 0, tzinfo=timezone.utc)
    trigger_ts = start + timedelta(minutes=435)

    contract_path = tmp_path / "blocked_time_contract.json"
    contract_path.write_text(
        json.dumps(
            {
                "blocked_buckets": [
                    {
                        "symbol": symbol,
                        "strategy_family": "sweep_reversal",
                        "entry_model": "LIMIT",
                        "direction": "LONG",
                        "year_utc": trigger_ts.year,
                        "month_utc": trigger_ts.month,
                        "day_utc": trigger_ts.day,
                        "hour_utc": trigger_ts.hour,
                        "minute_utc": trigger_ts.minute,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with SessionLocal() as db:
        repo = CandleRepository(db)
        for offset in range(91):
            ts = start + timedelta(minutes=5 * offset)
            if ts == trigger_ts + timedelta(minutes=5):
                candle = _candle(
                    symbol=symbol,
                    timeframe="5m",
                    ts=ts,
                    o=100.0,
                    h=100.2,
                    l=99.8,
                    c=100.0,
                )
            elif ts == trigger_ts + timedelta(minutes=10):
                candle = _candle(
                    symbol=symbol,
                    timeframe="5m",
                    ts=ts,
                    o=100.0,
                    h=100.1,
                    l=98.9,
                    c=99.0,
                )
            elif ts == trigger_ts + timedelta(minutes=15):
                candle = _candle(
                    symbol=symbol,
                    timeframe="5m",
                    ts=ts,
                    o=99.0,
                    h=99.1,
                    l=96.8,
                    c=97.0,
                )
            else:
                candle = _candle(
                    symbol=symbol,
                    timeframe="5m",
                    ts=ts,
                    o=100.0,
                    h=100.2,
                    l=99.8,
                    c=100.0,
                )
            repo.upsert(candle)
        for offset in range(30):
            ts = start + timedelta(minutes=15 * offset)
            repo.upsert(
                _candle(
                    symbol=symbol,
                    timeframe="15m",
                    ts=ts,
                    o=100.0,
                    h=100.3,
                    l=99.7,
                    c=100.0,
                )
            )
        db.commit()

        service = HistoricalWalkForwardProofService(
            candle_repo=repo,
            settings=SimpleNamespace(
                strategy_version="test",
                validation_report_dir=str(tmp_path),
                auto_trading_historical_walk_forward_cache_hours=0.0,
                auto_trading_historical_walk_forward_warmup_5m_bars=3,
                auto_trading_historical_walk_forward_min_15m_bars=2,
                auto_trading_historical_walk_forward_max_5m_window_bars=12,
                auto_trading_historical_walk_forward_max_15m_window_bars=6,
                thesis_time_bucket_minutes=30,
            ),
            context_engine=_DummyContextEngine(),
            zone_engine=_DummyZoneEngine(),
            plan_generator=_TwoPlanGenerator(trigger_ts=trigger_ts),
        )
        baseline = service.generate(
            eligible_symbols=(symbol,),
            eligible_families=("sweep_reversal",),
            eligible_entry_models=("LIMIT", "CONFIRM"),
            contract_scope="historical_walk_forward_limit_confirm",
            cache_key="unit_walk_forward_preselection_baseline",
            independent_signal_mode=True,
            max_candidates_per_bar=1,
        )
        filtered = service.generate(
            eligible_symbols=(symbol,),
            eligible_families=("sweep_reversal",),
            eligible_entry_models=("LIMIT", "CONFIRM"),
            contract_scope="historical_walk_forward_limit_confirm",
            cache_key="unit_walk_forward_preselection_filtered",
            independent_signal_mode=True,
            max_candidates_per_bar=1,
            blocked_strategy_time_contract_path=str(contract_path),
        )

    assert len(baseline["trade_rows"]) == 1
    assert baseline["trade_rows"][0]["entry_model"] == "LIMIT"
    assert baseline["trade_rows"][0]["direction"] == "long"
    assert baseline["trade_rows"][0]["final_exit_reason"] == "stop_loss"
    assert baseline["trade_rows"][0]["final_exit_realized_r"] == -1.0

    assert len(filtered["trade_rows"]) == 1
    assert filtered["trade_rows"][0]["entry_model"] == "CONFIRM"
    assert filtered["trade_rows"][0]["direction"] == "short"
    assert filtered["trade_rows"][0]["final_exit_reason"] == "target_tp3"
    assert filtered["trade_rows"][0]["final_exit_realized_r"] == 1.9


def test_historical_walk_forward_service_applies_fast_failure_guard_stop(tmp_path) -> None:
    init_db()
    symbol = "BTCUSDC"
    start = datetime(2026, 4, 18, 0, 0, tzinfo=timezone.utc)
    trigger_ts = start + timedelta(minutes=435)

    with SessionLocal() as db:
        repo = CandleRepository(db)
        for offset in range(91):
            ts = start + timedelta(minutes=5 * offset)
            if ts == trigger_ts + timedelta(minutes=5):
                candle = _candle(
                    symbol=symbol,
                    timeframe="5m",
                    ts=ts,
                    o=100.0,
                    h=100.1,
                    l=99.9,
                    c=100.0,
                )
            elif ts == trigger_ts + timedelta(minutes=10):
                candle = _candle(
                    symbol=symbol,
                    timeframe="5m",
                    ts=ts,
                    o=100.0,
                    h=100.1,
                    l=98.7,
                    c=99.0,
                )
            else:
                candle = _candle(
                    symbol=symbol,
                    timeframe="5m",
                    ts=ts,
                    o=100.0,
                    h=100.2,
                    l=99.8,
                    c=100.0,
                )
            repo.upsert(candle)
        for offset in range(30):
            ts = start + timedelta(minutes=15 * offset)
            repo.upsert(
                _candle(
                    symbol=symbol,
                    timeframe="15m",
                    ts=ts,
                    o=100.0,
                    h=100.3,
                    l=99.7,
                    c=100.0,
                )
            )
        db.commit()

        service = HistoricalWalkForwardProofService(
            candle_repo=repo,
            settings=SimpleNamespace(
                strategy_version="test",
                validation_report_dir=str(tmp_path),
                auto_trading_historical_walk_forward_cache_hours=0.0,
                auto_trading_historical_walk_forward_warmup_5m_bars=3,
                auto_trading_historical_walk_forward_min_15m_bars=2,
                auto_trading_historical_walk_forward_max_5m_window_bars=12,
                auto_trading_historical_walk_forward_max_15m_window_bars=6,
                thesis_time_bucket_minutes=30,
            ),
            context_engine=_DummyContextEngine(),
            zone_engine=_DummyZoneEngine(),
            plan_generator=_DummyPlanGenerator(
                trigger_ts=trigger_ts,
                extra_validity={
                    "strategy_fast_failure_enabled": True,
                    "strategy_fast_failure_policy": "btc_sweep_reversal_limit_initial_guard_stop",
                    "strategy_fast_failure_max_bars": 1,
                    "strategy_fast_failure_stop_r": 0.6,
                    "strategy_fast_failure_requires_sl_touch": True,
                },
            ),
        )
        payload = service.generate(
            eligible_symbols=(symbol,),
            eligible_families=("sweep_reversal",),
            eligible_entry_models=("LIMIT",),
            contract_scope="historical_walk_forward_limit_only",
            cache_key="unit_walk_forward_fast_failure",
        )

    assert len(payload["trade_rows"]) == 1
    row = payload["trade_rows"][0]
    assert row["final_exit_reason"] == "structure_failure"
    assert row["final_exit_price"] == 99.4
    assert row["final_exit_realized_r"] == -0.6
    assert row["final_exit_trigger_detail"]["saved_r_vs_full_stop"] == 0.4
    assert row["final_exit_trigger_detail"]["requires_sl_touch"] is True


def test_historical_walk_forward_fast_failure_waits_for_original_stop_touch(tmp_path) -> None:
    init_db()
    symbol = "BTCUSDC"
    start = datetime(2026, 4, 18, 0, 0, tzinfo=timezone.utc)
    trigger_ts = start + timedelta(minutes=435)

    with SessionLocal() as db:
        repo = CandleRepository(db)
        for offset in range(91):
            ts = start + timedelta(minutes=5 * offset)
            if ts == trigger_ts + timedelta(minutes=5):
                candle = _candle(
                    symbol=symbol,
                    timeframe="5m",
                    ts=ts,
                    o=100.0,
                    h=100.1,
                    l=99.9,
                    c=100.0,
                )
            elif ts == trigger_ts + timedelta(minutes=10):
                candle = _candle(
                    symbol=symbol,
                    timeframe="5m",
                    ts=ts,
                    o=100.0,
                    h=101.5,
                    l=99.35,
                    c=101.2,
                )
            elif ts == trigger_ts + timedelta(minutes=15):
                candle = _candle(
                    symbol=symbol,
                    timeframe="5m",
                    ts=ts,
                    o=101.2,
                    h=103.4,
                    l=101.0,
                    c=103.0,
                )
            else:
                candle = _candle(
                    symbol=symbol,
                    timeframe="5m",
                    ts=ts,
                    o=100.0,
                    h=100.2,
                    l=99.8,
                    c=100.0,
                )
            repo.upsert(candle)
        for offset in range(30):
            ts = start + timedelta(minutes=15 * offset)
            repo.upsert(
                _candle(
                    symbol=symbol,
                    timeframe="15m",
                    ts=ts,
                    o=100.0,
                    h=100.3,
                    l=99.7,
                    c=100.0,
                )
            )
        db.commit()

        service = HistoricalWalkForwardProofService(
            candle_repo=repo,
            settings=SimpleNamespace(
                strategy_version="test",
                validation_report_dir=str(tmp_path),
                auto_trading_historical_walk_forward_cache_hours=0.0,
                auto_trading_historical_walk_forward_warmup_5m_bars=3,
                auto_trading_historical_walk_forward_min_15m_bars=2,
                auto_trading_historical_walk_forward_max_5m_window_bars=12,
                auto_trading_historical_walk_forward_max_15m_window_bars=6,
                thesis_time_bucket_minutes=30,
            ),
            context_engine=_DummyContextEngine(),
            zone_engine=_DummyZoneEngine(),
            plan_generator=_DummyPlanGenerator(
                trigger_ts=trigger_ts,
                extra_validity={
                    "strategy_fast_failure_enabled": True,
                    "strategy_fast_failure_policy": "btc_sweep_reversal_limit_initial_guard_stop",
                    "strategy_fast_failure_max_bars": 1,
                    "strategy_fast_failure_stop_r": 0.6,
                    "strategy_fast_failure_requires_sl_touch": True,
                },
            ),
        )
        payload = service.generate(
            eligible_symbols=(symbol,),
            eligible_families=("sweep_reversal",),
            eligible_entry_models=("LIMIT",),
            contract_scope="historical_walk_forward_limit_only",
            cache_key="unit_walk_forward_fast_failure_requires_sl_touch",
        )

    assert len(payload["trade_rows"]) == 1
    row = payload["trade_rows"][0]
    assert row["final_exit_reason"] == "target_tp3"
    assert row["final_exit_realized_r"] == 1.9


def test_historical_walk_forward_cache_invalidates_when_earlier_history_is_backfilled(tmp_path) -> None:
    init_db()
    symbol = "ETHUSDC"
    start = datetime(2026, 4, 18, 0, 0, tzinfo=timezone.utc)
    earlier_start = start - timedelta(minutes=15 * 30)
    trigger_ts = start + timedelta(minutes=435)

    with SessionLocal() as db:
        repo = CandleRepository(db)
        for offset in range(90):
            ts = start + timedelta(minutes=5 * offset)
            close = 100.0 + (0.05 * (offset % 3))
            repo.upsert(
                _candle(
                    symbol=symbol,
                    timeframe="5m",
                    ts=ts,
                    o=close - 0.1,
                    h=close + 0.2,
                    l=close - 0.2,
                    c=close,
                )
            )
        for offset in range(30):
            ts = start + timedelta(minutes=15 * offset)
            close = 100.0 + (0.1 * (offset % 4))
            repo.upsert(
                _candle(
                    symbol=symbol,
                    timeframe="15m",
                    ts=ts,
                    o=close - 0.2,
                    h=close + 0.4,
                    l=close - 0.4,
                    c=close,
                )
            )
        db.commit()

        service = HistoricalWalkForwardProofService(
            candle_repo=repo,
            settings=SimpleNamespace(
                strategy_version="test",
                validation_report_dir=str(tmp_path),
                auto_trading_historical_walk_forward_cache_hours=24.0,
                auto_trading_historical_walk_forward_warmup_5m_bars=3,
                auto_trading_historical_walk_forward_min_15m_bars=2,
                auto_trading_historical_walk_forward_max_5m_window_bars=12,
                auto_trading_historical_walk_forward_max_15m_window_bars=6,
                thesis_time_bucket_minutes=30,
            ),
            context_engine=_DummyContextEngine(),
            zone_engine=_DummyZoneEngine(),
            plan_generator=_DummyPlanGenerator(trigger_ts=trigger_ts),
        )
        initial_payload = service.generate(
            eligible_symbols=(symbol,),
            eligible_families=("sweep_reversal",),
            eligible_entry_models=("LIMIT",),
            contract_scope="historical_walk_forward_limit_only",
            cache_key="cache_refresh",
        )
        assert initial_payload["simulation_start_ts"] == start.isoformat()

        for offset in range(90):
            ts = earlier_start + timedelta(minutes=5 * offset)
            close = 99.0 + (0.03 * (offset % 5))
            repo.upsert(
                _candle(
                    symbol=symbol,
                    timeframe="5m",
                    ts=ts,
                    o=close - 0.1,
                    h=close + 0.2,
                    l=close - 0.2,
                    c=close,
                )
            )
        for offset in range(30):
            ts = earlier_start + timedelta(minutes=15 * offset)
            close = 99.0 + (0.05 * (offset % 4))
            repo.upsert(
                _candle(
                    symbol=symbol,
                    timeframe="15m",
                    ts=ts,
                    o=close - 0.2,
                    h=close + 0.4,
                    l=close - 0.4,
                    c=close,
                )
            )
        db.commit()

        refreshed_payload = service.generate(
            eligible_symbols=(symbol,),
            eligible_families=("sweep_reversal",),
            eligible_entry_models=("LIMIT",),
            contract_scope="historical_walk_forward_limit_only",
            cache_key="cache_refresh",
        )

    assert refreshed_payload["simulation_start_ts"] == earlier_start.isoformat()


def test_historical_walk_forward_cache_invalidates_when_fast_failure_settings_change(tmp_path) -> None:
    init_db()
    symbol = "BTCUSDC"
    start = datetime(2026, 4, 18, 0, 0, tzinfo=timezone.utc)
    trigger_ts = start + timedelta(minutes=435)

    with SessionLocal() as db:
        repo = CandleRepository(db)
        for offset in range(91):
            ts = start + timedelta(minutes=5 * offset)
            if ts == trigger_ts + timedelta(minutes=5):
                candle = _candle(
                    symbol=symbol,
                    timeframe="5m",
                    ts=ts,
                    o=100.0,
                    h=100.1,
                    l=99.9,
                    c=100.0,
                )
            elif ts == trigger_ts + timedelta(minutes=10):
                candle = _candle(
                    symbol=symbol,
                    timeframe="5m",
                    ts=ts,
                    o=100.0,
                    h=100.2,
                    l=99.8,
                    c=100.0,
                )
            elif ts == trigger_ts + timedelta(minutes=15):
                candle = _candle(
                    symbol=symbol,
                    timeframe="5m",
                    ts=ts,
                    o=100.0,
                    h=100.1,
                    l=98.7,
                    c=99.0,
                )
            else:
                candle = _candle(
                    symbol=symbol,
                    timeframe="5m",
                    ts=ts,
                    o=100.0,
                    h=100.2,
                    l=99.8,
                    c=100.0,
                )
            repo.upsert(candle)
        for offset in range(30):
            ts = start + timedelta(minutes=15 * offset)
            repo.upsert(
                _candle(
                    symbol=symbol,
                    timeframe="15m",
                    ts=ts,
                    o=100.0,
                    h=100.3,
                    l=99.7,
                    c=100.0,
                )
            )
        db.commit()

        common_settings = dict(
            strategy_version="test",
            validation_report_dir=str(tmp_path),
            auto_trading_historical_walk_forward_cache_hours=24.0,
            auto_trading_historical_walk_forward_warmup_5m_bars=3,
            auto_trading_historical_walk_forward_min_15m_bars=2,
            auto_trading_historical_walk_forward_max_5m_window_bars=12,
            auto_trading_historical_walk_forward_max_15m_window_bars=6,
            thesis_time_bucket_minutes=30,
        )
        cache_key = "cache_refresh_fast_failure_settings"

        service_bars_1 = HistoricalWalkForwardProofService(
            candle_repo=repo,
            settings=SimpleNamespace(
                **common_settings,
                btc_sweep_reversal_limit_fast_failure_enabled=True,
                btc_sweep_reversal_limit_fast_failure_allowed_sessions="new_york",
                btc_sweep_reversal_limit_fast_failure_max_bars=1,
                btc_sweep_reversal_limit_fast_failure_stop_r=0.6,
                btc_sweep_reversal_limit_fast_failure_requires_sl_touch=True,
            ),
            context_engine=_DummyContextEngine(),
            zone_engine=_DummyZoneEngine(),
            plan_generator=_DummyPlanGenerator(
                trigger_ts=trigger_ts,
                extra_validity={
                    "strategy_fast_failure_enabled": True,
                    "strategy_fast_failure_policy": "btc_sweep_reversal_limit_initial_guard_stop",
                    "strategy_fast_failure_max_bars": 1,
                    "strategy_fast_failure_stop_r": 0.6,
                    "strategy_fast_failure_requires_sl_touch": True,
                },
            ),
        )
        first_payload = service_bars_1.generate(
            eligible_symbols=(symbol,),
            eligible_families=("sweep_reversal",),
            eligible_entry_models=("LIMIT",),
            contract_scope="historical_walk_forward_limit_only",
            cache_key=cache_key,
        )

        service_bars_2 = HistoricalWalkForwardProofService(
            candle_repo=repo,
            settings=SimpleNamespace(
                **common_settings,
                btc_sweep_reversal_limit_fast_failure_enabled=True,
                btc_sweep_reversal_limit_fast_failure_allowed_sessions="new_york",
                btc_sweep_reversal_limit_fast_failure_max_bars=2,
                btc_sweep_reversal_limit_fast_failure_stop_r=0.6,
                btc_sweep_reversal_limit_fast_failure_requires_sl_touch=True,
            ),
            context_engine=_DummyContextEngine(),
            zone_engine=_DummyZoneEngine(),
            plan_generator=_DummyPlanGenerator(
                trigger_ts=trigger_ts,
                extra_validity={
                    "strategy_fast_failure_enabled": True,
                    "strategy_fast_failure_policy": "btc_sweep_reversal_limit_initial_guard_stop",
                    "strategy_fast_failure_max_bars": 2,
                    "strategy_fast_failure_stop_r": 0.6,
                    "strategy_fast_failure_requires_sl_touch": True,
                },
            ),
        )
        second_payload = service_bars_2.generate(
            eligible_symbols=(symbol,),
            eligible_families=("sweep_reversal",),
            eligible_entry_models=("LIMIT",),
            contract_scope="historical_walk_forward_limit_only",
            cache_key=cache_key,
        )

    assert first_payload["trade_rows"][0]["final_exit_reason"] == "stop_loss"
    assert second_payload["trade_rows"][0]["final_exit_reason"] == "structure_failure"
    assert first_payload["generated_at"] != second_payload["generated_at"]


def test_historical_walk_forward_independent_signal_mode_accumulates_overlapping_signals(tmp_path) -> None:
    init_db()
    symbol = "BTCUSDC"
    start = datetime(2026, 4, 18, 0, 0, tzinfo=timezone.utc)
    trigger_ts_1 = start + timedelta(minutes=435)
    trigger_ts_2 = trigger_ts_1 + timedelta(minutes=15)

    with SessionLocal() as db:
        repo = CandleRepository(db)
        for offset in range(120):
            ts = start + timedelta(minutes=5 * offset)
            candle = _candle(
                symbol=symbol,
                timeframe="5m",
                ts=ts,
                o=100.0,
                h=100.2,
                l=99.8,
                c=100.0,
            )
            repo.upsert(candle)
        for offset in range(40):
            ts = start + timedelta(minutes=15 * offset)
            repo.upsert(
                _candle(
                    symbol=symbol,
                    timeframe="15m",
                    ts=ts,
                    o=100.0,
                    h=100.3,
                    l=99.7,
                    c=100.0,
                )
            )
        db.commit()

        service = HistoricalWalkForwardProofService(
            candle_repo=repo,
            settings=SimpleNamespace(
                strategy_version="test",
                validation_report_dir=str(tmp_path),
                auto_trading_historical_walk_forward_cache_hours=0.0,
                auto_trading_historical_walk_forward_warmup_5m_bars=3,
                auto_trading_historical_walk_forward_min_15m_bars=2,
                auto_trading_historical_walk_forward_max_5m_window_bars=12,
                auto_trading_historical_walk_forward_max_15m_window_bars=6,
                thesis_time_bucket_minutes=30,
            ),
            context_engine=_DummyContextEngine(),
            zone_engine=_DummyZoneEngine(),
            plan_generator=_DummyPlanGenerator(
                trigger_ts=(trigger_ts_1, trigger_ts_2),
                time_stop_bars=4,
            ),
        )
        payload = service.generate(
            eligible_symbols=(symbol,),
            eligible_families=("sweep_reversal",),
            eligible_entry_models=("LIMIT",),
            contract_scope="historical_walk_forward_strategy_level",
            cache_key="independent_signals",
            generate_on_new_15m_only=True,
            independent_signal_mode=True,
            max_candidates_per_bar=1,
        )

    assert len(payload["trade_rows"]) == 2
    assert payload["symbol_summaries"][0]["selected_contract_candidate_count"] == 2
    assert payload["symbol_summaries"][0]["closed_trade_count"] == 2
    assert {row["final_exit_reason"] for row in payload["trade_rows"]} == {"time_failure"}


def test_historical_walk_forward_can_replay_historical_generated_plans(tmp_path) -> None:
    init_db()
    symbol = "ETHUSDC"
    start = datetime(2026, 4, 18, 0, 0, tzinfo=timezone.utc)
    plan_ts_1 = start + timedelta(minutes=30)
    plan_ts_2 = start + timedelta(minutes=60)

    with SessionLocal() as db:
        repo = CandleRepository(db)
        for offset in range(48):
            ts = start + timedelta(minutes=5 * offset)
            candle = _candle(
                symbol=symbol,
                timeframe="5m",
                ts=ts,
                o=100.0,
                h=100.3,
                l=99.7,
                c=100.0,
            )
            repo.upsert(candle)
        for offset in range(16):
            ts = start + timedelta(minutes=15 * offset)
            repo.upsert(
                _candle(
                    symbol=symbol,
                    timeframe="15m",
                    ts=ts,
                    o=100.0,
                    h=100.3,
                    l=99.7,
                    c=100.0,
                )
            )

        db.add_all(
            [
                Plan(
                    plan_id="hist_plan_1",
                    zone_id="zone_hist_plan_1",
                    symbol=symbol,
                    timeframe="5m",
                    direction="long",
                    entry_model="LIMIT",
                    entry_price=100.0,
                    entry_condition="touch_limit",
                    sl=99.0,
                    tp1=101.0,
                    tp2=102.0,
                    tp3=103.0,
                    split={"tp1": 0.4, "tp2": 0.3, "runner": 0.3},
                    rr_min=1.0,
                    rr_base=2.0,
                    rr_opt=3.0,
                    ev=0.8,
                    cost_est=0.01,
                    confidence=0.7,
                    validity={
                        "strategy_family": "sweep_reversal",
                        "strategy_grade": "A",
                        "strategy_family_time_stop_max_bars": 4,
                        "thesis_cluster_id": "hist_cluster_1",
                    },
                    state="PLANNED",
                    valid_from=plan_ts_1,
                    valid_until=plan_ts_1 + timedelta(minutes=30),
                    strategy_version="test",
                ),
                Plan(
                    plan_id="hist_plan_2",
                    zone_id="zone_hist_plan_2",
                    symbol=symbol,
                    timeframe="5m",
                    direction="long",
                    entry_model="CONFIRM",
                    entry_price=100.0,
                    entry_condition="touch_limit",
                    sl=99.0,
                    tp1=101.0,
                    tp2=102.0,
                    tp3=103.0,
                    split={"tp1": 0.4, "tp2": 0.3, "runner": 0.3},
                    rr_min=1.0,
                    rr_base=2.0,
                    rr_opt=3.0,
                    ev=0.8,
                    cost_est=0.01,
                    confidence=0.7,
                    validity={
                        "strategy_family": "trend_continuation",
                        "strategy_grade": "A",
                        "strategy_family_time_stop_max_bars": 4,
                        "thesis_cluster_id": "hist_cluster_2",
                    },
                    state="PLANNED",
                    valid_from=plan_ts_2,
                    valid_until=plan_ts_2 + timedelta(minutes=30),
                    strategy_version="test",
                ),
            ]
        )
        db.commit()

        service = HistoricalWalkForwardProofService(
            candle_repo=repo,
            settings=SimpleNamespace(
                strategy_version="test",
                validation_report_dir=str(tmp_path),
                auto_trading_historical_walk_forward_cache_hours=0.0,
                auto_trading_historical_walk_forward_warmup_5m_bars=3,
                auto_trading_historical_walk_forward_min_15m_bars=2,
                auto_trading_historical_walk_forward_max_5m_window_bars=12,
                auto_trading_historical_walk_forward_max_15m_window_bars=6,
                thesis_time_bucket_minutes=30,
            ),
            context_engine=_DummyContextEngine(),
            zone_engine=_DummyZoneEngine(),
            plan_generator=_DummyPlanGenerator(trigger_ts=plan_ts_1),
        )
        payload = service.generate(
            eligible_symbols=(symbol,),
            eligible_families=("sweep_reversal", "trend_continuation"),
            eligible_entry_models=("LIMIT", "CONFIRM"),
            contract_scope="historical_walk_forward_strategy_level",
            cache_key="historical_generated_plans",
            source_mode="historical_generated_plans",
        )

    assert len(payload["trade_rows"]) == 2
    assert payload["symbol_summaries"][0]["generated_contract_candidate_count"] == 2
    assert payload["symbol_summaries"][0]["selected_contract_candidate_count"] == 2


def test_historical_walk_forward_raw_candle_heuristic_generates_strategy_samples(tmp_path) -> None:
    init_db()
    symbol = "BTCUSDC"
    start = datetime(2026, 4, 1, 0, 0, tzinfo=timezone.utc)

    with SessionLocal() as db:
        repo = CandleRepository(db)
        for offset in range(180):
            ts = start + timedelta(minutes=5 * offset)
            base = 100.0 + 0.01 * offset
            if offset in {120, 150}:
                candle = _candle(
                    symbol=symbol,
                    timeframe="5m",
                    ts=ts,
                    o=100.1,
                    h=100.6,
                    l=98.7,
                    c=100.35,
                )
            elif offset in {121, 122, 123, 151, 152, 153}:
                candle = _candle(
                    symbol=symbol,
                    timeframe="5m",
                    ts=ts,
                    o=100.4,
                    h=102.8,
                    l=100.2,
                    c=102.2,
                )
            else:
                candle = _candle(
                    symbol=symbol,
                    timeframe="5m",
                    ts=ts,
                    o=base - 0.08,
                    h=base + 0.12,
                    l=base - 0.12,
                    c=base,
                )
            repo.upsert(candle)

        for offset in range(60):
            ts = start + timedelta(minutes=15 * offset)
            base = 100.0 + 0.06 * offset
            repo.upsert(
                _candle(
                    symbol=symbol,
                    timeframe="15m",
                    ts=ts,
                    o=base - 0.15,
                    h=base + 0.25,
                    l=base - 0.25,
                    c=base,
                )
            )
        db.commit()

        service = HistoricalWalkForwardProofService(
            candle_repo=repo,
            settings=SimpleNamespace(
                strategy_version="test",
                validation_report_dir=str(tmp_path),
                auto_trading_historical_walk_forward_cache_hours=0.0,
                auto_trading_historical_walk_forward_warmup_5m_bars=30,
                auto_trading_historical_walk_forward_min_15m_bars=20,
                auto_trading_historical_walk_forward_max_5m_window_bars=120,
                auto_trading_historical_walk_forward_max_15m_window_bars=80,
                thesis_time_bucket_minutes=30,
            ),
        )
        payload = service.generate(
            eligible_symbols=(symbol,),
            eligible_families=("sweep_reversal", "trend_continuation"),
            eligible_entry_models=("LIMIT", "SWEEP_CONFIRM", "CONFIRM"),
            contract_scope="historical_walk_forward_strategy_level",
            cache_key="raw_strategy_samples",
            generate_on_new_15m_only=True,
            independent_signal_mode=True,
            max_candidates_per_bar=1,
            source_mode="raw_candle_heuristic",
        )

    assert len(payload["trade_rows"]) >= 2
    assert payload["symbol_summaries"][0]["generated_contract_candidate_count"] >= 2
    assert payload["symbol_summaries"][0]["closed_trade_count"] >= 2
    assert any(bool(row.get("historical_raw_signal")) for row in payload["trade_rows"])
    assert any(
        dict(row.get("raw_signal_features") or {}).get("signal_family") == "sweep_reversal"
        and "directional_close_position" in dict(row.get("raw_signal_features") or {})
        and "sweep_distance_atr" in dict(row.get("raw_signal_features") or {})
        and "entry_offset_r" in dict(row.get("raw_signal_features") or {})
        and "risk_atr" in dict(row.get("raw_signal_features") or {})
        for row in payload["trade_rows"]
    )


def test_historical_walk_forward_tolerates_malformed_numeric_settings(tmp_path) -> None:
    init_db()
    with SessionLocal() as db:
        repo = CandleRepository(db)
        settings = SimpleNamespace(
            strategy_version="test",
            validation_report_dir=str(tmp_path),
            auto_trading_historical_walk_forward_cache_hours="bad",
            auto_trading_historical_walk_forward_warmup_5m_bars="bad",
            auto_trading_historical_walk_forward_min_15m_bars=float("inf"),
            auto_trading_historical_walk_forward_max_5m_window_bars="bad",
            auto_trading_historical_walk_forward_max_15m_window_bars=float("inf"),
            thesis_time_bucket_minutes="bad",
            btc_sweep_reversal_limit_fast_failure_enabled=True,
            btc_sweep_reversal_limit_fast_failure_allowed_sessions="",
            btc_sweep_reversal_limit_fast_failure_max_bars=float("inf"),
            btc_sweep_reversal_limit_fast_failure_stop_r="bad",
            btc_sweep_reversal_limit_fast_failure_requires_sl_touch=True,
        )
        service = HistoricalWalkForwardProofService(
            candle_repo=repo,
            settings=settings,
            context_engine=_DummyContextEngine(),
            zone_engine=_DummyZoneEngine(),
            plan_generator=_DummyPlanGenerator(trigger_ts=datetime(2026, 1, 1, tzinfo=timezone.utc)),
        )

        fingerprint = service._replay_settings_fingerprint()
        payload = service._simulate_symbol(
            symbol="BTCUSDC",
            start_ts=datetime(2026, 1, 1, tzinfo=timezone.utc),
            end_ts=datetime(2026, 1, 2, tzinfo=timezone.utc),
            eligible_symbols={"BTCUSDC"},
            eligible_families={"sweep_reversal"},
            eligible_entry_models={"LIMIT"},
            generate_on_new_15m_only=True,
            independent_signal_mode=False,
            max_candidates_per_bar=1,
            source_mode="engine_regenerated",
            blocked_time_contract=[],
            blocked_plan_ids=set(),
        )

    assert fingerprint["btc_sweep_reversal_limit_fast_failure_max_bars"] == 18
    assert fingerprint["btc_sweep_reversal_limit_fast_failure_stop_r"] == 0.00000001
    assert payload["eligible_bar_count"] == 0
