from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from app.core.enums import ApprovalState, ExecutionMode, OrderLifecycleState, SubmitDecision
from app.db.models import ExecutionFill, OrderIntent, OrderSubmission, Plan
from app.db.session import SessionLocal, init_db
from app.domain.execution import RolloutPolicy
from app.services.order_intents import OrderIntentService
from app.services.runtime_worker_heartbeat import write_worker_heartbeat
from app.services.strategy_engine import StrategyEngine
from scripts import run_session_impulse_retest_runtime_audit_report


def _micro_plan(*, symbol: str, plan_id: str) -> Plan:
    now = datetime.now(timezone.utc)
    return Plan(
        plan_id=plan_id,
        zone_id=f"micro:{symbol}:{plan_id}"[:50],
        symbol=symbol,
        timeframe="5m",
        direction="long",
        entry_model="CONFIRM",
        entry_price=100.0,
        entry_condition="session_impulse_retest_confirm",
        sl=99.0,
        tp1=101.0,
        tp2=102.0,
        tp3=102.0,
        split={"tp1": 0.35, "tp2": 0.65, "runner": 0.0},
        rr_min=1.0,
        rr_base=2.0,
        rr_opt=2.0,
        ev=0.4,
        cost_est=0.06,
        confidence=0.84,
        validity={
            "regime": "trend",
            "strategy_family": "session_impulse_retest",
            "strategy_grade": "A",
            "strategy_family_score": 85.0,
            "strategy_mode": "A_ONLY",
            "recommended_risk_r": 0.55,
            "expected_win_prob": 0.62,
            "expected_ev_r": 0.40,
            "expected_summary": "session_impulse_retest benchmark",
            "reaction_classification": "acceptance_confirmed",
            "transition_state": "none",
            "thesis_fingerprint": {
                "symbol": symbol,
                "direction": "long",
                "family": "session_impulse_retest",
            },
            "thesis_cluster_id": f"cluster:{symbol}:session_impulse_retest:long",
            "thesis_primary_symbol": symbol,
        },
        state="ARMED",
        valid_from=now - timedelta(minutes=2),
        valid_until=now + timedelta(minutes=12),
        strategy_version="v2",
    )


def _sweep_plan(*, symbol: str, plan_id: str) -> Plan:
    plan = _micro_plan(symbol=symbol, plan_id=plan_id)
    validity = dict(plan.validity or {})
    validity.update(
        {
            "strategy_family": "sweep_reversal",
            "strategy_grade": "A",
            "strategy_family_score": 86.0,
            "recommended_risk_r": 0.4,
            "expected_summary": "sweep_reversal benchmark",
            "thesis_fingerprint": {
                "symbol": symbol,
                "direction": "long",
                "family": "sweep_reversal",
            },
            "thesis_cluster_id": f"cluster:{symbol}:sweep_reversal:long",
        }
    )
    plan.entry_model = "LIMIT"
    plan.entry_condition = "sweep_reversal_limit"
    plan.validity = validity
    return plan


def _exposure_plan(
    *,
    symbol: str,
    plan_id: str,
    strategy_family: str,
    recommended_risk_r: float,
    thesis_cluster_id: str,
) -> Plan:
    plan = _micro_plan(symbol=symbol, plan_id=plan_id)
    validity = dict(plan.validity or {})
    validity["strategy_family"] = strategy_family
    validity["recommended_risk_r"] = recommended_risk_r
    validity["thesis_cluster_id"] = thesis_cluster_id
    plan.validity = validity
    plan.state = "ARMED"
    return plan


def _candidate_for(plan: Plan) -> dict:
    return {
        "plan_id": plan.plan_id,
        "accepted": True,
        "deployment_go_no_go": "GO",
        "deployment_code": "go_runtime_candidate_ready",
        "deployment_message": "GO: runtime candidate is tradable.",
        "session_guidance": {
            "session_name": "london",
            "state": "normal",
            "risk_label": "normal",
        },
        "risk_reason": "normal",
        "operating_lock": {},
        "expected_win_prob": 0.62,
        "expected_ev_r": 0.40,
        "expected_summary": "session_impulse_retest benchmark",
    }


def _metrics() -> dict:
    return {
        "grade": "A",
        "recommendation": "deploy",
        "risk_state": "OPEN",
        "risk_reason": "normal",
        "operating_lock": {},
    }


def _write_bridge_pass_reports(root: Path) -> None:
    generated_at = datetime.now(timezone.utc).isoformat()
    backtest_dir = root / "backtests"
    portfolio_dir = root / "risk_sweeps"
    backtest_dir.mkdir(parents=True, exist_ok=True)
    portfolio_dir.mkdir(parents=True, exist_ok=True)
    (backtest_dir / "micro_main_usdt_proxy_backtest_20260510T114636Z.json").write_text(
        json.dumps(
            {
                "generated_at": generated_at,
                "days": 1095,
                "results": {
                    "BTCUSDT": {
                        "proxy_symbol": "BTCUSDT",
                        "canonical_symbol": "BTCUSDC",
                        "summary": {
                            "closed": 141,
                            "ev_r": 0.5307,
                            "total_r": 74.8267,
                            "win_rate": 0.6454,
                            "decision": "PASS",
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    (portfolio_dir / "micro_main_usdt_proxy_yearly_portfolio_replay_20260510T113926Z.json").write_text(
        json.dumps(
            {
                "generated_at": generated_at,
                "symbols": {"BTCUSDC": {"year_1": {}, "year_2": {}, "year_3": {}}},
                "horizons": {
                    "year_1": {"1.0%": {"accepted_trades": 1437, "return_pct": 743.83, "max_drawdown_pct": 6.90}},
                    "year_2": {"1.0%": {"accepted_trades": 1597, "return_pct": 941.94, "max_drawdown_pct": 10.93}},
                    "year_3": {"1.0%": {"accepted_trades": 1363, "return_pct": 740.05, "max_drawdown_pct": 6.16}},
                },
            }
        ),
        encoding="utf-8",
    )


def _patch_runtime(engine: StrategyEngine, *, candidate_row: dict) -> None:
    engine._execution_candidate_rows = lambda symbol: (None, [candidate_row], {})  # type: ignore[assignment]
    engine.metrics = lambda symbol, version: _metrics()  # type: ignore[assignment]
    engine._current_exposure_rows = lambda: []  # type: ignore[assignment]
    engine._today_trade_count = lambda: 0  # type: ignore[assignment]
    engine._approval_outcome_inputs = lambda symbol, candidate_rows: {}  # type: ignore[assignment]
    engine._live_cluster_guard = lambda **kwargs: {}  # type: ignore[assignment]
    engine.safety_locks.safety_state = lambda **kwargs: {"new_entry_allowed": True}  # type: ignore[assignment]


def _patch_live_contract(engine: StrategyEngine, *, allowed_symbols: list[str]) -> None:
    symbols_csv = ",".join(allowed_symbols)
    engine.settings.auto_trading_enabled = True
    engine.settings.auto_trading_execution_mode = ExecutionMode.MICRO_LIVE.value
    engine.settings.auto_trading_allowed_symbols = symbols_csv
    engine.settings.auto_trading_allowed_families = "sweep_reversal,session_impulse_retest"
    engine.settings.auto_trading_micro_live_allowed_symbols = symbols_csv
    engine.settings.auto_trading_micro_live_allowed_families = "sweep_reversal,session_impulse_retest"
    engine.settings.auto_trading_micro_live_allowed_sessions = "london,new_york"
    engine.settings.auto_trading_micro_live_allowed_entry_models = "LIMIT,CONFIRM"
    engine.settings.auto_trading_micro_live_max_concurrent_positions = 10
    engine.settings.auto_trading_micro_live_max_daily_new_entries = 10
    engine.settings.auto_trading_close_only = False
    engine.settings.binance_trade_live_enabled = True
    engine.settings.auto_trading_notional_per_r = 25.0
    engine.settings.binance_live_min_quantity = 0.001
    engine.settings.binance_live_quantity_step = 0.001
    engine.settings.auto_trading_live_liquidity_gate_enabled = False
    engine.settings.session_impulse_retest_shadow_only = False
    engine.settings.session_impulse_retest_partial_activation_ratio = 1.0
    engine.execution_coordinator.live_symbol_rules_loader = lambda symbol: {
        "symbol": str(symbol).upper(),
        "quantity_step": 0.001,
        "min_quantity": 0.001,
        "source": "test_override",
    }
    engine.execution_planning.rollout.get = lambda family: RolloutPolicy(  # type: ignore[assignment]
        strategy_family=str(family or "legacy_zone_plan").lower(),
        live_enabled=True,
        max_execution_mode=ExecutionMode.MICRO_LIVE,
        max_risk_r=0.6,
        allowed_sessions=("london", "new_york"),
        min_quality_score=78.0,
    )
    engine._session_impulse_retest_rollout_readiness = lambda **kwargs: {  # type: ignore[assignment]
        "ready_for_partial": True,
        "blockers": [],
    }


def test_live_cluster_guard_ignores_missing_opened_ts_for_recent_window() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        engine.settings.auto_trading_live_family_cluster_window_minutes = 180
        engine.settings.auto_trading_live_max_same_family_entries_per_window = 1
        engine.settings.auto_trading_live_max_same_family_direction_exposures = 10
        plan = _micro_plan(symbol="BTCUSDC", plan_id="sir_BTCUSDC_cluster_missing_ts")
        exposure = _micro_plan(symbol="ETHUSDC", plan_id="sir_ETHUSDC_cluster_missing_ts")
        exposure.state = "ENTERED"
        exposure.valid_from = None
        validity = dict(exposure.validity or {})
        validity.pop("entry_ts", None)
        validity["strategy_family"] = "session_impulse_retest"
        validity["direction"] = "long"
        exposure.validity = validity

        guard = engine._live_cluster_guard(
            plan=plan,
            executable_plan={"strategy_family": "session_impulse_retest", "direction": "long"},
            requested_mode=ExecutionMode.MICRO_LIVE,
            exposure_rows=[exposure],
        )

        assert guard is not None
        assert guard["recent_family_window_entry_count"] == 0
        assert guard["recent_family_direction_exposure_count"] == 1
        assert guard["recent_family_direction_exposures"][0]["opened_ts"] == ""


def test_live_cluster_guard_ignores_malformed_loss_exit_ts() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        engine.settings.auto_trading_live_family_cluster_window_minutes = 180
        engine.settings.auto_trading_live_max_same_family_entries_per_window = 1
        engine.settings.auto_trading_live_recent_loss_cooldown_minutes = 180
        engine.settings.auto_trading_live_recent_loss_trigger_count = 1
        plan = _micro_plan(symbol="BTCUSDC", plan_id="sir_BTCUSDC_loss_bad_ts")
        closed = _micro_plan(symbol="ETHUSDC", plan_id="sir_ETHUSDC_loss_bad_ts")
        validity = dict(closed.validity or {})
        validity["strategy_family"] = "session_impulse_retest"
        validity["final_exit_ts"] = "not-a-timestamp"
        validity["final_exit_realized_r"] = -1.0
        closed.validity = validity
        engine.plan_repo.list_recent_global = lambda **kwargs: [closed]  # type: ignore[assignment]

        guard = engine._live_cluster_guard(
            plan=plan,
            executable_plan={"strategy_family": "session_impulse_retest", "direction": "long"},
            requested_mode=ExecutionMode.MICRO_LIVE,
            exposure_rows=[],
        )

        assert guard is not None
        assert guard["recent_family_loss_count"] == 0


def test_live_cluster_guard_tolerates_malformed_window_settings() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        engine.settings.auto_trading_live_family_cluster_window_minutes = "bad-window"
        engine.settings.auto_trading_live_max_same_family_entries_per_window = "bad-entry-cap"
        engine.settings.auto_trading_live_max_same_family_direction_exposures = "bad-direction-cap"
        engine.settings.auto_trading_live_recent_loss_cooldown_minutes = "bad-loss-window"
        engine.settings.auto_trading_live_recent_loss_trigger_count = "bad-loss-count"
        plan = _micro_plan(symbol="BTCUSDC", plan_id="sir_BTCUSDC_bad_cluster_settings")

        guard = engine._live_cluster_guard(
            plan=plan,
            executable_plan={"strategy_family": "session_impulse_retest", "direction": "long"},
            requested_mode=ExecutionMode.MICRO_LIVE,
            exposure_rows=[],
        )

        assert guard is not None
        assert guard["cluster_window_minutes"] == 0
        assert guard["max_same_family_entries_per_window"] == 0
        assert guard["loss_cooldown_minutes"] == 0


def test_plan_allows_live_tranche_continuation_tolerates_malformed_tranche_counts() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        engine.settings.auto_trading_live_liquidity_gate_partial_submit_enabled = True
        engine.settings.auto_trading_live_liquidity_gate_min_tranche_notional_usdt = 10.0
        engine.settings.auto_trading_live_liquidity_gate_max_tranches = 3
        plan = _micro_plan(symbol="BTCUSDC", plan_id="sir_BTCUSDC_malformed_tranche_counts")
        engine.intent_repo.latest_for_plan = lambda plan_id: SimpleNamespace(intent_id="intent_bad_tranche")  # type: ignore[assignment]
        engine.submission_repo.latest_for_intent = lambda intent_id: SimpleNamespace(  # type: ignore[assignment]
            adapter="binance",
            requested_live=True,
            state=OrderLifecycleState.FILLED.value,
            attachments={
                "live_tranche": {
                    "additive_allowed": True,
                    "remaining_notional": "25.0",
                    "tranche_index": "bad-index",
                    "max_tranches": "bad-max",
                }
            },
            raw={},
        )

        assert engine._plan_allows_live_tranche_continuation(plan) is True


def test_session_impulse_retest_btc_micro_live_can_approve_and_submit(monkeypatch) -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        _patch_live_contract(engine, allowed_symbols=["BTCUSDC", "ETHUSDC", "SOLUSDC"])
        plan = _micro_plan(symbol="BTCUSDC", plan_id="sir_BTCUSDC_L_test")
        db.add(plan)
        db.commit()

        _patch_runtime(engine, candidate_row=_candidate_for(plan))

        engine.execution_coordinator.live_submitter = lambda **kwargs: {  # type: ignore[assignment]
            "status": "NEW",
            "order_id": "live_btc_001",
            "client_order_id": kwargs["client_order_id"],
            "side": kwargs["side"],
            "order_type": kwargs["order_type"],
            "reduce_only": kwargs["reduce_only"],
        }

        approval = engine.approve_execution_plan(plan_id=plan.plan_id)
        assert approval["approval_state"] == ApprovalState.APPROVED_AUTO.value
        assert approval["allowed_execution_mode"] == ExecutionMode.MICRO_LIVE.value

        intent = engine.create_order_intent(plan_id=plan.plan_id, execution_mode=ExecutionMode.MICRO_LIVE)
        assert intent["approval_state"] == ApprovalState.APPROVED_AUTO.value
        assert intent["submit_decision"] == SubmitDecision.SUBMIT.value
        assert intent["decision_reason_code"] == "submit_ready"

        submission = engine.submit_order_intent(intent_id=intent["intent_id"], live=True)
        assert submission["adapter"] == "binance"
        assert submission["requested_live"] is True
        assert submission["submit_status"] == "NEW"
        assert submission["state"] == "ACKNOWLEDGED"


def test_create_order_intent_reuses_recent_same_plan_intent() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        _patch_live_contract(engine, allowed_symbols=["BTCUSDC"])
        plan = _micro_plan(symbol="BTCUSDC", plan_id="sir_BTCUSDC_reuse_recent_intent")
        db.add(plan)
        db.commit()

        _patch_runtime(engine, candidate_row=_candidate_for(plan))

        first = engine.create_order_intent(plan_id=plan.plan_id, execution_mode=ExecutionMode.MICRO_LIVE)
        second = engine.create_order_intent(plan_id=plan.plan_id, execution_mode=ExecutionMode.MICRO_LIVE)

        assert second["intent_id"] == first["intent_id"]
        assert [row.intent_id for row in engine.intent_repo.list_for_plan(plan.plan_id)] == [first["intent_id"]]


def test_create_order_intent_does_not_reuse_recent_different_requested_mode() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        _patch_live_contract(engine, allowed_symbols=["BTCUSDC"])
        plan = _micro_plan(symbol="BTCUSDC", plan_id="sir_BTCUSDC_reuse_mode_guard")
        db.add(plan)
        db.commit()

        _patch_runtime(engine, candidate_row=_candidate_for(plan))

        paper_intent = engine.create_order_intent(plan_id=plan.plan_id, execution_mode=ExecutionMode.PAPER)
        micro_live_intent = engine.create_order_intent(plan_id=plan.plan_id, execution_mode=ExecutionMode.MICRO_LIVE)

        assert micro_live_intent["intent_id"] != paper_intent["intent_id"]
        assert len(engine.intent_repo.list_for_plan(plan.plan_id)) == 2
        assert paper_intent["requested_execution_mode"] == ExecutionMode.PAPER.value
        assert micro_live_intent["requested_execution_mode"] == ExecutionMode.MICRO_LIVE.value


def test_create_order_intent_does_not_reuse_recent_different_override_request() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        _patch_live_contract(engine, allowed_symbols=["BTCUSDC"])
        plan = _micro_plan(symbol="BTCUSDC", plan_id="sir_BTCUSDC_reuse_override_guard")
        db.add(plan)
        db.commit()

        _patch_runtime(engine, candidate_row=_candidate_for(plan))

        normal_intent = engine.create_order_intent(plan_id=plan.plan_id, execution_mode=ExecutionMode.PAPER)
        override_intent = engine.create_order_intent(
            plan_id=plan.plan_id,
            execution_mode=ExecutionMode.PAPER,
            paper_lineage_override=True,
        )

        assert override_intent["intent_id"] != normal_intent["intent_id"]
        assert len(engine.intent_repo.list_for_plan(plan.plan_id)) == 2
        assert normal_intent["paper_lineage_override_requested"] is False
        assert override_intent["paper_lineage_override_requested"] is True


def test_create_order_intent_does_not_reuse_legacy_override_applied_intent_for_normal_request() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        _patch_live_contract(engine, allowed_symbols=["BTCUSDC"])
        plan = _micro_plan(symbol="BTCUSDC", plan_id="sir_BTCUSDC_reuse_legacy_override_guard")
        db.add(plan)
        db.commit()

        _patch_runtime(engine, candidate_row=_candidate_for(plan))

        override_intent = engine.create_order_intent(
            plan_id=plan.plan_id,
            execution_mode=ExecutionMode.PAPER,
            paper_lineage_override=True,
        )
        row = engine.intent_repo.get(override_intent["intent_id"])
        payload = dict(row.payload or {})
        payload.pop("paper_lineage_override_requested", None)
        payload["intent_snapshot"] = {
            **dict(payload.get("intent_snapshot") or {}),
            "paper_lineage_override_applied": True,
        }
        row.payload = payload
        db.add(row)
        db.commit()

        normal_intent = engine.create_order_intent(plan_id=plan.plan_id, execution_mode=ExecutionMode.PAPER)

        assert normal_intent["intent_id"] != override_intent["intent_id"]
        assert len(engine.intent_repo.list_for_plan(plan.plan_id)) == 2


def test_create_order_intent_does_not_reuse_recent_intent_after_plan_expires() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        _patch_live_contract(engine, allowed_symbols=["BTCUSDC"])
        plan = _micro_plan(symbol="BTCUSDC", plan_id="sir_BTCUSDC_reuse_stale_guard")
        db.add(plan)
        db.commit()

        _patch_runtime(engine, candidate_row=_candidate_for(plan))

        first = engine.create_order_intent(plan_id=plan.plan_id, execution_mode=ExecutionMode.MICRO_LIVE)
        plan.valid_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        plan.state = "PLANNED"
        db.add(plan)
        db.commit()

        second = engine.create_order_intent(plan_id=plan.plan_id, execution_mode=ExecutionMode.MICRO_LIVE)

        assert second["intent_id"] != first["intent_id"]
        assert second["submit_decision"] == SubmitDecision.SKIP_STALE_PLAN.value
        assert second["decision_reason_code"] == "stale_plan"


def test_order_intent_stale_check_treats_missing_valid_until_as_stale() -> None:
    plan = SimpleNamespace(state="ARMED", valid_until=None)

    assert OrderIntentService._is_stale(plan) is True


def test_create_order_intent_tolerates_malformed_recheck_cooldown_setting() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        _patch_live_contract(engine, allowed_symbols=["BTCUSDC"])
        engine.settings.auto_trading_intent_recheck_cooldown_seconds = "bad-cooldown"
        plan = _micro_plan(symbol="BTCUSDC", plan_id="sir_BTCUSDC_bad_recheck_cooldown")
        db.add(plan)
        db.commit()

        _patch_runtime(engine, candidate_row=_candidate_for(plan))

        first = engine.create_order_intent(plan_id=plan.plan_id, execution_mode=ExecutionMode.MICRO_LIVE)
        second = engine.create_order_intent(plan_id=plan.plan_id, execution_mode=ExecutionMode.MICRO_LIVE)

        assert first["intent_id"] != second["intent_id"]
        assert len(engine.intent_repo.list_for_plan(plan.plan_id)) == 2


def test_create_order_intent_tolerates_empty_blocked_approval_reasons() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        _patch_live_contract(engine, allowed_symbols=["BTCUSDC"])
        plan = _micro_plan(symbol="BTCUSDC", plan_id="sir_BTCUSDC_empty_approval_reasons")
        db.add(plan)
        db.commit()

        engine.order_intents.approval_loader = lambda *args, **kwargs: {  # type: ignore[assignment]
            "approval": {
                "approval_state": ApprovalState.BLOCKED.value,
                "allowed_execution_mode": ExecutionMode.MICRO_LIVE.value,
                "approval_reasons": [],
                "playbook_code": "",
                "playbook_message": "",
            },
            "executable_plan": {
                "strategy_family": "session_impulse_retest",
                "setup_score": "legacy-bad-score",
                "recommended_risk_r": "legacy-bad-risk",
                "expected_summary": {"expected_ev_r": "legacy-bad-ev"},
                "thesis_fingerprint": {"symbol": "BTCUSDC", "direction": "long"},
            },
        }

        intent = engine.create_order_intent(plan_id=plan.plan_id, execution_mode=ExecutionMode.MICRO_LIVE)

        assert intent["submit_decision"] == SubmitDecision.SKIP_BLOCKED.value
        assert intent["decision_reason_code"] == "approval_blocked"
        assert intent["quality_snapshot"]["setup_score"] == 0.0
        assert intent["quality_snapshot"]["recommended_risk_r"] == 0.0
        assert intent["quality_snapshot"]["expected_ev_r"] == 0.0


def test_create_order_intent_treats_unknown_approval_state_as_blocked() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        _patch_live_contract(engine, allowed_symbols=["BTCUSDC"])
        plan = _micro_plan(symbol="BTCUSDC", plan_id="sir_BTCUSDC_unknown_approval_state")
        db.add(plan)
        db.commit()

        engine.order_intents.approval_loader = lambda *args, **kwargs: {  # type: ignore[assignment]
            "approval": {
                "approval_state": "LEGACY_UNKNOWN",
                "allowed_execution_mode": ExecutionMode.MICRO_LIVE.value,
                "approval_reasons": [{"code": "legacy_unknown_state", "message": "bad legacy state"}],
            },
            "executable_plan": {
                "strategy_family": "session_impulse_retest",
                "thesis_fingerprint": {"symbol": "BTCUSDC", "direction": "long"},
            },
        }

        intent = engine.create_order_intent(plan_id=plan.plan_id, execution_mode=ExecutionMode.MICRO_LIVE)

        assert intent["approval_state"] == ApprovalState.BLOCKED.value
        assert intent["submit_decision"] == SubmitDecision.SKIP_BLOCKED.value
        assert intent["decision_reason_code"] == "legacy_unknown_state"


def test_submit_order_intent_rejects_unknown_legacy_submit_decision() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        _patch_live_contract(engine, allowed_symbols=["BTCUSDC"])
        plan = _micro_plan(symbol="BTCUSDC", plan_id="sir_BTCUSDC_unknown_submit_decision")
        db.add(plan)
        db.add(
            OrderIntent(
                intent_id="intent_unknown_submit_decision",
                plan_id=plan.plan_id,
                symbol=plan.symbol,
                strategy_family="session_impulse_retest",
                execution_mode=ExecutionMode.MICRO_LIVE.value,
                approval_state=ApprovalState.APPROVED_AUTO.value,
                submit_decision="LEGACY_UNKNOWN",
                decision_reason_code="legacy_unknown_submit_decision",
                decision_reason_message="legacy bad decision",
                thesis_fingerprint={},
                dedupe_result={},
                session_guidance={},
                quality_snapshot={},
                approval_snapshot={
                    "approval_state": ApprovalState.APPROVED_AUTO.value,
                    "allowed_execution_mode": ExecutionMode.MICRO_LIVE.value,
                },
                payload={},
            )
        )
        db.commit()

        _patch_runtime(engine, candidate_row=_candidate_for(plan))

        submission = engine.submit_order_intent(intent_id="intent_unknown_submit_decision", live=True)

        assert submission["adapter"] == "none"
        assert submission["state"] == "REJECTED"
        assert submission["submit_status"] == "INTENT_NOT_SUBMITTABLE"


def test_session_impulse_retest_sol_micro_live_can_approve_and_submit() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        _patch_live_contract(engine, allowed_symbols=["BTCUSDC", "ETHUSDC", "SOLUSDC"])
        plan = _micro_plan(symbol="SOLUSDC", plan_id="sir_SOLUSDC_L_test")
        db.add(plan)
        db.commit()

        _patch_runtime(engine, candidate_row=_candidate_for(plan))

        engine.execution_coordinator.live_submitter = lambda **kwargs: {  # type: ignore[assignment]
            "status": "NEW",
            "order_id": "live_sol_001",
            "client_order_id": kwargs["client_order_id"],
            "side": kwargs["side"],
            "order_type": kwargs["order_type"],
            "reduce_only": kwargs["reduce_only"],
        }

        approval = engine.approve_execution_plan(plan_id=plan.plan_id)
        assert approval["approval_state"] == ApprovalState.APPROVED_AUTO.value
        assert approval["allowed_execution_mode"] == ExecutionMode.MICRO_LIVE.value

        intent = engine.create_order_intent(plan_id=plan.plan_id, execution_mode=ExecutionMode.MICRO_LIVE)
        assert intent["submit_decision"] == SubmitDecision.SUBMIT.value

        submission = engine.submit_order_intent(intent_id=intent["intent_id"], live=True)
        assert submission["adapter"] == "binance"
        assert submission["submit_status"] == "NEW"
        assert submission["state"] == "ACKNOWLEDGED"


def test_session_impulse_retest_live_requested_mode_uses_rollout_capped_micro_live_submit() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        _patch_live_contract(engine, allowed_symbols=["BTCUSDC"])
        engine.settings.auto_trading_execution_mode = ExecutionMode.LIVE.value
        plan = _micro_plan(symbol="BTCUSDC", plan_id="sir_BTCUSDC_live_mode_cap_test")
        db.add(plan)
        db.commit()

        _patch_runtime(engine, candidate_row=_candidate_for(plan))

        engine.execution_coordinator.live_submitter = lambda **kwargs: {  # type: ignore[assignment]
            "status": "NEW",
            "order_id": "live_btc_cap_001",
            "client_order_id": kwargs["client_order_id"],
            "side": kwargs["side"],
            "order_type": kwargs["order_type"],
            "reduce_only": kwargs["reduce_only"],
        }

        approval = engine.approve_execution_plan(plan_id=plan.plan_id)
        assert approval["approval_state"] == ApprovalState.APPROVED_AUTO.value
        assert approval["allowed_execution_mode"] == ExecutionMode.MICRO_LIVE.value

        intent = engine.create_order_intent(plan_id=plan.plan_id, execution_mode=ExecutionMode.LIVE)
        assert intent["approval_state"] == ApprovalState.APPROVED_AUTO.value
        assert intent["submit_decision"] == SubmitDecision.SUBMIT.value
        assert intent["execution_mode"] == ExecutionMode.MICRO_LIVE.value

        submission = engine.submit_order_intent(intent_id=intent["intent_id"], live=True)
        assert submission["adapter"] == "binance"
        assert submission["submit_status"] == "NEW"
        assert submission["state"] == "ACKNOWLEDGED"
        assert submission["execution_mode"] == ExecutionMode.MICRO_LIVE.value


def test_session_impulse_retest_link_remains_blocked_until_live_allowlist_expands() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        _patch_live_contract(engine, allowed_symbols=["BTCUSDC", "ETHUSDC", "SOLUSDC"])
        plan = _micro_plan(symbol="LINKUSDC", plan_id="sir_LINKUSDC_L_test")
        db.add(plan)
        db.commit()

        _patch_runtime(engine, candidate_row=_candidate_for(plan))

        approval = engine.approve_execution_plan(plan_id=plan.plan_id)
        assert approval["approval_state"] == ApprovalState.BLOCKED.value
        assert approval["playbook_code"] == "symbol_not_live_enabled"


def test_session_impulse_retest_secondary_symbol_stays_shadow_even_if_allowlisted() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        _patch_live_contract(engine, allowed_symbols=["BTCUSDC", "XLMUSDC"])
        plan = _micro_plan(symbol="XLMUSDC", plan_id="sir_XLMUSDC_L_test")
        db.add(plan)
        db.commit()

        _patch_runtime(engine, candidate_row=_candidate_for(plan))
        engine._session_impulse_retest_rollout_readiness = lambda **kwargs: {  # type: ignore[assignment]
            "ready_for_partial": False,
            "blockers": ["secondary_rollout_disabled"],
        }

        approval = engine.approve_execution_plan(plan_id=plan.plan_id)
        assert approval["approval_state"] == ApprovalState.APPROVED_SHADOW.value
        assert approval["playbook_code"] == "session_impulse_retest_rollout_not_ready"


def test_session_impulse_retest_live_filled_submit_ingests_immediate_entry_fill() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        _patch_live_contract(engine, allowed_symbols=["BTCUSDC", "ETHUSDC", "SOLUSDC"])
        plan = _micro_plan(symbol="BTCUSDC", plan_id="sir_BTCUSDC_fill_test")
        db.add(plan)
        db.commit()

        _patch_runtime(engine, candidate_row=_candidate_for(plan))

        engine.execution_coordinator.live_submitter = lambda **kwargs: {  # type: ignore[assignment]
            "status": "FILLED",
            "order_id": "live_btc_fill_001",
            "client_order_id": kwargs["client_order_id"],
            "side": kwargs["side"],
            "order_type": kwargs["order_type"],
            "reduce_only": kwargs["reduce_only"],
            "executed_qty": kwargs["quantity"],
            "avg_price": 100.25,
            "raw": {
                "orderId": "live_btc_fill_001",
                "executedQty": str(kwargs["quantity"]),
                "avgPrice": "100.25",
            },
        }

        intent = engine.create_order_intent(plan_id=plan.plan_id, execution_mode=ExecutionMode.MICRO_LIVE)
        submission = engine.submit_order_intent(intent_id=intent["intent_id"], live=True)

        assert submission["adapter"] == "binance"
        assert submission["submit_status"] == "FILLED"
        assert submission["state"] == "FILLED"
        assert submission["attachments"]["immediate_fill_ingested"] is True
        assert len(submission["fill_results"]) == 1
        assert submission["fill_results"][0]["accepted"] is True
        assert submission["fill_results"][0]["stage"] == "ENTRY"
        assert submission["fill_results"][0]["to_state"] == "ENTERED"

        db.expire_all()
        refreshed = db.get(Plan, plan.plan_id)
        assert refreshed is not None
        assert refreshed.state == "ENTERED"
        fills = db.query(ExecutionFill).filter(ExecutionFill.plan_id == plan.plan_id).all()
        assert len(fills) == 1
        assert fills[0].stage == "ENTRY"
        assert dict(fills[0].payload or {})["source"] == "binance_submit_response"


def test_session_impulse_retest_live_rejection_preserves_requested_live_flag() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        _patch_live_contract(engine, allowed_symbols=["BTCUSDC"])
        engine.settings.binance_trade_live_enabled = False
        plan = _micro_plan(symbol="BTCUSDC", plan_id="sir_BTCUSDC_live_disabled_test")
        db.add(plan)
        db.commit()

        _patch_runtime(engine, candidate_row=_candidate_for(plan))

        intent = engine.create_order_intent(plan_id=plan.plan_id, execution_mode=ExecutionMode.MICRO_LIVE)
        submission = engine.submit_order_intent(intent_id=intent["intent_id"], live=True)

        assert submission["submit_status"] == "LIVE_DISABLED"
        assert submission["requested_live"] is True
        assert submission["adapter"] == "none"


def test_failed_live_submit_does_not_count_as_live_exposure_or_trade_count() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        _patch_live_contract(engine, allowed_symbols=["BTCUSDC"])
        engine.settings.binance_trade_live_enabled = False
        plan = _micro_plan(symbol="BTCUSDC", plan_id="sir_BTCUSDC_live_reject_count_test")
        db.add(plan)
        db.commit()

        _patch_runtime(engine, candidate_row=_candidate_for(plan))

        intent = engine.create_order_intent(plan_id=plan.plan_id, execution_mode=ExecutionMode.MICRO_LIVE)
        submission = engine.submit_order_intent(intent_id=intent["intent_id"], live=True)

        assert submission["submit_status"] == "LIVE_DISABLED"
        assert submission["requested_live"] is True
        assert engine._current_exposure_rows() == []
        assert engine._today_trade_count() == 0


def test_today_trade_count_ignores_live_submission_without_submitted_at() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        engine.settings.auto_trading_execution_mode = ExecutionMode.MICRO_LIVE
        engine.submission_repo.list_recent = lambda days=2, limit=5000: [  # type: ignore[assignment]
            SimpleNamespace(
                plan_id="sir_BTCUSDC_missing_submitted_at",
                submitted_at=None,
                adapter="binance",
                state="SUBMITTED",
                execution_mode=ExecutionMode.MICRO_LIVE.value,
                requested_live=True,
            )
        ]
        engine.plan_repo.list_recent_global = lambda **kwargs: []  # type: ignore[assignment]

        assert engine._today_trade_count() == 0


def test_live_submitter_exception_records_unknown_live_state_and_blocks_reentry() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        _patch_live_contract(engine, allowed_symbols=["BTCUSDC"])
        plan = _micro_plan(symbol="BTCUSDC", plan_id="sir_BTCUSDC_live_submit_error")
        db.add(plan)
        db.commit()

        _patch_runtime(engine, candidate_row=_candidate_for(plan))
        engine.execution_coordinator.live_submitter = lambda **kwargs: (_ for _ in ()).throw(RuntimeError("binance timeout"))  # type: ignore[assignment]

        intent = engine.create_order_intent(plan_id=plan.plan_id, execution_mode=ExecutionMode.MICRO_LIVE)
        submission = engine.submit_order_intent(intent_id=intent["intent_id"], live=True)

        assert submission["submit_status"] == "LIVE_SUBMIT_ERROR"
        assert submission["requested_live"] is True
        assert submission["adapter"] == "binance"
        assert submission["state"] == "SUBMITTED"
        assert submission["attachments"]["requires_reconciliation"] is True
        assert submission["attachments"]["reentry_blocked_until_reconciled"] is True
        assert submission["attachments"]["live_submit_error"]["type"] == "RuntimeError"
        assert "before retrying: binance timeout" in submission["message"]

        followup_intent = engine.create_order_intent(plan_id=plan.plan_id, execution_mode=ExecutionMode.MICRO_LIVE)
        assert followup_intent["submit_decision"] == "SKIP_ALREADY_SUBMITTED"
        assert followup_intent["decision_reason_code"] == "plan_reentry_blocked"
        counter_engine = StrategyEngine(db)
        counter_engine.settings.auto_trading_execution_mode = ExecutionMode.MICRO_LIVE
        assert counter_engine._today_trade_count() == 1


def test_live_submitter_exception_rolls_back_failed_session_before_unknown_submission() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        _patch_live_contract(engine, allowed_symbols=["BTCUSDC"])
        plan = _micro_plan(symbol="BTCUSDC", plan_id="sir_BTCUSDC_live_submit_db_error")
        db.add(plan)
        db.add(
            OrderSubmission(
                submission_id="duplicate_submission_for_failed_session",
                intent_id="seed_intent_for_failed_session",
                plan_id=plan.plan_id,
                symbol=plan.symbol,
                client_order_id="seed-client-order",
                state="REJECTED",
                submit_status="SEEDED",
                message="seed row",
                adapter="none",
                execution_mode="MICRO_LIVE",
                attachments={},
                side="BUY",
                order_type="MARKET",
                reduce_only=False,
                requested_live=False,
                raw={},
            )
        )
        db.commit()
        db.expunge_all()
        plan = db.get(Plan, "sir_BTCUSDC_live_submit_db_error")
        assert plan is not None

        _patch_runtime(engine, candidate_row=_candidate_for(plan))

        def failing_submitter(**_kwargs):
            for obj in list(db.identity_map.values()):
                if isinstance(obj, OrderSubmission) and obj.submission_id == "duplicate_submission_for_failed_session":
                    db.expunge(obj)
            db.add(
                OrderSubmission(
                    submission_id="duplicate_submission_for_failed_session",
                    intent_id="transient_failed_insert",
                    plan_id=plan.plan_id,
                    symbol=plan.symbol,
                    client_order_id="transient-client-order",
                    state="REJECTED",
                    submit_status="TRANSIENT",
                    message="transient duplicate",
                    adapter="none",
                    execution_mode="MICRO_LIVE",
                    attachments={},
                    side="BUY",
                    order_type="MARKET",
                    reduce_only=False,
                    requested_live=False,
                    raw={},
                )
            )
            db.flush()

        engine.execution_coordinator.live_submitter = failing_submitter  # type: ignore[assignment]

        intent = engine.create_order_intent(plan_id=plan.plan_id, execution_mode=ExecutionMode.MICRO_LIVE)
        submission = engine.submit_order_intent(intent_id=intent["intent_id"], live=True)

        assert submission["submit_status"] == "LIVE_SUBMIT_ERROR"
        assert submission["adapter"] == "binance"
        assert submission["state"] == "SUBMITTED"
        assert submission["attachments"]["requires_reconciliation"] is True


def test_session_impulse_retest_auto_route_creates_and_submits_live_intent() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        _patch_live_contract(engine, allowed_symbols=["BTCUSDC"])
        plan = _micro_plan(symbol="BTCUSDC", plan_id="sir_BTCUSDC_auto_route_test")
        db.add(plan)
        db.commit()

        created_calls: list[tuple[str, object]] = []
        submitted_calls: list[tuple[str, bool]] = []

        engine.create_order_intent = lambda **kwargs: (  # type: ignore[assignment]
            created_calls.append((str(kwargs["plan_id"]), kwargs["execution_mode"])) or {
                "intent_id": "intent_auto_route_btc",
                "approval_state": ApprovalState.APPROVED_AUTO.value,
                "submit_decision": SubmitDecision.SUBMIT.value,
                "decision_reason_code": "submit_ready",
                "decision_reason_message": "ready",
            }
        )
        engine.submit_order_intent = lambda **kwargs: (  # type: ignore[assignment]
            submitted_calls.append((str(kwargs["intent_id"]), bool(kwargs["live"]))) or {
                "submission_id": "sub_auto_route_btc",
                "submit_status": "NEW",
                "state": "ACKNOWLEDGED",
                "adapter": "binance",
                "requested_live": True,
            }
        )

        payload = engine.auto_route_symbol(symbol="BTCUSDC")

        assert payload["requested_mode"] == ExecutionMode.MICRO_LIVE.value
        assert payload["intents_created"] == 1
        assert payload["submit_calls"] == 1
        assert payload["reason"] == "submitted"
        assert created_calls == [(plan.plan_id, ExecutionMode.MICRO_LIVE)]
        assert submitted_calls == [("intent_auto_route_btc", True)]


def test_auto_route_symbol_submits_sweep_reversal_live_contract_plan() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        _patch_live_contract(engine, allowed_symbols=["BTCUSDC"])
        plan = _sweep_plan(symbol="BTCUSDC", plan_id="sweep_BTCUSDC_auto_route_test")
        db.add(plan)
        db.commit()

        _patch_runtime(engine, candidate_row=_candidate_for(plan))
        engine.execution_coordinator.live_submitter = lambda **kwargs: {  # type: ignore[assignment]
            "status": "NEW",
            "order_id": "live_btc_sweep_001",
            "client_order_id": kwargs["client_order_id"],
            "side": kwargs["side"],
            "order_type": kwargs["order_type"],
            "reduce_only": kwargs["reduce_only"],
        }

        payload = engine.auto_route_symbol(symbol="BTCUSDC")

        assert payload["reason"] == "submitted"
        assert payload["requested_mode"] == ExecutionMode.MICRO_LIVE.value
        assert payload["intents_created"] == 1
        assert payload["submit_calls"] == 1
        assert payload["results"][0]["strategy_family"] == "sweep_reversal"
        assert payload["results"][0]["submission"]["adapter"] == "binance"
        assert payload["results"][0]["submission"]["requested_live"] is True


def test_auto_route_symbol_uses_replay_validation_bridge_for_missing_session_sample(tmp_path: Path) -> None:
    init_db()
    _write_bridge_pass_reports(tmp_path)
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        _patch_live_contract(engine, allowed_symbols=["BTCUSDC"])
        engine.settings.auto_trading_replay_validation_bridge_backtest_dir = str(tmp_path / "backtests")
        engine.settings.auto_trading_replay_validation_bridge_portfolio_dir = str(tmp_path / "risk_sweeps")
        engine.settings.auto_trading_replay_validation_bridge_max_age_days = 30.0
        plan = _micro_plan(symbol="BTCUSDC", plan_id="sir_BTCUSDC_replay_bridge_test")
        db.add(plan)
        db.commit()

        _patch_runtime(engine, candidate_row=_candidate_for(plan))
        engine.metrics = lambda symbol, version: {  # type: ignore[assignment]
            "grade": "F",
            "recommendation": "do-not-deploy",
            "sample_size": 0,
            "risk_state": "OPEN",
            "risk_reason": "normal",
            "operating_lock": {},
        }
        engine.execution_coordinator.live_submitter = lambda **kwargs: {  # type: ignore[assignment]
            "status": "NEW",
            "order_id": "live_btc_replay_bridge_001",
            "client_order_id": kwargs["client_order_id"],
            "side": kwargs["side"],
            "order_type": kwargs["order_type"],
            "reduce_only": kwargs["reduce_only"],
        }

        payload = engine.auto_route_symbol(symbol="BTCUSDC")

        assert payload["reason"] == "submitted"
        assert payload["intents_created"] == 1
        assert payload["submit_calls"] == 1
        assert payload["results"][0]["strategy_family"] == "session_impulse_retest"
        assert payload["results"][0]["submission"]["adapter"] == "binance"
        assert payload["results"][0]["submission"]["requested_live"] is True


def test_auto_route_symbol_keeps_validation_gate_for_sweep_reversal() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        _patch_live_contract(engine, allowed_symbols=["BTCUSDC"])
        plan = _sweep_plan(symbol="BTCUSDC", plan_id="sweep_BTCUSDC_validation_gate_test")
        db.add(plan)
        db.commit()

        _patch_runtime(engine, candidate_row=_candidate_for(plan))
        engine.metrics = lambda symbol, version: {  # type: ignore[assignment]
            "grade": "F",
            "recommendation": "do-not-deploy",
            "risk_state": "OPEN",
            "risk_reason": "normal",
            "operating_lock": {},
        }
        engine.execution_coordinator.live_submitter = lambda **kwargs: (_ for _ in ()).throw(  # type: ignore[assignment]
            AssertionError("validation-blocked sweep plan should not submit")
        )

        payload = engine.auto_route_symbol(symbol="BTCUSDC")

        assert payload["reason"] == "intent_blocked"
        assert payload["intents_created"] == 1
        assert payload["submit_calls"] == 0
        assert payload["results"][0]["strategy_family"] == "sweep_reversal"
        assert payload["results"][0]["intent"]["decision_reason_code"] == "validation_do_not_deploy"


def test_session_impulse_retest_active_thesis_clusters_ignore_zero_risk_and_non_live_rows() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        _patch_live_contract(engine, allowed_symbols=["LINKUSDC", "NEARUSDC", "SOLUSDC"])

        zero_risk_live = _exposure_plan(
            symbol="LINKUSDC",
            plan_id="plan_zero_risk_live",
            strategy_family="legacy_zone_plan",
            recommended_risk_r=0.0,
            thesis_cluster_id="cluster:live:zero",
        )
        non_live_symbol = _exposure_plan(
            symbol="1000BONKUSDC",
            plan_id="plan_non_live_symbol",
            strategy_family="sweep_reversal",
            recommended_risk_r=0.45,
            thesis_cluster_id="cluster:nonlive:symbol",
        )
        positive_live = _exposure_plan(
            symbol="SOLUSDC",
            plan_id="plan_positive_live",
            strategy_family="sweep_reversal",
            recommended_risk_r=0.55,
            thesis_cluster_id="cluster:live:positive",
        )

        count = engine._session_impulse_retest_active_thesis_clusters(
            [zero_risk_live, non_live_symbol, positive_live]
        )

        assert count == 1


def test_session_impulse_retest_live_mode_target_symbols_do_not_depend_on_micro_live_allowlist() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        engine.settings.auto_trading_enabled = True
        engine.settings.auto_trading_execution_mode = ExecutionMode.LIVE.value
        engine.settings.session_impulse_retest_allowed_symbols = "BTCUSDC,ETHUSDC"
        engine.settings.auto_trading_allowed_symbols = "ETHUSDC"
        engine.settings.auto_trading_micro_live_allowed_symbols = "BTCUSDC"

        assert engine._session_impulse_retest_miss_detector_symbols() == ["ETHUSDC"]


def test_session_impulse_retest_active_thesis_clusters_follow_live_mode_symbol_contract() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        engine.settings.auto_trading_enabled = True
        engine.settings.auto_trading_execution_mode = ExecutionMode.LIVE.value
        engine.settings.session_impulse_retest_allowed_symbols = "BTCUSDC,ETHUSDC"
        engine.settings.auto_trading_allowed_symbols = "ETHUSDC"
        engine.settings.auto_trading_micro_live_allowed_symbols = "BTCUSDC"
        engine.settings.auto_trading_allowed_families = "sweep_reversal,session_impulse_retest"
        engine.settings.auto_trading_micro_live_allowed_families = "sweep_reversal,session_impulse_retest"

        btc_live = _exposure_plan(
            symbol="BTCUSDC",
            plan_id="plan_btc_live_contract_mismatch",
            strategy_family="sweep_reversal",
            recommended_risk_r=0.45,
            thesis_cluster_id="cluster:btc:live",
        )
        eth_live = _exposure_plan(
            symbol="ETHUSDC",
            plan_id="plan_eth_live_contract_match",
            strategy_family="sweep_reversal",
            recommended_risk_r=0.55,
            thesis_cluster_id="cluster:eth:live",
        )

        count = engine._session_impulse_retest_active_thesis_clusters([btc_live, eth_live])

        assert count == 1


def test_session_impulse_retest_active_thesis_clusters_follow_live_mode_family_contract() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        engine.settings.auto_trading_enabled = True
        engine.settings.auto_trading_execution_mode = ExecutionMode.LIVE.value
        engine.settings.session_impulse_retest_allowed_symbols = "BTCUSDC"
        engine.settings.auto_trading_allowed_symbols = "BTCUSDC"
        engine.settings.auto_trading_micro_live_allowed_symbols = "BTCUSDC"
        engine.settings.auto_trading_allowed_families = "session_impulse_retest"
        engine.settings.auto_trading_micro_live_allowed_families = "sweep_reversal"

        sweep_live = _exposure_plan(
            symbol="BTCUSDC",
            plan_id="plan_btc_live_family_sweep",
            strategy_family="sweep_reversal",
            recommended_risk_r=0.45,
            thesis_cluster_id="cluster:btc:live:sweep",
        )
        sir_live = _exposure_plan(
            symbol="BTCUSDC",
            plan_id="plan_btc_live_family_sir",
            strategy_family="session_impulse_retest",
            recommended_risk_r=0.55,
            thesis_cluster_id="cluster:btc:live:sir",
        )

        count = engine._session_impulse_retest_active_thesis_clusters([sweep_live, sir_live])

        assert count == 1


def test_session_impulse_retest_active_thesis_clusters_empty_live_symbol_contract_returns_zero() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        engine.settings.auto_trading_enabled = True
        engine.settings.auto_trading_execution_mode = ExecutionMode.LIVE.value
        engine.settings.session_impulse_retest_allowed_symbols = "BTCUSDC"
        engine.settings.auto_trading_allowed_symbols = ""
        engine.settings.auto_trading_allowed_families = "session_impulse_retest"

        sir_live = _exposure_plan(
            symbol="BTCUSDC",
            plan_id="plan_btc_empty_live_symbol_contract",
            strategy_family="session_impulse_retest",
            recommended_risk_r=0.55,
            thesis_cluster_id="cluster:btc:live:sir",
        )

        count = engine._session_impulse_retest_active_thesis_clusters([sir_live])

        assert count == 0


def test_session_impulse_retest_active_thesis_clusters_empty_live_family_contract_returns_zero() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        engine.settings.auto_trading_enabled = True
        engine.settings.auto_trading_execution_mode = ExecutionMode.LIVE.value
        engine.settings.session_impulse_retest_allowed_symbols = "BTCUSDC"
        engine.settings.auto_trading_allowed_symbols = "BTCUSDC"
        engine.settings.auto_trading_allowed_families = ""

        sir_live = _exposure_plan(
            symbol="BTCUSDC",
            plan_id="plan_btc_empty_live_family_contract",
            strategy_family="session_impulse_retest",
            recommended_risk_r=0.55,
            thesis_cluster_id="cluster:btc:live:sir",
        )

        count = engine._session_impulse_retest_active_thesis_clusters([sir_live])

        assert count == 0


def test_micro_live_symbol_priority_ignores_recent_submit_ready_without_created_at() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        engine.settings.auto_trading_micro_live_allowed_symbols = "BTCUSDC,ETHUSDC"
        engine.settings.auto_trading_micro_live_symbol_priority = "BTCUSDC,ETHUSDC"
        engine.settings.auto_trading_micro_live_priority_submit_ready_lookback_minutes = 180
        eth_plan = _micro_plan(symbol="ETHUSDC", plan_id="sir_ETHUSDC_priority_missing_created_at")
        engine.intent_repo.list_recent = lambda limit=500, days=None: [  # type: ignore[assignment]
            SimpleNamespace(
                plan_id="sir_BTCUSDC_priority_missing_created_at",
                symbol="BTCUSDC",
                strategy_family="session_impulse_retest",
                approval_state=ApprovalState.APPROVED_AUTO.value,
                decision_reason_code="submit_ready",
                payload={"entry_model": "LIMIT"},
                created_at=None,
            )
        ]

        guard = engine._micro_live_symbol_priority_guard(
            plan=eth_plan,
            executable_plan={"entry_type": "limit", "strategy_family": "session_impulse_retest"},
            requested_mode=ExecutionMode.MICRO_LIVE,
        )

        assert guard is not None
        assert guard["blocked"] is False
        assert guard["summary"].startswith("ETHUSDC has no higher-priority")


def test_micro_live_symbol_priority_tolerates_malformed_lookback_setting() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        engine.settings.auto_trading_micro_live_allowed_symbols = "BTCUSDC,ETHUSDC"
        engine.settings.auto_trading_micro_live_symbol_priority = "BTCUSDC,ETHUSDC"
        engine.settings.auto_trading_micro_live_priority_submit_ready_lookback_minutes = "bad-lookback"
        eth_plan = _micro_plan(symbol="ETHUSDC", plan_id="sir_ETHUSDC_priority_bad_lookback")
        engine.intent_repo.list_recent = lambda limit=500, days=None: []  # type: ignore[assignment]

        guard = engine._micro_live_symbol_priority_guard(
            plan=eth_plan,
            executable_plan={"entry_type": "limit", "strategy_family": "session_impulse_retest"},
            requested_mode=ExecutionMode.MICRO_LIVE,
        )

        assert guard is not None
        assert guard["lookback_minutes"] == 180
        assert guard["blocked"] is False


def test_micro_live_symbol_priority_uses_candidate_own_created_at_for_sorting() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        engine.settings.auto_trading_micro_live_allowed_symbols = "BTCUSDC,SOLUSDC"
        engine.settings.auto_trading_micro_live_symbol_priority = "BTCUSDC,SOLUSDC"
        engine.settings.auto_trading_micro_live_priority_submit_ready_lookback_minutes = 180
        sol_plan = _micro_plan(symbol="SOLUSDC", plan_id="sir_SOLUSDC_priority_created_at_sort")
        now = datetime.now(timezone.utc)
        engine.intent_repo.list_recent = lambda limit=500, days=None: [  # type: ignore[assignment]
            SimpleNamespace(
                plan_id="sir_BTCUSDC_priority_old",
                symbol="BTCUSDC",
                strategy_family="session_impulse_retest",
                approval_state=ApprovalState.APPROVED_AUTO.value,
                decision_reason_code="submit_ready",
                payload={"entry_model": "LIMIT"},
                created_at=now - timedelta(minutes=90),
            ),
            SimpleNamespace(
                plan_id="sir_BTCUSDC_priority_new",
                symbol="BTCUSDC",
                strategy_family="session_impulse_retest",
                approval_state=ApprovalState.APPROVED_AUTO.value,
                decision_reason_code="submit_ready",
                payload={"entry_model": "LIMIT"},
                created_at=now - timedelta(minutes=10),
            ),
        ]

        guard = engine._micro_live_symbol_priority_guard(
            plan=sol_plan,
            executable_plan={"entry_type": "limit", "strategy_family": "session_impulse_retest"},
            requested_mode=ExecutionMode.MICRO_LIVE,
        )

        assert guard is not None
        assert guard["blocked"] is True
        assert guard["preferred_plan_id"] == "sir_BTCUSDC_priority_new"
        assert guard["active"] is True


def test_session_impulse_retest_active_thesis_clusters_zero_when_auto_trading_shadow_mode() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        engine.settings.auto_trading_enabled = True
        engine.settings.auto_trading_execution_mode = ExecutionMode.SHADOW.value
        engine.settings.session_impulse_retest_allowed_symbols = "BTCUSDC"
        engine.settings.auto_trading_allowed_symbols = "BTCUSDC"
        engine.settings.auto_trading_allowed_families = "session_impulse_retest"

        sir_live = _exposure_plan(
            symbol="BTCUSDC",
            plan_id="plan_btc_shadow_mode_exposure",
            strategy_family="session_impulse_retest",
            recommended_risk_r=0.55,
            thesis_cluster_id="cluster:btc:shadow:sir",
        )

        count = engine._session_impulse_retest_active_thesis_clusters([sir_live])

        assert count == 0


def test_runtime_sync_symbols_preserves_explicit_live_symbols_outside_top_universe() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        engine.settings.auto_trading_allowed_symbols = "BTCUSDC,OUTSIDEUSDC"
        engine.settings.auto_trading_micro_live_allowed_symbols = "BTCUSDC,OUTSIDEUSDC"
        engine.settings.session_impulse_retest_allowed_symbols = "BTCUSDC,OUTSIDEUSDC"
        engine.market_data.refresh_universe = lambda limit=30: ["BTCUSDC", "ETHUSDC", "SOLUSDC"]  # type: ignore[assignment]

        symbols = engine.runtime_sync_symbols(limit_symbols=3)

        assert symbols[:4] == ["BTCUSDC", "OUTSIDEUSDC", "ETHUSDC", "SOLUSDC"]


def test_current_exposure_rows_include_recent_live_submission_without_plan_execution_mode() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        engine.settings.auto_trading_execution_mode = ExecutionMode.MICRO_LIVE
        plan = _micro_plan(symbol="BTCUSDC", plan_id="sir_BTCUSDC_exposure_test")
        validity = dict(plan.validity or {})
        validity.pop("execution_mode", None)
        plan.validity = validity
        plan.state = "PLANNED"
        db.add(plan)
        db.commit()

        class _Submission:
            plan_id = plan.plan_id
            adapter = "binance"
            state = "SUBMITTED"
            execution_mode = ExecutionMode.MICRO_LIVE.value
            requested_live = True

        engine.submission_repo.list_recent = lambda days=7, limit=5000: [_Submission()]  # type: ignore[assignment]

        rows = engine._current_exposure_rows()

        assert [row.plan_id for row in rows] == [plan.plan_id]


def test_session_impulse_retest_auto_route_respects_recent_intent_cooldown() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        _patch_live_contract(engine, allowed_symbols=["BTCUSDC"])
        plan = _micro_plan(symbol="BTCUSDC", plan_id="sir_BTCUSDC_auto_route_cooldown")
        db.add(plan)
        db.commit()

        engine.intent_repo.latest_for_plan = lambda plan_id: SimpleNamespace(  # type: ignore[assignment]
            intent_id="intent_recent_btc",
            created_at=datetime.now(timezone.utc),
            execution_mode=ExecutionMode.MICRO_LIVE.value,
            payload={"requested_execution_mode": ExecutionMode.MICRO_LIVE.value},
            submit_decision=SubmitDecision.SKIP_BLOCKED.value,
            approval_state=ApprovalState.BLOCKED.value,
            decision_reason_code="approval_blocked",
        )
        engine.create_order_intent = lambda **kwargs: (_ for _ in ()).throw(AssertionError("create_order_intent should not be called"))  # type: ignore[assignment]
        engine.submit_order_intent = lambda **kwargs: (_ for _ in ()).throw(AssertionError("submit_order_intent should not be called"))  # type: ignore[assignment]

        payload = engine.auto_route_symbol(symbol="BTCUSDC")

        assert payload["reason"] == "recent_intent_cooldown_active"
        assert payload["intents_created"] == 0
        assert payload["submit_calls"] == 0
        assert payload["results"][0]["status"] == "skipped_recent_intent"


def test_session_impulse_retest_auto_route_ignores_recent_intent_cooldown_for_different_mode() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        _patch_live_contract(engine, allowed_symbols=["BTCUSDC"])
        plan = _micro_plan(symbol="BTCUSDC", plan_id="sir_BTCUSDC_auto_route_cooldown_mode_guard")
        db.add(plan)
        db.commit()

        engine.intent_repo.latest_for_plan = lambda plan_id: SimpleNamespace(  # type: ignore[assignment]
            intent_id="intent_recent_paper",
            created_at=datetime.now(timezone.utc),
            execution_mode=ExecutionMode.PAPER.value,
            payload={"requested_execution_mode": ExecutionMode.PAPER.value},
            submit_decision=SubmitDecision.SKIP_BLOCKED.value,
            approval_state=ApprovalState.BLOCKED.value,
            decision_reason_code="validation_do_not_deploy",
        )
        engine.create_order_intent = lambda **kwargs: {  # type: ignore[assignment]
            "intent_id": "intent_new_micro_live",
            "approval_state": ApprovalState.BLOCKED.value,
            "submit_decision": SubmitDecision.SKIP_BLOCKED.value,
            "decision_reason_code": "validation_do_not_deploy",
            "decision_reason_message": "Validation recommendation is do-not-deploy.",
        }
        engine.submit_order_intent = lambda **kwargs: (_ for _ in ()).throw(AssertionError("blocked intent should not submit"))  # type: ignore[assignment]

        payload = engine._auto_route_session_impulse_retest_plan(
            symbol="BTCUSDC",
            plan=plan,
            requested_mode=ExecutionMode.MICRO_LIVE,
            now=datetime.now(timezone.utc),
        )

        assert payload["reason"] == "intent_blocked"
        assert payload["intents_created"] == 1
        assert payload["submit_calls"] == 0
        assert payload["results"][0]["intent"]["intent_id"] == "intent_new_micro_live"


def test_session_impulse_retest_auto_route_ignores_recent_intent_cooldown_without_created_at() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        _patch_live_contract(engine, allowed_symbols=["BTCUSDC"])
        plan = _micro_plan(symbol="BTCUSDC", plan_id="sir_BTCUSDC_auto_route_cooldown_missing_ts")
        db.add(plan)
        db.commit()

        engine.intent_repo.latest_for_plan = lambda plan_id: SimpleNamespace(  # type: ignore[assignment]
            intent_id="intent_recent_missing_created_at",
            created_at=None,
            execution_mode=ExecutionMode.MICRO_LIVE.value,
            payload={"requested_execution_mode": ExecutionMode.MICRO_LIVE.value},
            submit_decision=SubmitDecision.SKIP_BLOCKED.value,
            approval_state=ApprovalState.BLOCKED.value,
            decision_reason_code="validation_do_not_deploy",
        )
        engine.create_order_intent = lambda **kwargs: {  # type: ignore[assignment]
            "intent_id": "intent_new_after_missing_ts",
            "approval_state": ApprovalState.BLOCKED.value,
            "submit_decision": SubmitDecision.SKIP_BLOCKED.value,
            "decision_reason_code": "validation_do_not_deploy",
            "decision_reason_message": "Validation recommendation is do-not-deploy.",
        }

        payload = engine._auto_route_session_impulse_retest_plan(
            symbol="BTCUSDC",
            plan=plan,
            requested_mode=ExecutionMode.MICRO_LIVE,
            now=datetime.now(timezone.utc),
        )

        assert payload["reason"] == "intent_blocked"
        assert payload["intents_created"] == 1
        assert payload["results"][0]["intent"]["intent_id"] == "intent_new_after_missing_ts"


def test_session_impulse_retest_auto_route_tolerates_malformed_cooldown_setting() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        engine.settings.auto_trading_intent_recheck_cooldown_seconds = "bad-cooldown"
        result = engine._auto_route_recent_intent_cooldown(
            plan_id="sir_BTCUSDC_bad_cooldown",
            requested_mode=ExecutionMode.MICRO_LIVE,
            now=datetime.now(timezone.utc),
        )

        assert result is None


def test_ws_stream_auto_route_active_tolerates_malformed_max_age_setting(tmp_path) -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        engine.settings.runtime_worker_heartbeat_dir = str(tmp_path)
        engine.settings.runtime_worker_ws_heartbeat_max_age_seconds = "bad-max-age"
        now = datetime.now(timezone.utc).replace(microsecond=0)
        write_worker_heartbeat(
            "ws",
            settings=engine.settings,
            status="ok",
            at=now,
            details={"phase": "streaming", "started_at": now.isoformat(), "processed_messages": 1},
        )

        assert engine._ws_stream_auto_route_active(now=now) is True


def test_strategy_engine_maybe_int_rejects_non_finite_values() -> None:
    assert StrategyEngine._maybe_int("inf") is None
    assert StrategyEngine._maybe_int(float("nan")) is None
    assert StrategyEngine._maybe_int("3.9") == 3


def test_sync_universe_suppresses_auto_route_when_ws_stream_is_active(tmp_path) -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        _patch_live_contract(engine, allowed_symbols=["NEARUSDC"])
        engine.settings.session_impulse_retest_allowed_symbols = "NEARUSDC"
        engine.settings.runtime_worker_heartbeat_dir = str(tmp_path)
        write_worker_heartbeat(
            "ws",
            settings=engine.settings,
            status="ok",
            details={
                "phase": "streaming",
                "started_at": datetime.now(timezone.utc).isoformat(),
                "processed_messages": 10,
            },
        )

        engine.market_data.backfill_symbol_timeframes = lambda **kwargs: {"ok": True}  # type: ignore[method-assign]
        engine.refresh_symbol = lambda symbol: {  # type: ignore[assignment]
            "symbol": symbol,
            "session_impulse_retest_plan_ids": ["sir_NEARUSDC_S_duplicate_guard"],
        }
        engine.auto_route_session_impulse_retest_plans = (  # type: ignore[assignment]
            lambda **kwargs: (_ for _ in ()).throw(AssertionError("loop worker must not auto-route while ws is active"))
        )
        engine.auto_route_symbol = (  # type: ignore[assignment]
            lambda **kwargs: (_ for _ in ()).throw(AssertionError("loop worker must not fallback-route while ws is active"))
        )

        payload = engine._sync_universe_symbol_local(
            symbol="NEARUSDC",
            limit_1m=120,
            limit_5m=500,
            limit_15m=500,
        )

        assert payload["auto_route"]["enabled"] is False
        assert payload["auto_route"]["reason"] == "ws_stream_active_route_suppressed"
        assert payload["auto_route"]["plans_considered"] == 1
        assert payload["auto_route"]["intents_created"] == 0
        assert payload["auto_route"]["submit_calls"] == 0
        audits = engine.session_impulse_retest_runtime_audits_recent(
            hours=1,
            symbol="NEARUSDC",
            phase="auto_route",
            limit=5,
        )
        assert audits
        assert audits[0]["status"] == "ws_stream_active_route_suppressed"
        assert audits[0]["payload"]["plans_considered"] == 1


def test_session_impulse_retest_direct_plan_route_creates_and_submits_live_intent() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        _patch_live_contract(engine, allowed_symbols=["BTCUSDC"])
        plan = _micro_plan(symbol="BTCUSDC", plan_id="sir_BTCUSDC_direct_route_test")
        db.add(plan)
        db.commit()

        created_calls: list[tuple[str, object]] = []
        submitted_calls: list[tuple[str, bool]] = []

        engine.create_order_intent = lambda **kwargs: (  # type: ignore[assignment]
            created_calls.append((str(kwargs["plan_id"]), kwargs["execution_mode"])) or {
                "intent_id": "intent_direct_route_btc",
                "approval_state": ApprovalState.APPROVED_AUTO.value,
                "submit_decision": SubmitDecision.SUBMIT.value,
                "decision_reason_code": "submit_ready",
                "decision_reason_message": "ready",
            }
        )
        engine.submit_order_intent = lambda **kwargs: (  # type: ignore[assignment]
            submitted_calls.append((str(kwargs["intent_id"]), bool(kwargs["live"]))) or {
                "submission_id": "sub_direct_route_btc",
                "submit_status": "NEW",
                "state": "ACKNOWLEDGED",
                "adapter": "binance",
                "requested_live": True,
            }
        )

        payload = engine.auto_route_session_impulse_retest_plans(
            symbol="BTCUSDC",
            plan_ids=[plan.plan_id],
        )

        assert payload["requested_mode"] == ExecutionMode.MICRO_LIVE.value
        assert payload["intents_created"] == 1
        assert payload["submit_calls"] == 1
        assert payload["reason"] == "submitted"
        assert created_calls == [(plan.plan_id, ExecutionMode.MICRO_LIVE)]
        assert submitted_calls == [("intent_direct_route_btc", True)]


def test_session_impulse_retest_shadow_symbol_is_not_auto_routed_live() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        _patch_live_contract(engine, allowed_symbols=["BTCUSDC"])
        engine.settings.session_impulse_retest_allowed_symbols = "BTCUSDC,SUIUSDC"
        plan = _micro_plan(symbol="SUIUSDC", plan_id="sir_SUIUSDC_direct_route_test")
        db.add(plan)
        db.commit()

        engine.create_order_intent = lambda **kwargs: (_ for _ in ()).throw(AssertionError("shadow symbol should not create intent"))  # type: ignore[assignment]
        engine.submit_order_intent = lambda **kwargs: (_ for _ in ()).throw(AssertionError("shadow symbol should not submit"))  # type: ignore[assignment]

        direct_payload = engine.auto_route_session_impulse_retest_plans(
            symbol="SUIUSDC",
            plan_ids=[plan.plan_id],
        )
        fallback_payload = engine.auto_route_symbol(symbol="SUIUSDC")

        assert direct_payload["reason"] == "symbol_not_live_enabled_for_auto_route"
        assert fallback_payload["reason"] == "symbol_not_live_enabled_for_auto_route"
        audits = engine.session_impulse_retest_runtime_audits_recent(
            hours=1,
            symbol="SUIUSDC",
            phase="auto_route",
            limit=5,
        )
        assert audits
        assert audits[0]["status"] == "symbol_not_live_enabled_for_auto_route"


def test_session_impulse_retest_auto_route_stops_when_family_disabled() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        _patch_live_contract(engine, allowed_symbols=["BTCUSDC"])
        engine.settings.session_impulse_retest_enabled = False
        plan = _micro_plan(symbol="BTCUSDC", plan_id="sir_BTCUSDC_family_disabled_test")
        db.add(plan)
        db.commit()

        engine.create_order_intent = lambda **kwargs: (_ for _ in ()).throw(AssertionError("family-disabled symbol should not create intent"))  # type: ignore[assignment]
        engine.submit_order_intent = lambda **kwargs: (_ for _ in ()).throw(AssertionError("family-disabled symbol should not submit"))  # type: ignore[assignment]

        direct_payload = engine.auto_route_session_impulse_retest_plans(
            symbol="BTCUSDC",
            plan_ids=[plan.plan_id],
        )
        fallback_payload = engine.auto_route_symbol(symbol="BTCUSDC")

        assert direct_payload["reason"] == "family_disabled"
        assert fallback_payload["reason"] == "family_disabled"


def test_session_impulse_retest_auto_route_stops_when_family_shadow_only() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        _patch_live_contract(engine, allowed_symbols=["BTCUSDC"])
        engine.settings.session_impulse_retest_shadow_only = True
        plan = _micro_plan(symbol="BTCUSDC", plan_id="sir_BTCUSDC_family_shadow_only_test")
        db.add(plan)
        db.commit()

        engine.create_order_intent = lambda **kwargs: (_ for _ in ()).throw(AssertionError("shadow-only symbol should not create intent"))  # type: ignore[assignment]
        engine.submit_order_intent = lambda **kwargs: (_ for _ in ()).throw(AssertionError("shadow-only symbol should not submit"))  # type: ignore[assignment]

        direct_payload = engine.auto_route_session_impulse_retest_plans(
            symbol="BTCUSDC",
            plan_ids=[plan.plan_id],
        )
        fallback_payload = engine.auto_route_symbol(symbol="BTCUSDC")

        assert direct_payload["reason"] == "family_shadow_only"
        assert fallback_payload["reason"] == "family_shadow_only"


def test_session_impulse_retest_create_order_intent_respects_family_shadow_only() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        _patch_live_contract(engine, allowed_symbols=["BTCUSDC"])
        engine.settings.session_impulse_retest_shadow_only = True
        plan = _micro_plan(symbol="BTCUSDC", plan_id="sir_BTCUSDC_shadow_only_intent_test")
        db.add(plan)
        db.commit()

        _patch_runtime(engine, candidate_row=_candidate_for(plan))

        intent = engine.create_order_intent(plan_id=plan.plan_id, execution_mode=ExecutionMode.MICRO_LIVE)

        assert intent["approval_state"] == ApprovalState.APPROVED_SHADOW.value
        assert intent["decision_reason_code"] == "session_impulse_retest_shadow_only"


def test_session_impulse_retest_create_order_intent_respects_family_disabled() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        _patch_live_contract(engine, allowed_symbols=["BTCUSDC"])
        engine.settings.session_impulse_retest_enabled = False
        plan = _micro_plan(symbol="BTCUSDC", plan_id="sir_BTCUSDC_family_disabled_intent_test")
        db.add(plan)
        db.commit()

        _patch_runtime(engine, candidate_row=_candidate_for(plan))

        intent = engine.create_order_intent(plan_id=plan.plan_id, execution_mode=ExecutionMode.MICRO_LIVE)

        assert intent["approval_state"] == ApprovalState.APPROVED_SHADOW.value
        assert intent["decision_reason_code"] == "session_impulse_retest_family_disabled"


def test_session_impulse_retest_empty_live_allowlist_does_not_fall_back_to_all_tracked_symbols() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        engine.settings.auto_trading_enabled = True
        engine.settings.auto_trading_execution_mode = ExecutionMode.MICRO_LIVE.value
        engine.settings.session_impulse_retest_allowed_symbols = "BTCUSDC,SUIUSDC"
        engine.settings.auto_trading_micro_live_allowed_symbols = ""

        assert engine._session_impulse_retest_live_routable_symbols(ExecutionMode.MICRO_LIVE) == set()
        assert engine._session_impulse_retest_symbol_live_routable(
            symbol="SUIUSDC",
            requested_mode=ExecutionMode.MICRO_LIVE,
        ) is False
        payload = engine.auto_route_symbol(symbol="SUIUSDC")
        assert payload["reason"] == "symbol_not_live_enabled_for_auto_route"


def test_stream_binance_klines_refreshes_1m_and_5m_final_for_same_symbol() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        refresh_calls: list[str] = []
        auto_route_calls: list[tuple[str, tuple[str, ...]]] = []
        base_ts = datetime.now(timezone.utc).replace(second=0, microsecond=0)

        async def fake_stream_klines(*, symbols, interval):
            if interval == "5m":
                await asyncio.sleep(0.01)
            yield SimpleNamespace(
                symbol="BTCUSDC",
                open_time=base_ts,
                o=100.0,
                h=101.0,
                l=99.5,
                c=100.5,
                v=10.0,
                is_final=True,
            )

        engine.market_data.binance.stream_klines = fake_stream_klines  # type: ignore[assignment]
        engine.market_data.ingest_candle = lambda payload: None  # type: ignore[assignment]
        engine.refresh_symbol = (  # type: ignore[assignment]
            lambda symbol: refresh_calls.append(str(symbol)) or {"symbol": symbol, "session_impulse_retest_plan_ids": [f"sir_{symbol}_L_test"]}
        )
        engine.auto_route_session_impulse_retest_plans = (  # type: ignore[assignment]
            lambda *, symbol, plan_ids: auto_route_calls.append((str(symbol), tuple(plan_ids))) or {"submit_calls": 0, "intents_created": 0}
        )
        engine.auto_route_symbol = (  # type: ignore[assignment]
            lambda *, symbol: (_ for _ in ()).throw(AssertionError("fallback auto_route_symbol should not be used"))
        )

        payload = asyncio.run(
            engine.stream_binance_klines(
                symbols=["BTCUSDC"],
                intervals=["1m", "5m"],
                refresh_on_final=True,
                max_messages=2,
            )
        )

        assert payload["refresh_calls"] == 2
        assert payload["auto_route_calls"] == 2
        assert refresh_calls == ["BTCUSDC", "BTCUSDC"]
        assert auto_route_calls == [
            ("BTCUSDC", ("sir_BTCUSDC_L_test",)),
            ("BTCUSDC", ("sir_BTCUSDC_L_test",)),
        ]


def test_session_impulse_retest_miss_detector_flags_missing_intent(tmp_path) -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        engine.settings.runtime_worker_heartbeat_dir = str(tmp_path)
        engine.settings.session_impulse_retest_enabled = True
        engine.settings.session_impulse_retest_allowed_symbols = "XRPUSDC"
        engine.settings.auto_trading_allowed_symbols = "XRPUSDC"
        engine.settings.auto_trading_micro_live_allowed_symbols = "XRPUSDC"

        replay_trade = SimpleNamespace(
            entry_ts=datetime.now(timezone.utc) - timedelta(hours=1),
            direction="short",
            r_value=-1.25,
            exit_reason="stop",
        )
        engine._session_impulse_retest_recent_replay_trades = lambda **kwargs: [replay_trade]  # type: ignore[assignment]
        engine._session_impulse_retest_runtime_plan_observation = lambda **kwargs: {  # type: ignore[assignment]
            "seen": True,
            "plan_id": "sir_XRPUSDC_S_20260501T0100",
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "valid_from": datetime.now(timezone.utc).isoformat(),
            "valid_until": (datetime.now(timezone.utc) + timedelta(minutes=12)).isoformat(),
        }
        engine.intent_repo.list_for_plan = lambda plan_id, limit=20: []  # type: ignore[assignment]
        engine.submission_repo.list_for_plan = lambda plan_id, limit=20: []  # type: ignore[assignment]

        payload = engine.detect_session_impulse_retest_recent_misses(
            lookback_hours=24,
            symbols=["XRPUSDC"],
            write_report=False,
        )

        assert payload["observation_mode"] == "replay_runtime_simulation"
        assert payload["expected_trade_count"] == 1
        assert payload["runtime_observed_count"] == 1
        assert payload["miss_count"] == 1
        assert payload["misses"][0]["symbol"] == "XRPUSDC"
        assert payload["misses"][0]["miss_reason"] == "missing_intent"


def test_session_impulse_retest_miss_detector_flags_unobserved_runtime_plan(tmp_path) -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        engine.settings.session_impulse_retest_enabled = True
        engine.settings.session_impulse_retest_allowed_symbols = "SOLUSDC"
        engine.settings.auto_trading_allowed_symbols = "SOLUSDC"
        engine.settings.auto_trading_micro_live_allowed_symbols = "SOLUSDC"
        engine.settings.runtime_worker_heartbeat_dir = str(tmp_path)

        replay_trade = SimpleNamespace(
            entry_ts=datetime.now(timezone.utc) - timedelta(hours=1),
            direction="long",
            r_value=0.75,
            exit_reason="target",
        )
        engine._session_impulse_retest_recent_replay_trades = lambda **kwargs: [replay_trade]  # type: ignore[assignment]
        engine._session_impulse_retest_runtime_plan_observation = lambda **kwargs: {"seen": False}  # type: ignore[assignment]

        payload = engine.detect_session_impulse_retest_recent_misses(
            lookback_hours=24,
            symbols=["SOLUSDC"],
            write_report=False,
        )

        assert payload["expected_trade_count"] == 1
        assert payload["runtime_observed_count"] == 0
        assert payload["miss_count"] == 1
        assert payload["by_symbol"]["SOLUSDC"]["misses"] == 1
        assert payload["misses"][0]["symbol"] == "SOLUSDC"
        assert payload["misses"][0]["miss_reason"] == "runtime_plan_not_seen"


def test_session_impulse_retest_miss_detector_marks_trades_before_ws_start_without_false_miss(tmp_path) -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        engine.settings.runtime_worker_heartbeat_dir = str(tmp_path)
        engine.settings.session_impulse_retest_enabled = True
        engine.settings.session_impulse_retest_allowed_symbols = "SOLUSDC"
        engine.settings.auto_trading_allowed_symbols = "SOLUSDC"
        engine.settings.auto_trading_micro_live_allowed_symbols = "SOLUSDC"

        now = datetime.now(timezone.utc).replace(microsecond=0)
        runtime_started_at = now - timedelta(minutes=30)
        replay_trade = SimpleNamespace(
            entry_ts=now - timedelta(hours=1),
            direction="long",
            r_value=1.0,
            exit_reason="target",
        )
        write_worker_heartbeat(
            "ws",
            settings=engine.settings,
            status="ok",
            details={"phase": "streaming", "started_at": runtime_started_at.isoformat(), "processed_messages": 1},
        )

        engine._session_impulse_retest_recent_replay_trades = lambda **kwargs: [replay_trade]  # type: ignore[assignment]
        engine._session_impulse_retest_runtime_plan_observation = lambda **kwargs: {"seen": False}  # type: ignore[assignment]

        payload = engine.detect_session_impulse_retest_recent_misses(
            lookback_hours=24,
            symbols=["SOLUSDC"],
            write_report=False,
        )

        assert payload["expected_trade_count"] == 1
        assert payload["runtime_observed_count"] == 0
        assert payload["skipped_before_runtime_start_count"] == 1
        assert payload["miss_count"] == 0
        assert payload["runtime_started_at"] == runtime_started_at.isoformat()
        assert payload["by_symbol"]["SOLUSDC"]["skipped_before_runtime_start"] == 1


def test_session_impulse_retest_miss_detector_ignores_malformed_ws_started_at(tmp_path) -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        engine.settings.runtime_worker_heartbeat_dir = str(tmp_path)
        engine.settings.session_impulse_retest_enabled = True
        engine.settings.session_impulse_retest_allowed_symbols = "SOLUSDC"
        engine.settings.auto_trading_allowed_symbols = "SOLUSDC"
        engine.settings.auto_trading_micro_live_allowed_symbols = "SOLUSDC"

        replay_trade = SimpleNamespace(
            entry_ts=datetime.now(timezone.utc) - timedelta(hours=1),
            direction="long",
            r_value=1.0,
            exit_reason="target",
        )
        write_worker_heartbeat(
            "ws",
            settings=engine.settings,
            status="ok",
            details={"phase": "streaming", "started_at": "not-a-timestamp", "processed_messages": 1},
        )

        engine._session_impulse_retest_recent_replay_trades = lambda **kwargs: [replay_trade]  # type: ignore[assignment]
        engine._session_impulse_retest_runtime_plan_observation = lambda **kwargs: {"seen": False}  # type: ignore[assignment]

        payload = engine.detect_session_impulse_retest_recent_misses(
            lookback_hours=24,
            symbols=["SOLUSDC"],
            write_report=False,
        )

        assert payload["runtime_started_at"] is None
        assert payload["skipped_before_runtime_start_count"] == 0
        assert payload["miss_count"] == 1


def test_session_impulse_retest_miss_detector_skips_pre_start_trade_before_replay_observation(tmp_path) -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        engine.settings.runtime_worker_heartbeat_dir = str(tmp_path)
        engine.settings.session_impulse_retest_enabled = True
        engine.settings.session_impulse_retest_allowed_symbols = "SOLUSDC"
        engine.settings.auto_trading_allowed_symbols = "SOLUSDC"
        engine.settings.auto_trading_micro_live_allowed_symbols = "SOLUSDC"

        now = datetime.now(timezone.utc).replace(microsecond=0)
        runtime_started_at = now - timedelta(minutes=30)
        replay_trade = SimpleNamespace(
            entry_ts=now - timedelta(hours=1),
            direction="long",
            r_value=1.0,
            exit_reason="target",
        )
        write_worker_heartbeat(
            "ws",
            settings=engine.settings,
            status="ok",
            details={"phase": "streaming", "started_at": runtime_started_at.isoformat(), "processed_messages": 1},
        )

        def fail_if_replayed(**_kwargs) -> dict:
            raise AssertionError("pre-start trades must not be replay-observed as current runtime activity")

        engine._session_impulse_retest_recent_replay_trades = lambda **kwargs: [replay_trade]  # type: ignore[assignment]
        engine._session_impulse_retest_runtime_plan_observation = fail_if_replayed  # type: ignore[assignment]

        payload = engine.detect_session_impulse_retest_recent_misses(
            lookback_hours=24,
            symbols=["SOLUSDC"],
            write_report=False,
        )

        assert payload["expected_trade_count"] == 1
        assert payload["runtime_observed_count"] == 0
        assert payload["skipped_before_runtime_start_count"] == 1
        assert payload["miss_count"] == 0
        assert payload["effective_window_start"] == runtime_started_at.isoformat()


def test_session_impulse_retest_miss_detector_treats_existing_intent_as_observed(tmp_path) -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        engine.settings.runtime_worker_heartbeat_dir = str(tmp_path)
        engine.settings.session_impulse_retest_enabled = True
        engine.settings.session_impulse_retest_allowed_symbols = "SOLUSDC"
        engine.settings.auto_trading_allowed_symbols = "SOLUSDC"
        engine.settings.auto_trading_micro_live_allowed_symbols = "SOLUSDC"

        replay_trade = SimpleNamespace(
            entry_ts=datetime.now(timezone.utc) - timedelta(hours=1),
            direction="long",
            r_value=1.0,
            exit_reason="target",
        )
        engine._session_impulse_retest_recent_replay_trades = lambda **kwargs: [replay_trade]  # type: ignore[assignment]
        engine._session_impulse_retest_runtime_plan_observation = lambda **kwargs: {  # type: ignore[assignment]
            "seen": False,
            "plan_id": "sir_SOLUSDC_L_existing",
        }
        engine.intent_repo.list_for_plan = lambda plan_id, limit=20: [SimpleNamespace(intent_id="intent_existing")]  # type: ignore[assignment]
        engine.submission_repo.list_for_plan = lambda plan_id, limit=20: []  # type: ignore[assignment]

        payload = engine.detect_session_impulse_retest_recent_misses(
            lookback_hours=24,
            symbols=["SOLUSDC"],
            write_report=False,
        )

        assert payload["expected_trade_count"] == 1
        assert payload["runtime_observed_count"] == 1
        assert payload["miss_count"] == 0
        assert payload["by_symbol"]["SOLUSDC"]["runtime_observed_trades"] == 1


def test_session_impulse_retest_miss_detector_disables_when_family_shadow_only() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        engine.settings.session_impulse_retest_enabled = True
        engine.settings.session_impulse_retest_shadow_only = True

        payload = engine.detect_session_impulse_retest_recent_misses(
            lookback_hours=24,
            write_report=False,
        )

        assert payload["enabled"] is False
        assert payload["disabled_reason"] == "family_shadow_only"
        assert payload["expected_trade_count"] == 0
        assert payload["miss_count"] == 0


def test_session_impulse_retest_miss_detector_disables_when_auto_trading_disabled() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        engine.settings.session_impulse_retest_enabled = True
        engine.settings.auto_trading_enabled = False

        payload = engine.detect_session_impulse_retest_recent_misses(
            lookback_hours=24,
            write_report=False,
        )

        assert payload["enabled"] is False
        assert payload["disabled_reason"] == "auto_trading_disabled_or_shadow_mode"
        assert payload["expected_trade_count"] == 0
        assert payload["miss_count"] == 0


def test_session_impulse_retest_miss_alert_emits_and_writes_report(tmp_path: Path) -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        engine.settings.session_impulse_retest_miss_alert_enabled = True
        engine.settings.validation_alert_channel = "discord"
        engine.settings.session_impulse_retest_miss_alert_cooldown_seconds = 3600
        engine.settings.session_impulse_retest_miss_detector_report_dir = str(tmp_path)

        dispatch_calls: list[dict] = []
        published_events: list[tuple[str, dict]] = []
        engine.notification_dispatcher.dispatch = lambda **kwargs: (  # type: ignore[assignment]
            dispatch_calls.append(dict(kwargs)) or {
                "channel": "discord",
                "delivered": True,
                "skipped": False,
                "reason": "delivered",
            }
        )
        engine.alert_retry_queue.capture_delivery_failure = lambda **kwargs: []  # type: ignore[assignment]
        engine.events.publish = lambda event_type, payload: published_events.append((event_type, dict(payload)))  # type: ignore[assignment]

        report = {
            "enabled": True,
            "family": "session_impulse_retest",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "lookback_hours": 24,
            "window_start": (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat(),
            "window_end": datetime.now(timezone.utc).isoformat(),
            "expected_trade_count": 2,
            "runtime_observed_count": 2,
            "miss_count": 2,
            "misses": [
                {
                    "symbol": "ADAUSDC",
                    "plan_id": "sir_ADAUSDC_S_test",
                    "direction": "short",
                    "entry_ts": datetime.now(timezone.utc).isoformat(),
                    "miss_reason": "missing_intent",
                },
                {
                    "symbol": "XRPUSDC",
                    "plan_id": "sir_XRPUSDC_S_test",
                    "direction": "short",
                    "entry_ts": datetime.now(timezone.utc).isoformat(),
                    "miss_reason": "missing_intent",
                },
            ],
            "report_path": None,
        }

        payload = engine._maybe_emit_session_impulse_retest_miss_alert(report=report)

        assert payload is not None
        assert payload["emitted"] is True
        assert payload["miss_count"] == 2
        assert payload["symbols_with_misses"] == ["ADAUSDC", "XRPUSDC"]
        assert report["report_path"]
        assert Path(str(report["report_path"])).exists()
        assert len(dispatch_calls) == 1
        assert dispatch_calls[0]["alert_type"] == "session_impulse_retest_miss"
        assert dispatch_calls[0]["symbol"] == "SESSION_IMPULSE_RETEST"
        assert "miss=2" in dispatch_calls[0]["payload"]["message"]
        assert "symbols=ADAUSDC,XRPUSDC" in dispatch_calls[0]["payload"]["message"]
        assert published_events
        assert published_events[0][0] == "session_impulse_retest.miss"
        recent = engine.alert_repo.find_recent(
            symbol="SESSION_IMPULSE_RETEST",
            channel="discord",
            alert_type="session_impulse_retest_miss",
            within_seconds=3600,
        )
        assert recent is not None


def test_session_impulse_retest_miss_alert_respects_cooldown(tmp_path: Path) -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        engine.settings.session_impulse_retest_miss_alert_enabled = True
        engine.settings.validation_alert_channel = "discord"
        engine.settings.session_impulse_retest_miss_alert_cooldown_seconds = 3600
        engine.settings.session_impulse_retest_miss_detector_report_dir = str(tmp_path)

        dispatch_calls: list[dict] = []
        engine.notification_dispatcher.dispatch = lambda **kwargs: (  # type: ignore[assignment]
            dispatch_calls.append(dict(kwargs)) or {
                "channel": "discord",
                "delivered": True,
                "skipped": False,
                "reason": "delivered",
            }
        )
        engine.alert_retry_queue.capture_delivery_failure = lambda **kwargs: []  # type: ignore[assignment]
        engine.events.publish = lambda event_type, payload: None  # type: ignore[assignment]

        report = {
            "enabled": True,
            "family": "session_impulse_retest",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "lookback_hours": 24,
            "window_start": (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat(),
            "window_end": datetime.now(timezone.utc).isoformat(),
            "expected_trade_count": 1,
            "runtime_observed_count": 1,
            "miss_count": 1,
            "misses": [
                {
                    "symbol": "ETHUSDC",
                    "plan_id": "sir_ETHUSDC_S_test",
                    "direction": "short",
                    "entry_ts": datetime.now(timezone.utc).isoformat(),
                    "miss_reason": "missing_intent",
                }
            ],
            "report_path": None,
        }

        first = engine._maybe_emit_session_impulse_retest_miss_alert(report=report)
        second = engine._maybe_emit_session_impulse_retest_miss_alert(report=report)

        assert first is not None and first["emitted"] is True
        assert second is not None and second["emitted"] is False
        assert second["reason"] == "cooldown_active"
        assert len(dispatch_calls) == 1


def test_session_impulse_retest_refresh_writes_runtime_audit_for_insufficient_candles() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        symbol = f"AUDITEMPTY{int(datetime.now(timezone.utc).timestamp() * 1_000_000)}USDC"
        engine.settings.session_impulse_retest_allowed_symbols = symbol

        payload = engine.refresh_symbol(symbol)

        assert payload["updated"] is False
        assert payload["reason"] == "insufficient_candles"
        audits = engine.session_impulse_retest_runtime_audits_recent(
            hours=1,
            symbol=symbol,
            phase="refresh",
            limit=5,
        )
        assert audits
        latest = audits[0]
        assert latest["status"] == "insufficient_candles"
        assert latest["payload"]["reason"] == "insufficient_candles"


def test_session_impulse_retest_non_tracked_symbol_does_not_write_runtime_audit() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        _patch_live_contract(engine, allowed_symbols=["BTCUSDC"])
        engine.settings.session_impulse_retest_allowed_symbols = "BTCUSDC,ETHUSDC"
        symbol = "WLFIUSDC"

        route_payload = engine.auto_route_symbol(symbol=symbol)

        assert route_payload["reason"] == "symbol_not_live_enabled_for_auto_route"
        audits = engine.session_impulse_retest_runtime_audits_recent(
            hours=1,
            symbol=symbol,
            limit=5,
        )
        assert audits == []


def test_session_impulse_retest_auto_route_writes_runtime_audit() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        _patch_live_contract(engine, allowed_symbols=["BTCUSDC", "ETHUSDC", "SOLUSDC"])
        plan = _micro_plan(symbol="BTCUSDC", plan_id="sir_BTCUSDC_audit_test")
        db.add(plan)
        db.commit()

        _patch_runtime(engine, candidate_row=_candidate_for(plan))

        engine.execution_coordinator.live_submitter = lambda **kwargs: {  # type: ignore[assignment]
            "status": "NEW",
            "order_id": "live_btc_audit_001",
            "client_order_id": kwargs["client_order_id"],
            "side": kwargs["side"],
            "order_type": kwargs["order_type"],
            "reduce_only": kwargs["reduce_only"],
        }

        payload = engine.auto_route_session_impulse_retest_plans(
            symbol="BTCUSDC",
            plan_ids=[plan.plan_id],
        )

        assert payload["reason"] == "submitted"
        audits = engine.session_impulse_retest_runtime_audits_recent(
            hours=1,
            symbol="BTCUSDC",
            phase="auto_route",
            limit=5,
        )
        assert audits
        latest = audits[0]
        assert latest["status"] == "submitted"
        assert latest["plan_id"] == plan.plan_id
        assert latest["payload"]["requested_mode"] == ExecutionMode.MICRO_LIVE.value


def test_session_impulse_retest_auto_route_rolls_back_before_intent_error_audit() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        _patch_live_contract(engine, allowed_symbols=["BTCUSDC"])
        plan = _micro_plan(symbol="BTCUSDC", plan_id="sir_BTCUSDC_intent_error_audit")
        db.add(plan)
        db.commit()

        rollbacks: list[str] = []
        original_rollback = db.rollback

        def _rollback() -> None:
            rollbacks.append("rollback")
            original_rollback()

        db.rollback = _rollback  # type: ignore[method-assign]
        engine.create_order_intent = lambda **kwargs: (_ for _ in ()).throw(RuntimeError("intent db error"))  # type: ignore[assignment]

        payload = engine.auto_route_session_impulse_retest_plans(
            symbol="BTCUSDC",
            plan_ids=[plan.plan_id],
        )

        assert payload["reason"] == "intent_creation_failed"
        assert rollbacks
        audits = engine.session_impulse_retest_runtime_audits_recent(
            hours=1,
            symbol="BTCUSDC",
            phase="auto_route",
            limit=5,
        )
        assert audits[0]["status"] == "intent_creation_failed"
        assert audits[0]["plan_id"] == plan.plan_id
        assert "intent db error" in audits[0]["payload"]["results"][0]["error"]


def test_session_impulse_retest_runtime_audit_report_marks_hard_status_fail() -> None:
    summary = run_session_impulse_retest_runtime_audit_report._status_summary(
        [
            {
                "symbol": "BTCUSDC",
                "phase": "auto_route",
                "status": "submit_error",
                "decision_code": "submit_ready",
            }
        ]
    )

    assert summary["overall_status"] == "FAIL"
    assert summary["reason"] == "runtime_audit_has_hard_route_failures"
    assert summary["hard_status_counts"] == {"submit_error": 1}


def test_session_impulse_retest_runtime_audit_report_main_writes_latest_aliases(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    monkeypatch.setattr(
        run_session_impulse_retest_runtime_audit_report,
        "build_payload",
        lambda **_kwargs: {
            "generated_at": "2026-05-10T00:00:00Z",
            "hours": 3,
            "symbol": "",
            "phase_filter": "",
            "status_filter": "",
            "overall_status": "PASS",
            "reason": "runtime_audit_recent_and_no_hard_route_failures",
            "audit_count": 1,
            "phase_counts": {"auto_route": 1},
            "status_counts": {"submitted": 1},
            "decision_code_counts": {"submit_ready": 1},
            "hard_status_counts": {},
            "watch_status_counts": {},
            "recent_audits": [
                {
                    "symbol": "BTCUSDC",
                    "phase": "auto_route",
                    "status": "submitted",
                    "plan_id": "sir_BTCUSDC_test",
                    "decision_code": "submit_ready",
                    "observed_ts": "2026-05-10T00:00:00Z",
                }
            ],
        },
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_session_impulse_retest_runtime_audit_report.py",
            "--report-dir",
            str(tmp_path),
            "--no-fail-exit",
        ],
    )

    run_session_impulse_retest_runtime_audit_report.main()
    output = json.loads(capsys.readouterr().out)

    assert (tmp_path / "session_impulse_retest_runtime_audit_20260510T000000Z.md").exists()
    assert (tmp_path / "latest.md").exists()
    assert (tmp_path / "latest.json").exists()
    assert output["latest_report_path"].endswith("latest.md")
    latest_payload = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    assert latest_payload["overall_status"] == "PASS"


def test_session_impulse_retest_refresh_audit_status_stays_no_fresh_without_sir_plan(monkeypatch) -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        symbol = "BTCUSDC"
        engine.settings.session_impulse_retest_allowed_symbols = symbol
        base_ts = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        engine.market_data.recent_candles = lambda *args, **kwargs: [  # type: ignore[assignment]
            SimpleNamespace(
                ts=base_ts - timedelta(minutes=max(0, kwargs.get("limit", 10) - 1 - i)),
                o=100.0,
                h=101.0,
                l=99.0,
                c=100.5,
                v=10.0,
            )
            for i in range(kwargs.get("limit", 10))
        ]
        engine.context_engine.build_snapshot = lambda **kwargs: SimpleNamespace(  # type: ignore[assignment]
            jump_rate_5m=0.0,
            atr5=1.0,
            transition_score=50.0,
            transition_state="none",
            transition_lock_reason=None,
        )
        engine.zone_repo.list_all = lambda **kwargs: []  # type: ignore[assignment]
        engine.zone_engine.refresh = lambda **kwargs: []  # type: ignore[assignment]
        engine._evaluate_gate = lambda **kwargs: (SimpleNamespace(value="OPEN"), True, "normal", SimpleNamespace(to_dict=lambda: {}))  # type: ignore[assignment]
        engine._runtime_feature_calibration = lambda **kwargs: ("range", None)  # type: ignore[assignment]
        engine.plan_repo.list_exposure_candidates = lambda **kwargs: []  # type: ignore[assignment]
        engine.plan_generator.generate = lambda **kwargs: [SimpleNamespace(plan=_micro_plan(symbol=symbol, plan_id="legacy_plan_generated"))]  # type: ignore[assignment]
        engine._session_impulse_retest_runtime_plan = lambda **kwargs: None  # type: ignore[assignment]
        engine.plan_generator.generation_diagnostics = lambda **kwargs: {"generation_state": "generated"}  # type: ignore[assignment]
        engine.plan_repo.upsert_many = lambda plans: None  # type: ignore[assignment]
        engine.plan_repo.invalidate_expired = lambda: None  # type: ignore[assignment]
        engine.plan_repo.list_active_for_symbol = lambda **kwargs: []  # type: ignore[assignment]
        engine._emit_pre_entry_plan_alerts = lambda **kwargs: {"near": 0, "touch": 0, "confirm": 0, "emitted_total": 0}  # type: ignore[assignment]
        engine.events.publish = lambda *args, **kwargs: None  # type: ignore[assignment]
        engine.plan_generator.resolve_regime_label = lambda context: "range"  # type: ignore[assignment]

        payload = engine.refresh_symbol(symbol)

        assert payload["session_impulse_retest_generated_count"] == 0
        audits = engine.session_impulse_retest_runtime_audits_recent(
            hours=1,
            symbol=symbol,
            phase="refresh",
            limit=1,
        )
        assert audits
        assert audits[0]["status"] == "no_fresh_candidates"


def test_session_impulse_retest_refresh_audit_marks_family_disabled(monkeypatch) -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        symbol = "BTCUSDC"
        engine.settings.session_impulse_retest_allowed_symbols = symbol
        engine.settings.session_impulse_retest_enabled = False
        base_ts = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        engine.market_data.recent_candles = lambda *args, **kwargs: [  # type: ignore[assignment]
            SimpleNamespace(
                ts=base_ts - timedelta(minutes=max(0, kwargs.get("limit", 10) - 1 - i)),
                o=100.0,
                h=101.0,
                l=99.0,
                c=100.5,
                v=10.0,
            )
            for i in range(kwargs.get("limit", 10))
        ]
        engine.context_engine.build_snapshot = lambda **kwargs: SimpleNamespace(  # type: ignore[assignment]
            jump_rate_5m=0.0,
            atr5=1.0,
            transition_score=50.0,
            transition_state="none",
            transition_lock_reason=None,
        )
        engine.zone_repo.list_all = lambda **kwargs: []  # type: ignore[assignment]
        engine.zone_engine.refresh = lambda **kwargs: []  # type: ignore[assignment]
        engine._evaluate_gate = lambda **kwargs: (SimpleNamespace(value="OPEN"), True, "normal", SimpleNamespace(to_dict=lambda: {}))  # type: ignore[assignment]
        engine._runtime_feature_calibration = lambda **kwargs: ("range", None)  # type: ignore[assignment]
        engine.plan_repo.list_exposure_candidates = lambda **kwargs: []  # type: ignore[assignment]
        engine.plan_generator.generate = lambda **kwargs: []  # type: ignore[assignment]
        engine.plan_generator.generation_diagnostics = lambda **kwargs: {"generation_state": "generated"}  # type: ignore[assignment]
        engine.plan_repo.upsert_many = lambda plans: None  # type: ignore[assignment]
        engine.plan_repo.invalidate_expired = lambda: None  # type: ignore[assignment]
        engine.plan_repo.list_active_for_symbol = lambda **kwargs: []  # type: ignore[assignment]
        engine._emit_pre_entry_plan_alerts = lambda **kwargs: {"near": 0, "touch": 0, "confirm": 0, "emitted_total": 0}  # type: ignore[assignment]
        engine.events.publish = lambda *args, **kwargs: None  # type: ignore[assignment]
        engine.plan_generator.resolve_regime_label = lambda context: "range"  # type: ignore[assignment]

        payload = engine.refresh_symbol(symbol)

        assert payload["session_impulse_retest_generated_count"] == 0
        audits = engine.session_impulse_retest_runtime_audits_recent(
            hours=1,
            symbol=symbol,
            phase="refresh",
            limit=1,
        )
        assert audits
        assert audits[0]["status"] == "family_disabled"
        assert audits[0]["decision_code"] == "family_disabled"
