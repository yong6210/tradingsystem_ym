from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from app.core.enums import ApprovalState, ExecutionMode, SubmitDecision
from app.db.models import ExecutionFill, Plan
from app.db.session import SessionLocal, init_db
from app.domain.execution import RolloutPolicy
from app.services.strategy_engine import StrategyEngine


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
        db.add(plan)
        db.commit()

        class _Submission:
            plan_id = plan.plan_id
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


def test_session_impulse_retest_miss_detector_flags_missing_intent() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
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
        engine.settings.session_impulse_retest_allowed_symbols = "BTCUSDC,ETHUSDC"
        symbol = "WLFIUSDC"

        route_payload = engine.auto_route_symbol(symbol=symbol)

        assert route_payload["reason"] == "symbol_not_enabled_for_session_impulse_retest"
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
