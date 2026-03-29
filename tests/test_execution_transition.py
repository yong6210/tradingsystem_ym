from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.enums import ExecutionMode, OrderLifecycleState, RiskGateState
from app.db.models import BinanceOrderLedger, BinancePositionSnapshot, Candle, ExecutionFill, OrderIntent, OrderSubmission, Plan
from app.db.repositories import (
    FamilyRolloutPolicyRepository,
    OrderIntentRepository,
    OrderSubmissionRepository,
    PlanRepository,
    SafetyLockRepository,
)
from app.db.session import SessionLocal, init_db
from app.main import app
from app.services.strategy_engine import StrategyEngine
from app.services.family_rollout import RolloutPolicyService
from app.services.operating_lock import OperatingLockSnapshot
from app.services.safety_locks import SafetyLockService
from app.services.thesis_fingerprint import ThesisFingerprintService

client = TestClient(app)


def _reset_execution_control_state() -> None:
    with SessionLocal() as db:
        safety = SafetyLockService(repo=SafetyLockRepository(db), settings=get_settings())
        for reason_code in [
            "close_only_active",
            "kill_switch_active",
            "reconciliation_user_stream_stale",
        ]:
            safety.release_reason(scope_type="GLOBAL", reason_code=reason_code)

        rollout = RolloutPolicyService(repo=FamilyRolloutPolicyRepository(db))
        rollout.upsert(
            family="trend_continuation",
            live_enabled=True,
            max_execution_mode="MICRO_LIVE",
            max_risk_r=1.0,
            allowed_sessions=["london", "new_york"],
            min_quality_score=75.0,
            updated_by="test_reset",
        )
        rollout.upsert(
            family="sweep_reversal",
            live_enabled=False,
            max_execution_mode="PAPER",
            max_risk_r=0.5,
            allowed_sessions=["london", "new_york"],
            min_quality_score=70.0,
            updated_by="test_reset",
        )
        rollout.upsert(
            family="range_rotation",
            live_enabled=False,
            max_execution_mode="SHADOW",
            max_risk_r=0.25,
            allowed_sessions=["london", "new_york"],
            min_quality_score=68.0,
            updated_by="test_reset",
        )
        db.commit()


def _apply_auto_trading_defaults(monkeypatch) -> None:
    _reset_execution_control_state()
    settings = get_settings()
    monkeypatch.setattr(settings, "auto_trading_enabled", True)
    monkeypatch.setattr(settings, "auto_trading_execution_mode", ExecutionMode.LIVE)
    monkeypatch.setattr(settings, "auto_trading_allowed_symbols", "")
    monkeypatch.setattr(settings, "auto_trading_allowed_families", "")
    monkeypatch.setattr(settings, "auto_trading_close_only", False)
    monkeypatch.setattr(settings, "auto_trading_require_validation_go", True)
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_symbols", "")
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_families", "")
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_sessions", "london,new_york,overlap")
    monkeypatch.setattr(settings, "auto_trading_micro_live_max_concurrent_positions", 5)
    monkeypatch.setattr(settings, "auto_trading_micro_live_max_daily_new_entries", 10)
    monkeypatch.setattr(settings, "auto_trading_reconciliation_user_stream_stale_seconds", 180)
    monkeypatch.setattr(settings, "binance_trade_live_enabled", False)
    monkeypatch.setattr(settings, "portfolio_overlay_enabled", False)


def _seed_plan(
    *,
    symbol: str,
    family: str,
    plan_id: str,
    state: str = "ARMED",
    strategy_grade: str = "A",
    thesis_fingerprint: dict | None = None,
) -> None:
    with SessionLocal() as db:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        db.add(
            Plan(
                plan_id=plan_id,
                zone_id=f"{symbol}_z1",
                symbol=symbol,
                timeframe="5m",
                direction="long",
                entry_model="CONFIRM",
                entry_price=100.0,
                entry_condition="touch_then_confirm",
                sl=98.5,
                tp1=101.0,
                tp2=102.0,
                tp3=103.0,
                split={"tp1": 0.6, "tp2": 0.25, "runner": 0.15},
                rr_min=1.2,
                rr_base=1.8,
                rr_opt=2.4,
                ev=0.35,
                cost_est=0.05,
                confidence=0.81,
                validity={
                    "strategy_family": family,
                    "strategy_grade": strategy_grade,
                    "strategy_family_score": 82.0,
                    "recommended_risk_r": 0.5,
                    "reaction_classification": "rejection_confirmed",
                    "regime": "trend",
                    "strategy_mode": "A_ONLY",
                    "expected_ev_r": 0.42,
                    "expected_summary": "test expected summary",
                    "thesis_fingerprint": dict(thesis_fingerprint or {}),
                },
                state=state,
                valid_from=now - timedelta(minutes=15),
                valid_until=now + timedelta(hours=6),
                strategy_version="v1",
            )
        )
        db.commit()


def _good_metrics(self, symbol: str, version: str) -> dict:
    return {
        "symbol": symbol,
        "version": version,
        "grade": "A",
        "recommendation": "deploy",
        "risk_state": "OPEN",
        "risk_reason": "normal",
        "operating_lock": {
            "active": False,
            "enforced": False,
            "reason": "",
            "scope": "none",
            "current_session": {"name": "london", "active": True},
        },
    }


def _open_gate_context(self, *, symbol: str):
    return (
        None,
        RiskGateState.OPEN,
        "normal",
        OperatingLockSnapshot(
            state=RiskGateState.OPEN,
            active=False,
            enforced=False,
            reason="",
            scope="none",
            strategy_mode="A_ONLY",
            unlock_at=None,
            current_session={"name": "london", "active": True},
            daily_stats={"trades": 0, "realized_r": 0.0, "loss_streak": 0, "a_grade_loss_streak": 0, "last_trade": None, "loss_limit_r": -2.0},
            session_stats={"trades": 0, "realized_r": 0.0, "loss_streak": 0, "last_trade": None, "loss_limit_r": -1.5},
        ),
    )


def test_execution_preview_and_approval_respect_family_rollout(monkeypatch) -> None:
    init_db()
    _apply_auto_trading_defaults(monkeypatch)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine.metrics", _good_metrics)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._gate_context_for_symbol", _open_gate_context)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._today_trade_count", lambda self: 0)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._current_exposure_rows", lambda self: [])

    symbol = f"EXECPRE{int(datetime.now(timezone.utc).timestamp() * 1_000_000)}USDC"
    plan_id = f"{symbol}_plan"
    _seed_plan(symbol=symbol, family="trend_continuation", plan_id=plan_id)

    preview = client.post("/execution/plans/preview", json={"plan_id": plan_id})
    assert preview.status_code == 200
    preview_payload = preview.json()
    assert preview_payload["plan_id"] == plan_id
    assert preview_payload["strategy_family"] == "trend_continuation"

    approval = client.post("/execution/approve-plan", json={"plan_id": plan_id})
    assert approval.status_code == 200
    approval_payload = approval.json()
    assert approval_payload["approval_state"] == "APPROVED_AUTO"
    assert approval_payload["allowed_execution_mode"] == "MICRO_LIVE"
    assert approval_payload["rollout_policy"]["max_execution_mode"] == "MICRO_LIVE"


def test_order_intent_and_paper_submit_flow_updates_position_state(monkeypatch) -> None:
    init_db()
    _apply_auto_trading_defaults(monkeypatch)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine.metrics", _good_metrics)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._gate_context_for_symbol", _open_gate_context)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._today_trade_count", lambda self: 0)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._current_exposure_rows", lambda self: [])

    symbol = f"PAPER{int(datetime.now(timezone.utc).timestamp() * 1_000_000) + 1}USDC"
    plan_id = f"{symbol}_plan"
    _seed_plan(symbol=symbol, family="sweep_reversal", plan_id=plan_id)

    intent = client.post(
        "/execution/order-intents",
        json={"plan_id": plan_id, "execution_mode": "PAPER"},
    )
    assert intent.status_code == 200
    intent_payload = intent.json()
    assert intent_payload["submit_decision"] == "SUBMIT"
    assert intent_payload["allowed_execution_mode"] == "PAPER"
    assert intent_payload["deployment_go_no_go"] == intent_payload["approval"]["deployment_go_no_go"]
    assert intent_payload["deployment_code"] == intent_payload["approval"]["deployment_code"]
    assert intent_payload["playbook_action"] == intent_payload["approval"]["playbook_action"]
    assert intent_payload["source_of_truth_hint"] == "execution_approval_snapshot"

    submit = client.post(
        "/execution/submit",
        json={"intent_id": intent_payload["intent_id"], "live": False, "paper_scenario": "fill"},
    )
    assert submit.status_code == 200
    submit_payload = submit.json()
    assert submit_payload["adapter"] == "paper"
    assert submit_payload["state"] == "FILLED"
    assert submit_payload["fill_results"][0]["to_state"] == "ENTERED"

    with SessionLocal() as db:
        refreshed = db.get(Plan, plan_id)
        assert refreshed is not None
        assert refreshed.state == "ENTERED"


def test_paper_exit_tick_closes_filled_paper_positions_on_targets(monkeypatch) -> None:
    init_db()
    _apply_auto_trading_defaults(monkeypatch)

    symbol = f"PEXIT{int(datetime.now(timezone.utc).timestamp() * 1_000_000) + 2}USDC"
    plan_id = f"{symbol}_plan"
    _seed_plan(symbol=symbol, family="sweep_reversal", plan_id=plan_id, state="ENTERED")

    now = datetime.now(timezone.utc).replace(microsecond=0)
    with SessionLocal() as db:
        db.add(
            OrderSubmission(
                submission_id=f"sub_{symbol}",
                intent_id=f"intent_{symbol}",
                plan_id=plan_id,
                symbol=symbol,
                client_order_id=f"client_{symbol}",
                exchange_order_id=f"paper_{symbol}",
                state=OrderLifecycleState.FILLED.value,
                submit_status="FILLED",
                message="paper filled",
                adapter="paper",
                execution_mode="PAPER",
                attachments={},
                side="BUY",
                order_type="LIMIT",
                reduce_only=False,
                requested_live=False,
                raw={},
                submitted_at=now,
                acknowledged_at=now,
            )
        )
        db.add(
            Candle(
                symbol=symbol,
                timeframe="1m",
                ts=now,
                o=100.0,
                h=103.5,
                l=99.5,
                c=103.1,
                v=1000.0,
                source="test",
                is_final=True,
            )
        )
        db.commit()

    with SessionLocal() as db:
        engine = StrategyEngine(db)
        payload = engine.process_paper_exit_tick(
            families=["sweep_reversal"],
            days=2,
            limit=20,
            sync_candles=False,
            limit_1m=1,
            limit_5m=1,
        )
        assert payload["paper_candidate_plans"] >= 1
        assert payload["partial_exit_events"] == 2
        assert payload["closed_events"] == 1

    with SessionLocal() as db:
        refreshed = db.get(Plan, plan_id)
        assert refreshed is not None
        assert refreshed.state == "CLOSED"
        validity = dict(refreshed.validity or {})
        assert validity["final_exit_reason"] == "target_tp3"
        fills = (
            db.query(ExecutionFill)
            .filter(ExecutionFill.plan_id == plan_id)
            .order_by(ExecutionFill.fill_ts.asc())
            .all()
        )
        assert [fill.stage for fill in fills] == ["PARTIAL_EXIT", "PARTIAL_EXIT", "CLOSED"]


def test_plan_upsert_preserves_entered_plan_history_by_rolling_plan_id() -> None:
    init_db()
    symbol = f"PCOLL{int(datetime.now(timezone.utc).timestamp() * 1_000_000) + 3}USDC"
    plan_id = f"{symbol}_plan"
    _seed_plan(symbol=symbol, family="sweep_reversal", plan_id=plan_id, state="ENTERED")

    with SessionLocal() as db:
        repo = PlanRepository(db)
        now = datetime.now(timezone.utc).replace(microsecond=0)
        repo.upsert_many(
            [
                Plan(
                    plan_id=plan_id,
                    zone_id=f"{symbol}_z1",
                    symbol=symbol,
                    timeframe="5m",
                    direction="long",
                    entry_model="CONFIRM",
                    entry_price=101.0,
                    entry_condition="refresh",
                    sl=99.0,
                    tp1=102.0,
                    tp2=103.0,
                    tp3=104.0,
                    split={"tp1": 0.5, "tp2": 0.3, "runner": 0.2},
                    rr_min=1.0,
                    rr_base=1.5,
                    rr_opt=2.0,
                    ev=0.2,
                    cost_est=0.05,
                    confidence=0.7,
                    validity={
                        "strategy_family": "legacy_zone_plan",
                        "strategy_family_reason": "trend_continuation_not_applicable",
                    },
                    state="PLANNED",
                    valid_from=now,
                    valid_until=now + timedelta(hours=2),
                    strategy_version="v1",
                )
            ]
        )
        db.commit()

    with SessionLocal() as db:
        original = db.get(Plan, plan_id)
        assert original is not None
        assert original.state == "ENTERED"
        rows = db.query(Plan).filter(Plan.symbol == symbol).order_by(Plan.valid_from.asc()).all()
        assert len(rows) == 2
        rolled = next(row for row in rows if row.plan_id != plan_id)
        assert rolled.state == "PLANNED"
        assert rolled.plan_id.startswith(plan_id[: min(len(plan_id), 40)])
        validity = dict(rolled.validity or {})
        assert validity["supersedes_plan_id"] == plan_id
        assert validity["collision_preserved_existing_state"] == "ENTERED"


def test_execution_candidate_rows_apply_outcome_sizing_clamp(monkeypatch) -> None:
    init_db()
    _apply_auto_trading_defaults(monkeypatch)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._gate_context_for_symbol", _open_gate_context)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._today_trade_count", lambda self: 0)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._current_exposure_rows", lambda self: [])

    def _stub_outcome_inputs(self, *, symbols, days=180, portfolio_budget_by_symbol=None):
        return {
            str(symbols[0]): {
                "family_execution_degradation_advisory_summary": {
                    "families": [
                        {
                            "family": "trend_continuation",
                            "status": "manual_review",
                            "confidence": "high",
                            "sample_note": "family closed sample is sufficient for advisory use",
                        }
                    ]
                },
                "mode_advisory_summary": {"family": [], "regime": [], "session": []},
                "score_to_outcome_funnel_summary": {
                    "decomposition": {
                        "family": [
                            {
                                "key": "trend_continuation",
                                "closed": 6,
                                "baseline_cost_profitable_rate_from_closed": 0.2,
                            }
                        ],
                        "regime": [],
                        "session": [],
                    }
                },
            }
        }

    monkeypatch.setattr(
        "app.services.strategy_engine.StrategyEngine._outcome_inputs_for_symbols",
        _stub_outcome_inputs,
    )

    symbol = f"OUTCOME{int(datetime.now(timezone.utc).timestamp() * 1_000_000) + 2}USDC"
    plan_id = f"{symbol}_plan"
    _seed_plan(symbol=symbol, family="trend_continuation", plan_id=plan_id)

    with SessionLocal() as db:
        engine = StrategyEngine(db)
        _, candidate_rows, _ = engine._execution_candidate_rows(symbol=symbol)

    assert candidate_rows
    row = candidate_rows[0]
    adjustment = row["strategy_sizing"]["outcome_risk_adjustment"]
    assert adjustment["applied"] is True
    assert adjustment["penalty_tier"] == "hard_clamp"
    assert row["recommended_risk_r"] == adjustment["final_risk_r"]
    assert row["recommended_risk_r"] == round(adjustment["base_final_risk_r"] * 0.5, 4)


def test_order_intent_uses_execution_layer_open_intent_for_duplicate_thesis(monkeypatch) -> None:
    init_db()
    _apply_auto_trading_defaults(monkeypatch)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine.metrics", _good_metrics)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._gate_context_for_symbol", _open_gate_context)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._today_trade_count", lambda self: 0)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._current_exposure_rows", lambda self: [])

    symbol = f"DEDUPE{int(datetime.now(timezone.utc).timestamp() * 1_000_000) + 11}USDC"
    existing_plan_id = f"{symbol}_existing"
    fresh_plan_id = f"{symbol}_fresh"
    _seed_plan(symbol=symbol, family="trend_continuation", plan_id=existing_plan_id, state="CLOSED")
    _seed_plan(symbol=symbol, family="trend_continuation", plan_id=fresh_plan_id, state="ARMED")

    with SessionLocal() as db:
        existing_plan = db.get(Plan, existing_plan_id)
        assert existing_plan is not None
        existing_fingerprint = ThesisFingerprintService(get_settings()).build_from_plan(existing_plan)
        db.add(
            OrderIntent(
                intent_id=f"intent_{symbol}_existing",
                plan_id=existing_plan_id,
                symbol=symbol,
                strategy_family="trend_continuation",
                execution_mode="MICRO_LIVE",
                approval_state="APPROVED_AUTO",
                submit_decision="SUBMIT",
                decision_reason_code="submit_ready",
                decision_reason_message="ready",
                thesis_fingerprint=existing_fingerprint,
                dedupe_result={"status": "unique"},
                session_guidance={"state": "london"},
                quality_snapshot={"validation_grade": "A"},
                approval_snapshot={
                    "approval_state": "APPROVED_AUTO",
                    "allowed_execution_mode": "MICRO_LIVE",
                    "deployment_go_no_go": "GO",
                    "deployment_code": "go_execution_auto_submit",
                    "playbook_go_no_go": "GO",
                    "playbook_code": "go_execution_auto_submit",
                    "playbook_action": "allow_auto_submit",
                    "playbook_message": "GO: execution path is auto-approved.",
                },
                payload={},
            )
        )
        db.commit()

    intent = client.post(
        "/execution/order-intents",
        json={"plan_id": fresh_plan_id, "execution_mode": "MICRO_LIVE"},
    )
    assert intent.status_code == 200
    intent_payload = intent.json()
    assert intent_payload["submit_decision"] == "SKIP_DUPLICATE"
    assert intent_payload["decision_reason_code"] == "duplicate_active_thesis"
    assert intent_payload["dedupe_result"]["source"] == "open_intent"
    assert intent_payload["dedupe_result"]["matched_intent_id"] == f"intent_{symbol}_existing"


def test_paper_lineage_override_allows_active_plan_duplicate_for_eligible_family(monkeypatch) -> None:
    init_db()
    _apply_auto_trading_defaults(monkeypatch)
    settings = get_settings()
    monkeypatch.setattr(settings, "auto_trading_execution_mode", ExecutionMode.PAPER)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine.metrics", _good_metrics)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._gate_context_for_symbol", _open_gate_context)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._today_trade_count", lambda self: 0)

    symbol = f"PLINE{int(datetime.now(timezone.utc).timestamp() * 1_000_000) + 12}USDC"
    existing_plan_id = f"{symbol}_existing"
    fresh_plan_id = f"{symbol}_fresh"
    shared_thesis = {
        "direction": "long",
        "regime": "trend",
        "strategy_family": "sweep_reversal",
        "liquidity_narrative": "session_low_sweep",
        "event_classification": "rejection_confirmed",
        "time_bucket": "2026-03-09T05:00Z_30m",
        "correlation_cluster": "others",
    }
    _seed_plan(
        symbol=symbol,
        family="sweep_reversal",
        plan_id=existing_plan_id,
        state="ENTERED",
        thesis_fingerprint=shared_thesis,
    )
    _seed_plan(
        symbol=symbol,
        family="sweep_reversal",
        plan_id=fresh_plan_id,
        state="ARMED",
        thesis_fingerprint=shared_thesis,
    )

    def _exposures(self):
        with SessionLocal() as db:
            row = db.get(Plan, existing_plan_id)
            return [row] if row is not None else []

    def _candidate_rows(self, *, symbol: str):
        return None, [
            {
                "plan_id": fresh_plan_id,
                "symbol": symbol,
                "direction": "long",
                "strategy_family": "sweep_reversal",
                "strategy_grade": "A",
                "deployment_go_no_go": "GO",
                "deployment_code": "go_runtime_gate_open",
                "deployment_message": "GO: runtime gate is open for candidate review.",
                "block_reason": "thesis_duplicate_blocked",
                "block_reason_message": "Blocked: an active candidate with the same thesis already exists.",
                "thesis_rejected_reason": "duplicate_active_thesis",
                "recommended_risk_r": 0.5,
                "session_guidance": {"state": "london", "session_name": "london"},
                "operating_lock": {"active": False, "current_session": {"name": "london", "active": True}},
                "final_rank_score": 80.0,
            }
        ], {"active": False, "current_session": {"name": "london", "active": True}}

    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._current_exposure_rows", _exposures)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._execution_candidate_rows", _candidate_rows)

    blocked = client.post("/execution/approve-plan", json={"plan_id": fresh_plan_id})
    assert blocked.status_code == 200
    assert blocked.json()["approval_state"] == "BLOCKED"

    approval = client.post(
        "/execution/approve-plan",
        json={"plan_id": fresh_plan_id, "paper_lineage_override": True},
    )
    assert approval.status_code == 200
    approval_payload = approval.json()
    assert approval_payload["paper_lineage_override_applied"] is True
    assert approval_payload["approval_state"] == "APPROVED_AUTO"
    assert approval_payload["allowed_execution_mode"] == "PAPER"

    intent = client.post(
        "/execution/order-intents",
        json={"plan_id": fresh_plan_id, "execution_mode": "PAPER", "paper_lineage_override": True},
    )
    assert intent.status_code == 200
    intent_payload = intent.json()
    assert intent_payload["submit_decision"] == "SUBMIT"
    assert intent_payload["dedupe_result"]["source"] == "active_plan"
    assert intent_payload["paper_lineage_override_applied"] is True


def test_paper_lineage_override_does_not_bypass_open_intent_duplicate(monkeypatch) -> None:
    init_db()
    _apply_auto_trading_defaults(monkeypatch)
    settings = get_settings()
    monkeypatch.setattr(settings, "auto_trading_execution_mode", ExecutionMode.PAPER)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine.metrics", _good_metrics)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._gate_context_for_symbol", _open_gate_context)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._today_trade_count", lambda self: 0)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._current_exposure_rows", lambda self: [])

    symbol = f"PLNO{int(datetime.now(timezone.utc).timestamp() * 1_000_000) + 13}USDC"
    existing_plan_id = f"{symbol}_existing"
    fresh_plan_id = f"{symbol}_fresh"
    _seed_plan(symbol=symbol, family="trend_continuation", plan_id=existing_plan_id, state="CLOSED")
    _seed_plan(symbol=symbol, family="trend_continuation", plan_id=fresh_plan_id, state="ARMED")

    with SessionLocal() as db:
        existing_plan = db.get(Plan, existing_plan_id)
        assert existing_plan is not None
        existing_fingerprint = ThesisFingerprintService(get_settings()).build_from_plan(existing_plan)
        db.add(
            OrderIntent(
                intent_id=f"intent_{symbol}_existing",
                plan_id=existing_plan_id,
                symbol=symbol,
                strategy_family="trend_continuation",
                execution_mode="PAPER",
                approval_state="APPROVED_AUTO",
                submit_decision="SUBMIT",
                decision_reason_code="submit_ready",
                decision_reason_message="ready",
                thesis_fingerprint=existing_fingerprint,
                dedupe_result={"status": "unique"},
                session_guidance={"state": "london"},
                quality_snapshot={"validation_grade": "A"},
                approval_snapshot={
                    "approval_state": "APPROVED_AUTO",
                    "allowed_execution_mode": "PAPER",
                    "deployment_go_no_go": "GO",
                    "deployment_code": "go_execution_auto_submit",
                    "playbook_go_no_go": "GO",
                    "playbook_code": "go_execution_auto_submit",
                    "playbook_action": "allow_auto_submit",
                    "playbook_message": "GO: execution path is auto-approved.",
                },
                payload={},
            )
        )
        db.commit()

    intent = client.post(
        "/execution/order-intents",
        json={"plan_id": fresh_plan_id, "execution_mode": "PAPER", "paper_lineage_override": True},
    )
    assert intent.status_code == 200
    intent_payload = intent.json()
    assert intent_payload["submit_decision"] == "SKIP_DUPLICATE"
    assert intent_payload["dedupe_result"]["source"] == "open_intent"


def test_paper_lineage_override_bypasses_allowlist_and_validation_for_paper_sampling(monkeypatch) -> None:
    init_db()
    _apply_auto_trading_defaults(monkeypatch)
    settings = get_settings()
    monkeypatch.setattr(settings, "auto_trading_execution_mode", ExecutionMode.PAPER)
    monkeypatch.setattr(settings, "auto_trading_allowed_symbols", "BTCUSDC")
    monkeypatch.setattr(settings, "auto_trading_allowed_families", "trend_continuation")
    monkeypatch.setattr(
        "app.services.strategy_engine.StrategyEngine.metrics",
        lambda self, symbol, version: {  # noqa: ARG005
            "symbol": symbol,
            "version": version,
            "grade": "F",
            "recommendation": "do-not-deploy",
            "risk_state": "OPEN",
            "risk_reason": "normal",
            "operating_lock": {
                "active": False,
                "enforced": False,
                "reason": "",
                "scope": "none",
                "current_session": {"name": "london", "active": True},
            },
        },
    )
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._gate_context_for_symbol", _open_gate_context)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._today_trade_count", lambda self: 0)
    monkeypatch.setattr(
        "app.services.strategy_engine.StrategyEngine._approval_outcome_inputs",
        lambda self, *, symbol, candidate_rows: {  # noqa: ARG005
            "execution_degradation_advisory_summary": {
                "status": "manual_review",
                "reason_codes": ["slippage_p95_exceeds_live_tolerance"],
            },
            "score_to_outcome_funnel_summary": {
                "historical_execution_outcomes": {"baseline_cost_profitable_rate_from_closed": 0.0},
                "decomposition": {"family": [], "regime": [], "session": []},
            },
            "mode_advisory_summary": {"family": [], "regime": [], "session": []},
        },
    )

    symbol = f"PLALW{int(datetime.now(timezone.utc).timestamp() * 1_000_000) + 14}USDC"
    existing_plan_id = f"{symbol}_existing"
    fresh_plan_id = f"{symbol}_fresh"
    shared_thesis = {
        "direction": "long",
        "regime": "range",
        "strategy_family": "sweep_reversal",
        "liquidity_narrative": "session_low_sweep",
        "event_classification": "rejection_confirmed",
        "time_bucket": "2026-03-09T05:00Z_30m",
        "correlation_cluster": "others",
    }
    _seed_plan(
        symbol=symbol,
        family="sweep_reversal",
        plan_id=existing_plan_id,
        state="ENTERED",
        thesis_fingerprint=shared_thesis,
    )
    _seed_plan(
        symbol=symbol,
        family="sweep_reversal",
        plan_id=fresh_plan_id,
        state="ARMED",
        thesis_fingerprint=shared_thesis,
    )

    def _exposures(self):
        with SessionLocal() as db:
            row = db.get(Plan, existing_plan_id)
            return [row] if row is not None else []

    def _candidate_rows(self, *, symbol: str):
        return None, [
            {
                "plan_id": fresh_plan_id,
                "symbol": symbol,
                "direction": "long",
                "strategy_family": "sweep_reversal",
                "strategy_grade": "A",
                "deployment_go_no_go": "GO",
                "deployment_code": "go_runtime_gate_open",
                "deployment_message": "GO: runtime gate is open for candidate review.",
                "block_reason": "thesis_duplicate_blocked",
                "block_reason_message": "Blocked: an active candidate with the same thesis already exists.",
                "thesis_rejected_reason": "duplicate_active_thesis",
                "recommended_risk_r": 0.5,
                "session_guidance": {"state": "london", "session_name": "london"},
                "operating_lock": {"active": False, "current_session": {"name": "london", "active": True}},
                "final_rank_score": 80.0,
            }
        ], {"active": False, "current_session": {"name": "london", "active": True}}

    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._current_exposure_rows", _exposures)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._execution_candidate_rows", _candidate_rows)

    approval = client.post(
        "/execution/approve-plan",
        json={"plan_id": fresh_plan_id, "paper_lineage_override": True},
    )
    assert approval.status_code == 200
    approval_payload = approval.json()
    assert approval_payload["approval_state"] == "APPROVED_AUTO"
    assert approval_payload["playbook_go_no_go"] == "GO"
    reason_codes = {row["code"] for row in approval_payload["approval_reasons"]}
    assert "paper_lineage_override_bypassed_symbol_allowlist" in reason_codes
    assert "paper_lineage_override_bypassed_family_allowlist" in reason_codes
    assert "paper_lineage_override_bypassed_validation_do_not_deploy" in reason_codes
    assert "paper_lineage_override_retained_paper_auto_submit" in reason_codes

    intent = client.post(
        "/execution/order-intents",
        json={"plan_id": fresh_plan_id, "execution_mode": "PAPER", "paper_lineage_override": True},
    )
    assert intent.status_code == 200
    intent_payload = intent.json()
    assert intent_payload["submit_decision"] == "SUBMIT"
    assert intent_payload["paper_lineage_override_applied"] is True

    submit = client.post(
        "/execution/submit",
        json={"intent_id": intent_payload["intent_id"], "live": False, "paper_scenario": "fill"},
    )
    assert submit.status_code == 200
    submit_payload = submit.json()
    assert submit_payload["adapter"] == "paper"
    assert submit_payload["state"] == "FILLED"
    assert submit_payload["submit_status"] == "FILLED"


def test_live_submit_requires_global_live_enable_even_when_intent_is_ready(monkeypatch) -> None:
    init_db()
    _apply_auto_trading_defaults(monkeypatch)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine.metrics", _good_metrics)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._gate_context_for_symbol", _open_gate_context)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._today_trade_count", lambda self: 0)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._current_exposure_rows", lambda self: [])

    symbol = f"LIVE{int(datetime.now(timezone.utc).timestamp() * 1_000_000) + 2}USDC"
    plan_id = f"{symbol}_plan"
    _seed_plan(symbol=symbol, family="trend_continuation", plan_id=plan_id)

    intent = client.post(
        "/execution/order-intents",
        json={"plan_id": plan_id, "execution_mode": "MICRO_LIVE"},
    )
    assert intent.status_code == 200
    intent_payload = intent.json()
    assert intent_payload["submit_decision"] == "SUBMIT"

    submit = client.post(
        "/execution/submit",
        json={"intent_id": intent_payload["intent_id"], "live": True},
    )
    assert submit.status_code == 200
    submit_payload = submit.json()
    assert submit_payload["state"] == "REJECTED"
    assert submit_payload["submit_status"] == "LIVE_DISABLED"


def test_reconcile_route_reports_missing_stop_stale_stream_and_size_mismatch() -> None:
    init_db()
    symbol = f"RECON{int(datetime.now(timezone.utc).timestamp() * 1_000_000) + 3}USDC"
    plan_id = f"{symbol}_entered"
    _seed_plan(symbol=symbol, family="trend_continuation", plan_id=plan_id, state="ENTERED")

    stale_ts = datetime.now(timezone.utc) - timedelta(hours=1)
    with SessionLocal() as db:
        db.add(
            BinancePositionSnapshot(
                position_key=f"{symbol}_both",
                symbol=symbol,
                position_side="BOTH",
                position_amt=2.0,
                entry_price=100.0,
                break_even_price=100.0,
                mark_price=101.0,
                liquidation_price=80.0,
                unrealized_pnl=2.0,
                notional=202.0,
                leverage=2,
                margin_type="cross",
                isolated_wallet=0.0,
                update_ts=stale_ts,
                raw={},
            )
        )
        db.add(
            BinanceOrderLedger(
                client_order_id=f"{symbol}_entry",
                exchange_order_id=123456,
                plan_id=plan_id,
                symbol=symbol,
                side="BUY",
                order_type="MARKET",
                status="NEW",
                reduce_only=False,
                requested_live=True,
                live_enabled=True,
                test_order=False,
                price=100.0,
                orig_qty=1.0,
                executed_qty=0.0,
                time_in_force="GTC",
                last_event_type="ORDER_TRADE_UPDATE",
                last_trade_id=None,
                last_event_ts=stale_ts,
                raw={},
            )
        )
        db.commit()

    reconcile = client.post("/execution/reconcile", json={"symbol": symbol})
    assert reconcile.status_code == 200
    payload = reconcile.json()
    mismatch_types = {item["mismatch_type"] for item in payload["mismatches"]}
    assert "POSITION_SIZE_MISMATCH" in mismatch_types
    assert "MISSING_STOP_ORDER" in mismatch_types
    assert "USER_STREAM_STALE" in mismatch_types
    assert payload["lock_required"] is True


def test_reconcile_handles_naive_submission_timestamp_and_reports_fill_gap() -> None:
    init_db()
    symbol = f"FILLGAP{int(datetime.now(timezone.utc).timestamp() * 1_000_000) + 31}USDC"
    plan_id = f"{symbol}_armed"
    _seed_plan(symbol=symbol, family="trend_continuation", plan_id=plan_id, state="ARMED")

    with SessionLocal() as db:
        db.add(
            OrderSubmission(
                submission_id=f"sub_{symbol}",
                intent_id=f"intent_{symbol}",
                plan_id=plan_id,
                symbol=symbol,
                client_order_id=f"client_{symbol}",
                exchange_order_id=None,
                state=OrderLifecycleState.SUBMITTED.value,
                submit_status="SUBMITTED",
                message="submitted",
                adapter="binance",
                execution_mode="MICRO_LIVE",
                attachments={},
                side="BUY",
                order_type="STOP_MARKET",
                reduce_only=False,
                requested_live=True,
                raw={},
                submitted_at=(datetime.now(timezone.utc) - timedelta(minutes=10)).replace(tzinfo=None),
            )
        )
        db.commit()

    reconcile = client.post("/execution/reconcile", json={"symbol": symbol})
    assert reconcile.status_code == 200
    payload = reconcile.json()
    mismatch_types = {item["mismatch_type"] for item in payload["mismatches"]}
    assert "FILL_EVENT_GAP" in mismatch_types
    assert payload["lock_required"] is True


def test_order_intent_and_submission_repositories_support_create_get_and_transition() -> None:
    init_db()
    symbol = f"REPOTEST{int(datetime.now(timezone.utc).timestamp() * 1_000_000) + 4}USDC"
    plan_id = f"{symbol}_plan"
    _seed_plan(symbol=symbol, family="sweep_reversal", plan_id=plan_id)

    with SessionLocal() as db:
        intent_repo = OrderIntentRepository(db)
        submission_repo = OrderSubmissionRepository(db)
        intent = OrderIntent(
            intent_id=f"intent_{symbol}",
            plan_id=plan_id,
            symbol=symbol,
            strategy_family="sweep_reversal",
            execution_mode="PAPER",
            approval_state="APPROVED_AUTO",
            submit_decision="SUBMIT",
            decision_reason_code="submit_ready",
            decision_reason_message="ready",
            thesis_fingerprint={"cluster": "x"},
            dedupe_result={"status": "unique"},
            session_guidance={"state": "london"},
            quality_snapshot={"validation_grade": "A"},
            approval_snapshot={
                "approval_state": "APPROVED_AUTO",
                "allowed_execution_mode": "PAPER",
                "deployment_go_no_go": "GO",
                "deployment_code": "go_execution_auto_submit",
                "playbook_go_no_go": "GO",
                "playbook_code": "go_execution_auto_submit",
                "playbook_action": "allow_auto_submit",
                "playbook_message": "GO: execution path is auto-approved.",
            },
            payload={},
        )
        intent_repo.add(intent)
        db.flush()

        fetched_intent = intent_repo.get(intent.intent_id)
        assert fetched_intent is not None
        assert fetched_intent.plan_id == plan_id
        assert intent_repo.latest_for_plan(plan_id).intent_id == intent.intent_id

        submission = OrderSubmission(
            submission_id=f"sub_{symbol}",
            intent_id=intent.intent_id,
            plan_id=plan_id,
            symbol=symbol,
            client_order_id=f"client_{symbol}",
            exchange_order_id="paper_1",
            state=OrderLifecycleState.CREATED.value,
            submit_status="CREATED",
            message="created",
            adapter="paper",
            execution_mode="PAPER",
            side="BUY",
            order_type="MARKET",
            reduce_only=False,
            requested_live=False,
            attachments={},
            raw={},
        )
        submission_repo.add(submission)
        submission_repo.transition(
            submission,
            state=OrderLifecycleState.ACKNOWLEDGED.value,
            submit_status="ACKNOWLEDGED",
            message="acknowledged",
        )
        db.commit()

        fetched_submission = submission_repo.get(submission.submission_id)
        assert fetched_submission is not None
        assert fetched_submission.state == "ACKNOWLEDGED"
        assert submission_repo.get_by_client_order_id(submission.client_order_id).submission_id == submission.submission_id


def test_control_plane_close_only_and_safety_state_routes(monkeypatch) -> None:
    init_db()
    _apply_auto_trading_defaults(monkeypatch)

    enable = client.post(
        "/execution/control/close-only",
        json={"active": True, "reason_message": "manual close only"},
    )
    assert enable.status_code == 200
    enable_payload = enable.json()
    assert enable_payload["close_only_active"] is True
    assert enable_payload["new_entry_allowed"] is False

    state = client.get("/execution/safety-state")
    assert state.status_code == 200
    state_payload = state.json()
    assert state_payload["close_only_active"] is True
    assert state_payload["blocking_reason_code"] == "close_only_active"

    disable = client.post(
        "/execution/control/close-only",
        json={"active": False, "reason_message": "manual close only"},
    )
    assert disable.status_code == 200
    disable_payload = disable.json()
    assert disable_payload["close_only_active"] is False

    kill = client.post(
        "/execution/control/kill-switch",
        json={"active": True, "reason_message": "manual kill"},
    )
    assert kill.status_code == 200
    kill_payload = kill.json()
    assert kill_payload["kill_switch_active"] is True
    assert kill_payload["blocking_reason_code"] == "kill_switch_active"

    kill_disable = client.post(
        "/execution/control/kill-switch",
        json={"active": False, "reason_message": "manual kill"},
    )
    assert kill_disable.status_code == 200
    assert kill_disable.json()["kill_switch_active"] is False


def test_control_plane_kill_condition_apply_route_returns_engine_payload(monkeypatch) -> None:
    init_db()
    _apply_auto_trading_defaults(monkeypatch)

    def _fake_apply(self, **kwargs):
        assert kwargs["symbol"] == "BTCUSDC"
        assert kwargs["universe"] == "usdc_perp_top30"
        assert kwargs["days"] == 7
        assert kwargs["dry_run"] is True
        assert kwargs["allow_live_write"] is False
        return {
            "generated_at": datetime.now(timezone.utc),
            "symbol": "BTCUSDC",
            "universe": "usdc_perp_top30",
            "dry_run": True,
            "allow_live_write": False,
            "arm_valid": False,
            "explicit_arm_required": True,
            "eligible_for_live_write": False,
            "kill_condition_state": "close_only_review",
            "automation_bias": "propose_close_only",
            "trigger_axis": "reconciliation_axis",
            "effective_write_scope": "proposal_only",
            "action_target": "close_only",
            "action_reason_code": "auto_kill_condition_close_only",
            "action_reason_message": "Current evidence is weak enough that close-only review should happen before new entries continue.",
            "action_applied": False,
            "kill_condition_automation_summary": {
                "available": True,
                "kill_condition_state": "close_only_review",
                "automation_bias": "propose_close_only",
                "trigger_axis": "reconciliation_axis",
                "write_scope": "proposal_only",
                "summary": "Current evidence is weak enough that close-only review should happen before new entries continue.",
                "reason_codes": ["kill_condition:close_only_review"],
            },
            "safety_state_before": {"new_entry_allowed": True},
            "safety_state_after": {"new_entry_allowed": True},
        }

    monkeypatch.setattr(StrategyEngine, "apply_kill_condition_automation", _fake_apply)

    response = client.post(
        "/execution/control/kill-condition/apply",
        json={
            "symbol": "BTCUSDC",
            "universe": "usdc_perp_top30",
            "days": 7,
            "dry_run": True,
            "allow_live_write": False,
            "updated_by": "test_operator",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["kill_condition_state"] == "close_only_review"
    assert payload["automation_bias"] == "propose_close_only"
    assert payload["trigger_axis"] == "reconciliation_axis"
    assert payload["effective_write_scope"] == "proposal_only"
    assert payload["action_target"] == "close_only"
    assert payload["action_applied"] is False


def test_safety_lock_service_supports_family_symbol_release_and_unlock_at() -> None:
    init_db()
    now = datetime.now(timezone.utc)
    suffix = str(int(now.timestamp() * 1_000_000))[-6:]
    symbol = f"LK{suffix}USDC"
    with SessionLocal() as db:
        service = SafetyLockService(repo=SafetyLockRepository(db), settings=get_settings())
        family_lock = service.set_lock(
            scope_type="FAMILY",
            scope_key="trend_continuation",
            reason_code="family_lock_test",
            reason_message="family blocked",
        )
        service.set_lock(
            scope_type="SYMBOL",
            scope_key=symbol,
            severity="CRITICAL",
            reason_code="symbol_lock_test",
            reason_message="symbol blocked",
        )
        service.set_lock(
            scope_type="SESSION",
            scope_key="london",
            reason_code="expired_lock_test",
            reason_message="expired",
            unlock_at=now - timedelta(minutes=1),
        )
        state = service.safety_state(
            symbol=symbol,
            family="trend_continuation",
            session_name="london",
        )
        reason_codes = {item["reason_code"] for item in state["matching_locks"]}
        assert state["new_entry_allowed"] is False
        assert "family_lock_test" in reason_codes
        assert "symbol_lock_test" in reason_codes
        assert "expired_lock_test" not in reason_codes

        service.release_lock(lock_id=family_lock.lock_id)
        released_state = service.safety_state(
            symbol=symbol,
            family="trend_continuation",
            session_name="london",
        )
        released_codes = {item["reason_code"] for item in released_state["matching_locks"]}
        assert "family_lock_test" not in released_codes
        assert "symbol_lock_test" in released_codes


def test_micro_live_submit_path_uses_binance_adapter_when_gates_pass(monkeypatch) -> None:
    init_db()
    _apply_auto_trading_defaults(monkeypatch)
    settings = get_settings()
    monkeypatch.setattr(settings, "binance_trade_live_enabled", True)
    suffix = str(int(datetime.now(timezone.utc).timestamp() * 1_000_000))[-6:]
    symbol = f"LH{suffix}USDC"
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_symbols", symbol)
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_families", "trend_continuation")
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine.metrics", _good_metrics)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._gate_context_for_symbol", _open_gate_context)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._today_trade_count", lambda self: 0)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._current_exposure_rows", lambda self: [])

    def _fake_submit(self, **kwargs):
        return {
            "symbol": kwargs["symbol"],
            "plan_id": kwargs["plan_id"],
            "order_id": 987654,
            "client_order_id": kwargs["client_order_id"],
            "status": "NEW",
            "side": kwargs["side"],
            "order_type": kwargs["order_type"],
            "reduce_only": kwargs["reduce_only"],
        }

    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine.submit_binance_order", _fake_submit)

    plan_id = f"{symbol}_ml_{suffix}"
    _seed_plan(symbol=symbol, family="trend_continuation", plan_id=plan_id)

    intent = client.post(
        "/execution/order-intents",
        json={"plan_id": plan_id, "execution_mode": "MICRO_LIVE"},
    )
    assert intent.status_code == 200
    intent_payload = intent.json()
    assert intent_payload["submit_decision"] == "SUBMIT"

    submit = client.post(
        "/execution/submit",
        json={"intent_id": intent_payload["intent_id"], "live": True},
    )
    assert submit.status_code == 200
    submit_payload = submit.json()
    assert submit_payload["adapter"] == "binance"
    assert submit_payload["requested_live"] is True
    assert submit_payload["state"] == "ACKNOWLEDGED"


def test_rollout_policy_db_override_blocks_micro_live_intent(monkeypatch) -> None:
    init_db()
    _apply_auto_trading_defaults(monkeypatch)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine.metrics", _good_metrics)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._gate_context_for_symbol", _open_gate_context)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._today_trade_count", lambda self: 0)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._current_exposure_rows", lambda self: [])
    suffix = str(int(datetime.now(timezone.utc).timestamp() * 1_000_000))[-6:]
    symbol = f"RO{suffix}USDC"
    plan_id = f"{symbol}_ro_{suffix}"
    _seed_plan(symbol=symbol, family="trend_continuation", plan_id=plan_id)

    rollout = client.post(
        "/execution/control/rollout-policy",
        json={
            "family": "trend_continuation",
            "live_enabled": False,
            "max_execution_mode": "PAPER",
            "max_risk_r": 0.5,
            "allowed_sessions": ["london"],
            "min_quality_score": 70.0,
            "updated_by": "test",
        },
    )
    assert rollout.status_code == 200
    assert rollout.json()["max_execution_mode"] == "PAPER"

    intent = client.post(
        "/execution/order-intents",
        json={"plan_id": plan_id, "execution_mode": "MICRO_LIVE"},
    )
    assert intent.status_code == 200
    intent_payload = intent.json()
    assert intent_payload["submit_decision"] == "SKIP_BLOCKED"
    assert intent_payload["approval"]["playbook_code"] == "rollout_mode_cap_exceeded"


def test_reconcile_apply_lock_sets_symbol_lock_for_missing_stop(monkeypatch) -> None:
    init_db()
    _apply_auto_trading_defaults(monkeypatch)
    symbol = f"LOCKSYM{int(datetime.now(timezone.utc).timestamp() * 1_000_000) + 5}USDC"
    plan_id = f"{symbol}_entered"
    _seed_plan(symbol=symbol, family="trend_continuation", plan_id=plan_id, state="ENTERED")

    fresh_ts = datetime.now(timezone.utc)
    with SessionLocal() as db:
        db.add(
            BinancePositionSnapshot(
                position_key=f"{symbol}_both",
                symbol=symbol,
                position_side="BOTH",
                position_amt=1.0,
                entry_price=100.0,
                break_even_price=100.0,
                mark_price=101.0,
                liquidation_price=80.0,
                unrealized_pnl=1.0,
                notional=101.0,
                leverage=2,
                margin_type="cross",
                isolated_wallet=0.0,
                update_ts=fresh_ts,
                raw={},
            )
        )
        db.add(
            BinanceOrderLedger(
                client_order_id=f"{symbol}_entry",
                exchange_order_id=654321,
                plan_id=plan_id,
                symbol=symbol,
                side="BUY",
                order_type="MARKET",
                status="NEW",
                reduce_only=False,
                requested_live=True,
                live_enabled=True,
                test_order=False,
                price=100.0,
                orig_qty=1.0,
                executed_qty=0.0,
                time_in_force="GTC",
                last_event_type="ORDER_TRADE_UPDATE",
                last_trade_id=None,
                last_event_ts=fresh_ts,
                raw={},
            )
        )
        db.commit()

    reconcile = client.post("/execution/reconcile?apply_lock=true", json={"symbol": symbol})
    assert reconcile.status_code == 200
    assert reconcile.json()["lock_required"] is True

    state = client.get(f"/execution/safety-state?symbol={symbol}&family=trend_continuation&session_name=london")
    assert state.status_code == 200
    reason_codes = {item["reason_code"] for item in state.json()["matching_locks"]}
    assert "reconciliation_missing_stop_order" in reason_codes


def test_reconcile_user_stream_stale_applies_global_lock(monkeypatch) -> None:
    init_db()
    _apply_auto_trading_defaults(monkeypatch)
    symbol = f"LOCKGLB{int(datetime.now(timezone.utc).timestamp() * 1_000_000) + 6}USDC"
    stale_ts = datetime.now(timezone.utc) - timedelta(minutes=10)
    with SessionLocal() as db:
        db.add(
            BinanceOrderLedger(
                client_order_id=f"{symbol}_stale",
                exchange_order_id=777777,
                plan_id=None,
                symbol=symbol,
                side="BUY",
                order_type="MARKET",
                status="NEW",
                reduce_only=False,
                requested_live=True,
                live_enabled=True,
                test_order=False,
                price=100.0,
                orig_qty=1.0,
                executed_qty=0.0,
                time_in_force="GTC",
                last_event_type="ORDER_TRADE_UPDATE",
                last_trade_id=None,
                last_event_ts=stale_ts,
                raw={},
            )
        )
        db.commit()

    reconcile = client.post("/execution/reconcile?apply_lock=true", json={"symbol": symbol})
    assert reconcile.status_code == 200
    assert reconcile.json()["lock_required"] is True

    state = client.get("/execution/safety-state")
    assert state.status_code == 200
    reason_codes = {item["reason_code"] for item in state.json()["matching_locks"]}
    assert "reconciliation_user_stream_stale" in reason_codes

    with SessionLocal() as db:
        SafetyLockService(repo=SafetyLockRepository(db), settings=get_settings()).release_reason(
            scope_type="GLOBAL",
            reason_code="reconciliation_user_stream_stale",
        )
        db.commit()
