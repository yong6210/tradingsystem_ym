from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

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
from app.services.lane_tracker import get_execution_lane_tracker, reset_execution_lane_tracker
from app.services.execution_coordinator import ExecutionCoordinator
from app.services.strategy_engine import StrategyEngine
from app.services.family_rollout import RolloutPolicyService
from app.services.family_rollout import RolloutPolicyBootstrap
from app.services.operating_lock import OperatingLockSnapshot
from app.services.safety_locks import SafetyLockService
from app.services.thesis_fingerprint import ThesisFingerprintService

client = TestClient(app)


def test_family_rollout_bootstrap_keeps_sweep_reversal_out_of_micro_live_by_default() -> None:
    policy = RolloutPolicyBootstrap().get("sweep_reversal")

    assert policy.live_enabled is False
    assert policy.max_execution_mode == ExecutionMode.PAPER
    assert policy.max_risk_r == 0.0


def test_binance_live_position_side_mode_maps_hedge_directions() -> None:
    coordinator = ExecutionCoordinator.__new__(ExecutionCoordinator)
    coordinator.settings = SimpleNamespace(binance_live_position_side_mode="HEDGE")

    assert coordinator._binance_live_position_side(plan=SimpleNamespace(direction="long"), side="BUY") == "LONG"
    assert coordinator._binance_live_position_side(plan=SimpleNamespace(direction="short"), side="SELL") == "SHORT"

    coordinator.settings = SimpleNamespace(binance_live_position_side_mode="ONE_WAY")
    assert coordinator._binance_live_position_side(plan=SimpleNamespace(direction="long"), side="BUY") is None


def _reset_execution_control_state() -> None:
    reset_execution_lane_tracker()
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
            live_enabled=False,
            max_execution_mode="PAPER",
            max_risk_r=0.5,
            allowed_sessions=["london", "new_york"],
            min_quality_score=75.0,
            updated_by="test_reset",
        )
        rollout.upsert(
            family="sweep_reversal",
            live_enabled=True,
            max_execution_mode="MICRO_LIVE",
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
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_entry_models", "LIMIT,CONFIRM")
    monkeypatch.setattr(settings, "auto_trading_micro_live_max_concurrent_positions", 5)
    monkeypatch.setattr(settings, "auto_trading_micro_live_max_daily_new_entries", 10)
    monkeypatch.setattr(settings, "auto_trading_reconciliation_user_stream_stale_seconds", 180)
    monkeypatch.setattr(settings, "binance_trade_live_enabled", False)
    monkeypatch.setattr(settings, "binance_live_position_side_mode", "ONE_WAY")
    monkeypatch.setattr(settings, "auto_trading_live_balance_sync_enabled", False)
    monkeypatch.setattr(settings, "auto_trading_live_liquidity_gate_enabled", False)
    monkeypatch.setattr(settings, "portfolio_overlay_enabled", False)
    monkeypatch.setattr(settings, "transition_edge_variant_enabled", True)
    monkeypatch.setattr(settings, "transition_edge_variant_shadow_only", True)
    monkeypatch.setattr(settings, "transition_edge_variant_partial_activation_ratio", 0.3)
    monkeypatch.setattr(
        "app.services.strategy_engine.StrategyEngine.load_binance_symbol_trading_rules",
        lambda self, symbol: {
            "symbol": str(symbol).upper(),
            "quantity_step": 0.001,
            "min_quantity": 0.001,
            "source": "test_default",
        },
    )


def _seed_plan(
    *,
    symbol: str,
    family: str,
    plan_id: str,
    state: str = "ARMED",
    strategy_grade: str = "A",
    thesis_fingerprint: dict | None = None,
    entry_model: str = "CONFIRM",
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
                entry_model=entry_model,
                entry_price=100.0,
                entry_condition="limit_on_touch" if entry_model == "LIMIT" else "touch_then_confirm",
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
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._live_cluster_guard", lambda self, **kwargs: {})

    symbol = f"EXECPRE{int(datetime.now(timezone.utc).timestamp() * 1_000_000)}USDC"
    plan_id = f"{symbol}_plan"
    _seed_plan(symbol=symbol, family="sweep_reversal", plan_id=plan_id, entry_model="LIMIT")

    preview = client.post("/execution/plans/preview", json={"plan_id": plan_id})
    assert preview.status_code == 200
    preview_payload = preview.json()
    assert preview_payload["plan_id"] == plan_id
    assert preview_payload["strategy_family"] == "sweep_reversal"

    approval = client.post("/execution/approve-plan", json={"plan_id": plan_id})
    assert approval.status_code == 200
    approval_payload = approval.json()
    assert approval_payload["approval_state"] == "APPROVED_AUTO"
    assert approval_payload["allowed_execution_mode"] == "MICRO_LIVE"
    assert approval_payload["rollout_policy"]["max_execution_mode"] == "MICRO_LIVE"


def test_execution_approval_blocks_same_window_family_cluster_for_micro_live(monkeypatch) -> None:
    init_db()
    _apply_auto_trading_defaults(monkeypatch)
    settings = get_settings()
    monkeypatch.setattr(settings, "auto_trading_live_family_cluster_window_minutes", 30)
    monkeypatch.setattr(settings, "auto_trading_live_max_same_family_entries_per_window", 1)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine.metrics", _good_metrics)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._gate_context_for_symbol", _open_gate_context)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._today_trade_count", lambda self: 0)

    now_token = int(datetime.now(timezone.utc).timestamp() * 1_000_000)
    symbol = f"CLUSTER{now_token}USDC"
    other_symbol = f"CLUSTER{now_token + 1}USDC"
    plan_id = f"{symbol}_plan"
    other_plan_id = f"{other_symbol}_plan"
    _seed_plan(symbol=symbol, family="sweep_reversal", plan_id=plan_id, entry_model="LIMIT")
    _seed_plan(
        symbol=other_symbol,
        family="sweep_reversal",
        plan_id=other_plan_id,
        state="ENTERED",
        entry_model="LIMIT",
    )

    with SessionLocal() as db:
        other_plan = PlanRepository(db).get(other_plan_id)
        assert other_plan is not None
        monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._current_exposure_rows", lambda self: [other_plan])

        approval = client.post("/execution/approve-plan", json={"plan_id": plan_id})
        assert approval.status_code == 200
        approval_payload = approval.json()

    assert approval_payload["approval_state"] == "BLOCKED"
    assert approval_payload["approval_reasons"][0]["code"] == "live_family_cluster_window_cap_reached"


def test_micro_live_symbol_priority_blocks_eth_when_recent_btc_submit_ready_exists(monkeypatch) -> None:
    init_db()
    _apply_auto_trading_defaults(monkeypatch)
    settings = get_settings()
    now_token = int(datetime.now(timezone.utc).timestamp() * 1_000_000)
    btc_symbol = f"BTCPRIO{now_token}USDC"
    eth_symbol = f"ETHPRIO{now_token}USDC"
    btc_plan_id = f"{btc_symbol}_plan"
    eth_plan_id = f"{eth_symbol}_plan"
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_symbols", f"{btc_symbol},{eth_symbol}")
    monkeypatch.setattr(settings, "auto_trading_micro_live_symbol_priority", f"{btc_symbol},{eth_symbol}")
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_families", "sweep_reversal")
    monkeypatch.setattr(settings, "auto_trading_micro_live_priority_submit_ready_lookback_minutes", 180)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine.metrics", _good_metrics)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._gate_context_for_symbol", _open_gate_context)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._today_trade_count", lambda self: 0)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._current_exposure_rows", lambda self: [])
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._live_cluster_guard", lambda self, **kwargs: {})

    _seed_plan(symbol=btc_symbol, family="sweep_reversal", plan_id=btc_plan_id, entry_model="LIMIT")
    _seed_plan(symbol=eth_symbol, family="sweep_reversal", plan_id=eth_plan_id, entry_model="LIMIT")

    with SessionLocal() as db:
        db.add(
            OrderIntent(
                intent_id=f"intent_{btc_symbol}_submit_ready",
                plan_id=btc_plan_id,
                symbol=btc_symbol,
                strategy_family="sweep_reversal",
                execution_mode="MICRO_LIVE",
                approval_state="APPROVED_AUTO",
                submit_decision="SUBMIT",
                decision_reason_code="submit_ready",
                decision_reason_message="ready",
                thesis_fingerprint={},
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
                payload={"entry_model": "LIMIT"},
                created_at=datetime.now(timezone.utc) - timedelta(minutes=15),
            )
        )
        db.commit()

    intent = client.post(
        "/execution/order-intents",
        json={"plan_id": eth_plan_id, "execution_mode": "MICRO_LIVE"},
    )
    assert intent.status_code == 200
    intent_payload = intent.json()
    assert intent_payload["approval_state"] == "BLOCKED"
    assert intent_payload["submit_decision"] == "SKIP_BLOCKED"
    assert intent_payload["decision_reason_code"] == "micro_live_higher_priority_symbol_available"
    assert btc_symbol in intent_payload["decision_reason_message"]


def test_micro_live_symbol_priority_keeps_btc_as_top_priority(monkeypatch) -> None:
    init_db()
    _apply_auto_trading_defaults(monkeypatch)
    settings = get_settings()
    now_token = int(datetime.now(timezone.utc).timestamp() * 1_000_000)
    btc_symbol = f"BTCPRIO{now_token + 1}USDC"
    eth_symbol = f"ETHPRIO{now_token + 1}USDC"
    btc_plan_id = f"{btc_symbol}_plan"
    eth_plan_id = f"{eth_symbol}_plan"
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_symbols", f"{btc_symbol},{eth_symbol}")
    monkeypatch.setattr(settings, "auto_trading_micro_live_symbol_priority", f"{btc_symbol},{eth_symbol}")
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_families", "sweep_reversal")
    monkeypatch.setattr(settings, "auto_trading_micro_live_priority_submit_ready_lookback_minutes", 180)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine.metrics", _good_metrics)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._gate_context_for_symbol", _open_gate_context)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._today_trade_count", lambda self: 0)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._current_exposure_rows", lambda self: [])
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._live_cluster_guard", lambda self, **kwargs: {})

    _seed_plan(symbol=btc_symbol, family="sweep_reversal", plan_id=btc_plan_id, entry_model="LIMIT")
    _seed_plan(symbol=eth_symbol, family="sweep_reversal", plan_id=eth_plan_id, entry_model="LIMIT")

    with SessionLocal() as db:
        db.add(
            OrderIntent(
                intent_id=f"intent_{eth_symbol}_submit_ready",
                plan_id=eth_plan_id,
                symbol=eth_symbol,
                strategy_family="sweep_reversal",
                execution_mode="MICRO_LIVE",
                approval_state="APPROVED_AUTO",
                submit_decision="SUBMIT",
                decision_reason_code="submit_ready",
                decision_reason_message="ready",
                thesis_fingerprint={},
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
                payload={"entry_model": "LIMIT"},
                created_at=datetime.now(timezone.utc) - timedelta(minutes=15),
            )
        )
        db.commit()

    approval = client.post("/execution/approve-plan", json={"plan_id": btc_plan_id})
    assert approval.status_code == 200
    approval_payload = approval.json()
    assert approval_payload["approval_state"] == "APPROVED_AUTO"
    assert approval_payload["allowed_execution_mode"] == "MICRO_LIVE"


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


def test_submit_tolerates_malformed_lane_tracker_window(monkeypatch) -> None:
    init_db()
    _apply_auto_trading_defaults(monkeypatch)
    settings = get_settings()
    monkeypatch.setattr(settings, "transition_edge_variant_lane_tracker_window", "bad-window")
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine.metrics", _good_metrics)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._gate_context_for_symbol", _open_gate_context)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._today_trade_count", lambda self: 0)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._current_exposure_rows", lambda self: [])

    symbol = f"LANE{int(datetime.now(timezone.utc).timestamp() * 1_000_000)}USDC"
    plan_id = f"{symbol}_plan"
    _seed_plan(symbol=symbol, family="sweep_reversal", plan_id=plan_id)

    intent = client.post(
        "/execution/order-intents",
        json={"plan_id": plan_id, "execution_mode": "PAPER"},
    )
    assert intent.status_code == 200
    intent_payload = intent.json()
    assert intent_payload["submit_decision"] == "SUBMIT"

    submit = client.post(
        "/execution/submit",
        json={"intent_id": intent_payload["intent_id"], "live": False, "paper_scenario": "fill"},
    )

    assert submit.status_code == 200
    assert submit.json()["state"] == "FILLED"


def test_order_intent_blocks_plan_reentry_when_prior_submission_exists(monkeypatch) -> None:
    init_db()
    _apply_auto_trading_defaults(monkeypatch)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine.metrics", _good_metrics)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._gate_context_for_symbol", _open_gate_context)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._today_trade_count", lambda self: 0)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._current_exposure_rows", lambda self: [])

    symbol = f"PREENTRY{int(datetime.now(timezone.utc).timestamp() * 1_000_000) + 101}USDC"
    plan_id = f"{symbol}_plan"
    _seed_plan(symbol=symbol, family="sweep_reversal", plan_id=plan_id)

    first_intent = client.post(
        "/execution/order-intents",
        json={"plan_id": plan_id, "execution_mode": "PAPER"},
    )
    assert first_intent.status_code == 200
    first_intent_payload = first_intent.json()
    assert first_intent_payload["submit_decision"] == "SUBMIT"

    first_submit = client.post(
        "/execution/submit",
        json={"intent_id": first_intent_payload["intent_id"], "live": False, "paper_scenario": "fill"},
    )
    assert first_submit.status_code == 200
    assert first_submit.json()["state"] == "FILLED"

    with SessionLocal() as db:
        plan = db.get(Plan, plan_id)
        assert plan is not None
        plan.state = "PLANNED"
        db.add(plan)
        db.commit()

    second_intent = client.post(
        "/execution/order-intents",
        json={"plan_id": plan_id, "execution_mode": "PAPER"},
    )
    assert second_intent.status_code == 200
    second_intent_payload = second_intent.json()
    assert second_intent_payload["submit_decision"] == "SKIP_ALREADY_SUBMITTED"
    assert second_intent_payload["decision_reason_code"] == "plan_reentry_blocked"
    assert "already has routed submission" in second_intent_payload["decision_reason_message"]


def test_submit_rejects_plan_reentry_when_prior_submission_exists(monkeypatch) -> None:
    init_db()
    _apply_auto_trading_defaults(monkeypatch)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine.metrics", _good_metrics)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._gate_context_for_symbol", _open_gate_context)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._today_trade_count", lambda self: 0)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._current_exposure_rows", lambda self: [])

    symbol = f"PRESUB{int(datetime.now(timezone.utc).timestamp() * 1_000_000) + 102}USDC"
    plan_id = f"{symbol}_plan"
    _seed_plan(symbol=symbol, family="sweep_reversal", plan_id=plan_id)

    first_intent = client.post(
        "/execution/order-intents",
        json={"plan_id": plan_id, "execution_mode": "PAPER"},
    )
    assert first_intent.status_code == 200
    first_intent_payload = first_intent.json()

    first_submit = client.post(
        "/execution/submit",
        json={"intent_id": first_intent_payload["intent_id"], "live": False, "paper_scenario": "fill"},
    )
    assert first_submit.status_code == 200
    assert first_submit.json()["state"] == "FILLED"

    with SessionLocal() as db:
        plan = db.get(Plan, plan_id)
        assert plan is not None
        plan.state = "PLANNED"
        db.add(plan)
        db.add(
            OrderIntent(
                intent_id=f"intent_{symbol}_manual_reentry",
                plan_id=plan_id,
                symbol=symbol,
                strategy_family="sweep_reversal",
                execution_mode="PAPER",
                approval_state="APPROVED_AUTO",
                submit_decision="SUBMIT",
                decision_reason_code="submit_ready",
                decision_reason_message="ready",
                thesis_fingerprint={},
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

    second_submit = client.post(
        "/execution/submit",
        json={"intent_id": f"intent_{symbol}_manual_reentry", "live": False, "paper_scenario": "fill"},
    )
    assert second_submit.status_code == 200
    second_submit_payload = second_submit.json()
    assert second_submit_payload["adapter"] == "none"
    assert second_submit_payload["submit_status"] == "PLAN_REENTRY_BLOCKED"
    assert second_submit_payload["state"] == "REJECTED"


def test_order_intent_allows_reentry_when_prior_paper_submission_is_stale(monkeypatch) -> None:
    init_db()
    _apply_auto_trading_defaults(monkeypatch)
    settings = get_settings()
    monkeypatch.setattr(settings, "auto_trading_paper_submission_stale_hours", 1)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine.metrics", _good_metrics)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._gate_context_for_symbol", _open_gate_context)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._today_trade_count", lambda self: 0)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._current_exposure_rows", lambda self: [])

    symbol = f"STALESUB{int(datetime.now(timezone.utc).timestamp() * 1_000_000) + 102}USDC"
    plan_id = f"{symbol}_plan"
    _seed_plan(symbol=symbol, family="sweep_reversal", plan_id=plan_id)

    first_intent = client.post(
        "/execution/order-intents",
        json={"plan_id": plan_id, "execution_mode": "PAPER"},
    )
    assert first_intent.status_code == 200
    first_intent_payload = first_intent.json()

    first_submit = client.post(
        "/execution/submit",
        json={"intent_id": first_intent_payload["intent_id"], "live": False, "paper_scenario": "fill"},
    )
    assert first_submit.status_code == 200

    stale_ts = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=10)
    with SessionLocal() as db:
        plan = db.get(Plan, plan_id)
        assert plan is not None
        plan.state = "PLANNED"
        db.add(plan)
        submission = db.query(OrderSubmission).filter(OrderSubmission.plan_id == plan_id).one()
        submission.submitted_at = stale_ts
        submission.acknowledged_at = stale_ts
        submission.updated_at = stale_ts
        db.add(submission)
        db.commit()

    second_intent = client.post(
        "/execution/order-intents",
        json={"plan_id": plan_id, "execution_mode": "PAPER"},
    )
    assert second_intent.status_code == 200
    second_intent_payload = second_intent.json()
    assert second_intent_payload["submit_decision"] == "SUBMIT"
    assert second_intent_payload["decision_reason_code"] == "submit_ready"
    self_heal = dict(second_intent_payload.get("self_heal_summary") or {})
    assert self_heal["stale_paper_reentry_block_ignored"] is True
    assert self_heal["stale_paper_reentry_block_ignored_count"] >= 1


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
        assert payload["partial_exit_events"] >= 2
        assert payload["closed_events"] >= 1
        assert any(action.get("plan_id") == plan_id for action in payload["actions"])

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


def test_paper_exit_tick_waits_for_candle_after_latest_fill() -> None:
    init_db()
    _reset_execution_control_state()

    symbol = f"PEXWAIT{int(datetime.now(timezone.utc).timestamp() * 1_000_000) + 3}USDC"
    plan_id = f"{symbol}_plan"
    _seed_plan(symbol=symbol, family="sweep_reversal", plan_id=plan_id, state="ENTERED")

    candle_ts = datetime.now(timezone.utc).replace(microsecond=0, second=0)
    entry_fill_ts = candle_ts + timedelta(seconds=40)
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
                submitted_at=entry_fill_ts,
                acknowledged_at=entry_fill_ts,
            )
        )
        db.add(
            ExecutionFill(
                fill_id=f"fill_{symbol}_entry",
                plan_id=plan_id,
                symbol=symbol,
                stage="ENTRY",
                fill_ts=entry_fill_ts,
                price=100.0,
                qty=1.0,
                fee=0.0,
                from_state="ARMED",
                to_state="ENTERED",
                state_changed=True,
                payload={"source": "paper_adapter"},
                strategy_version="v1",
            )
        )
        db.add(
            Candle(
                symbol=symbol,
                timeframe="1m",
                ts=candle_ts,
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
        assert any(
            action.get("plan_id") == plan_id and action.get("status") == "await_next_candle_after_last_fill"
            for action in payload["actions"]
        )

    with SessionLocal() as db:
        refreshed = db.get(Plan, plan_id)
        assert refreshed is not None
        assert refreshed.state == "ENTERED"
        fills = db.query(ExecutionFill).filter(ExecutionFill.plan_id == plan_id).all()
        assert [fill.stage for fill in fills] == ["ENTRY"]


def test_paper_exit_tick_repairs_armed_plan_state_from_entry_fill() -> None:
    init_db()
    symbol = f"PEXWAIT{int(datetime.now(timezone.utc).timestamp() * 1_000_000) + 6}USDC"
    plan_id = f"{symbol}_plan"
    _seed_plan(symbol=symbol, family="sweep_reversal", plan_id=plan_id, state="ARMED")
    candle_ts = datetime.now(timezone.utc).replace(microsecond=0, second=0)
    entry_fill_ts = candle_ts + timedelta(seconds=40)

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
                submitted_at=entry_fill_ts,
                acknowledged_at=entry_fill_ts,
            )
        )
        db.add(
            ExecutionFill(
                fill_id=f"{plan_id}_entry",
                plan_id=plan_id,
                symbol=symbol,
                stage="ENTRY",
                fill_ts=entry_fill_ts,
                price=100.0,
                qty=1.0,
                fee=0.0,
                from_state="ARMED",
                to_state="ENTERED",
                state_changed=True,
                payload={"source": "paper_adapter"},
                strategy_version="v1",
            )
        )
        db.add(
            Candle(
                symbol=symbol,
                timeframe="1m",
                ts=candle_ts,
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
        assert payload["state_repairs"] >= 1
        assert any(
            action.get("plan_id") == plan_id and action.get("status") == "await_next_candle_after_last_fill"
            for action in payload["actions"]
        )

    with SessionLocal() as db:
        refreshed = db.get(Plan, plan_id)
        assert refreshed is not None
        assert refreshed.state == "ENTERED"


def test_paper_exit_tick_repairs_missing_entry_fill_from_submission_raw() -> None:
    init_db()
    symbol = f"PREENTRY{int(datetime.now(timezone.utc).timestamp() * 1_000_000) + 9}USDC"
    plan_id = f"{symbol}_plan"
    _seed_plan(symbol=symbol, family="sweep_reversal", plan_id=plan_id, state="ARMED")
    submitted_at = datetime.now(timezone.utc).replace(microsecond=0, second=0)
    candle_ts = submitted_at + timedelta(minutes=1)

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
                raw={
                    "fill_results": [
                        {
                            "accepted": True,
                            "duplicate": False,
                            "fill_id": f"paper_fill_{symbol}_entry",
                            "plan_id": plan_id,
                            "symbol": symbol,
                            "stage": "ENTRY",
                            "from_state": "ARMED",
                            "to_state": "ENTERED",
                            "state_changed": True,
                            "reason": "applied",
                            "exit_reason": None,
                        }
                    ]
                },
                submitted_at=submitted_at,
                acknowledged_at=submitted_at,
            )
        )
        db.add(
            Candle(
                symbol=symbol,
                timeframe="1m",
                ts=candle_ts,
                o=100.0,
                h=100.4,
                l=99.8,
                c=100.1,
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
        assert payload["fill_repairs"] >= 1

    with SessionLocal() as db:
        fills = (
            db.query(ExecutionFill)
            .filter(ExecutionFill.plan_id == plan_id)
            .order_by(ExecutionFill.fill_ts.asc())
            .all()
        )
        assert [fill.stage for fill in fills] == ["ENTRY"]
        assert dict(fills[0].payload or {})["source"] == "paper_submission_raw_repair"
        refreshed = db.get(Plan, plan_id)
        assert refreshed is not None
        assert refreshed.state == "ENTERED"


def test_paper_exit_tick_closes_time_failure_when_family_hold_window_is_exceeded() -> None:
    init_db()
    _reset_execution_control_state()

    symbol = f"PEXTIME{int(datetime.now(timezone.utc).timestamp() * 1_000_000) + 11}USDC"
    plan_id = f"{symbol}_plan"
    _seed_plan(symbol=symbol, family="sweep_reversal", plan_id=plan_id, state="ENTERED")

    with SessionLocal() as db:
        plan = db.get(Plan, plan_id)
        assert plan is not None
        validity = dict(plan.validity or {})
        validity["strategy_family_time_stop_min_bars"] = 3
        validity["strategy_family_time_stop_max_bars"] = 5
        plan.validity = validity
        db.add(plan)
        db.commit()

    entry_fill_ts = datetime.now(timezone.utc).replace(microsecond=0, second=0)
    candle_ts = entry_fill_ts + timedelta(minutes=31)
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
                submitted_at=entry_fill_ts,
                acknowledged_at=entry_fill_ts,
            )
        )
        db.add(
            ExecutionFill(
                fill_id=f"fill_{symbol}_entry",
                plan_id=plan_id,
                symbol=symbol,
                stage="ENTRY",
                fill_ts=entry_fill_ts,
                price=100.0,
                qty=1.0,
                fee=0.0,
                from_state="ARMED",
                to_state="ENTERED",
                state_changed=True,
                payload={"source": "paper_adapter"},
                strategy_version="v1",
            )
        )
        db.add(
            Candle(
                symbol=symbol,
                timeframe="1m",
                ts=candle_ts,
                o=100.1,
                h=100.4,
                l=99.8,
                c=100.2,
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
        assert payload["closed_events"] >= 1
        assert any(
            action.get("plan_id") == plan_id
            and action.get("stage") == "CLOSED"
            and action.get("exit_reason") == "time_failure"
            for action in payload["actions"]
        )

    with SessionLocal() as db:
        refreshed = db.get(Plan, plan_id)
        assert refreshed is not None
        assert refreshed.state == "CLOSED"
        validity = dict(refreshed.validity or {})
        assert validity["final_exit_reason"] == "time_failure"
        assert int(validity["final_exit_held_bars"]) >= 6


def test_paper_exit_tick_closes_structure_failure_when_fast_guard_stop_hits() -> None:
    init_db()
    _reset_execution_control_state()

    symbol = f"PEXFAST{int(datetime.now(timezone.utc).timestamp() * 1_000_000) + 12}USDC"
    plan_id = f"{symbol}_plan"
    _seed_plan(symbol=symbol, family="sweep_reversal", plan_id=plan_id, state="ENTERED", entry_model="LIMIT")

    with SessionLocal() as db:
        plan = db.get(Plan, plan_id)
        assert plan is not None
        validity = dict(plan.validity or {})
        validity["strategy_fast_failure_enabled"] = True
        validity["strategy_fast_failure_policy"] = "btc_sweep_reversal_limit_initial_guard_stop"
        validity["strategy_fast_failure_max_bars"] = 1
        validity["strategy_fast_failure_stop_r"] = 0.6
        validity["strategy_fast_failure_requires_sl_touch"] = True
        plan.validity = validity
        db.add(plan)
        db.commit()

    entry_fill_ts = datetime.now(timezone.utc).replace(microsecond=0, second=0)
    candle_ts = entry_fill_ts + timedelta(minutes=4)
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
                submitted_at=entry_fill_ts,
                acknowledged_at=entry_fill_ts,
            )
        )
        db.add(
            ExecutionFill(
                fill_id=f"fill_{symbol}_entry",
                plan_id=plan_id,
                symbol=symbol,
                stage="ENTRY",
                fill_ts=entry_fill_ts,
                price=100.0,
                qty=1.0,
                fee=0.0,
                from_state="ARMED",
                to_state="ENTERED",
                state_changed=True,
                payload={"source": "paper_adapter"},
                strategy_version="v1",
            )
        )
        db.add(
            Candle(
                symbol=symbol,
                timeframe="1m",
                ts=candle_ts,
                o=100.0,
                h=100.1,
                l=98.4,
                c=98.8,
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
        assert payload["closed_events"] >= 1
        assert any(
            action.get("plan_id") == plan_id
            and action.get("stage") == "CLOSED"
            and action.get("exit_reason") == "structure_failure"
            for action in payload["actions"]
        )

    with SessionLocal() as db:
        refreshed = db.get(Plan, plan_id)
        assert refreshed is not None
        assert refreshed.state == "CLOSED"
        validity = dict(refreshed.validity or {})
        assert validity["final_exit_reason"] == "structure_failure"
        assert validity["final_exit_price"] == 99.1
        assert validity["final_exit_trigger_detail"]["saved_r_vs_full_stop"] == 0.4
        assert validity["final_exit_trigger_detail"]["requires_sl_touch"] is True


def test_paper_exit_tick_skips_fast_failure_without_original_stop_touch() -> None:
    init_db()
    _reset_execution_control_state()

    symbol = f"PEXFASTSKIP{int(datetime.now(timezone.utc).timestamp() * 1_000_000) + 12}USDC"
    plan_id = f"{symbol}_plan"
    _seed_plan(symbol=symbol, family="sweep_reversal", plan_id=plan_id, state="ENTERED", entry_model="LIMIT")

    with SessionLocal() as db:
        plan = db.get(Plan, plan_id)
        assert plan is not None
        validity = dict(plan.validity or {})
        validity["strategy_fast_failure_enabled"] = True
        validity["strategy_fast_failure_policy"] = "btc_sweep_reversal_limit_initial_guard_stop"
        validity["strategy_fast_failure_max_bars"] = 1
        validity["strategy_fast_failure_stop_r"] = 0.6
        validity["strategy_fast_failure_requires_sl_touch"] = True
        plan.validity = validity
        db.add(plan)
        db.commit()

    entry_fill_ts = datetime.now(timezone.utc).replace(microsecond=0, second=0)
    first_candle_ts = entry_fill_ts + timedelta(minutes=4)
    second_candle_ts = entry_fill_ts + timedelta(minutes=5)
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
                submitted_at=entry_fill_ts,
                acknowledged_at=entry_fill_ts,
            )
        )
        db.add(
            ExecutionFill(
                fill_id=f"fill_{symbol}_entry",
                plan_id=plan_id,
                symbol=symbol,
                stage="ENTRY",
                fill_ts=entry_fill_ts,
                price=100.0,
                qty=1.0,
                fee=0.0,
                from_state="ARMED",
                to_state="ENTERED",
                state_changed=True,
                payload={"source": "paper_adapter"},
                strategy_version="v1",
            )
        )
        db.add(
            Candle(
                symbol=symbol,
                timeframe="1m",
                ts=first_candle_ts,
                o=100.0,
                h=100.4,
                l=99.35,
                c=100.2,
                v=1000.0,
                source="test",
                is_final=True,
            )
        )
        db.add(
            Candle(
                symbol=symbol,
                timeframe="1m",
                ts=second_candle_ts,
                o=100.2,
                h=100.8,
                l=100.1,
                c=100.7,
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
            limit_1m=2,
            limit_5m=1,
        )
        assert not any(
            action.get("plan_id") == plan_id
            and action.get("stage") == "CLOSED"
            and action.get("exit_reason") == "structure_failure"
            for action in payload["actions"]
        )

    with SessionLocal() as db:
        refreshed = db.get(Plan, plan_id)
        assert refreshed is not None
        assert refreshed.state == "ENTERED"


def test_paper_exit_tick_repairs_closed_plan_final_exit_metadata_from_closed_fill_payload() -> None:
    init_db()
    symbol = f"PEXCLOSE{int(datetime.now(timezone.utc).timestamp() * 1_000_000) + 13}USDC"
    plan_id = f"{symbol}_plan"
    _seed_plan(symbol=symbol, family="sweep_reversal", plan_id=plan_id, state="CLOSED")
    closed_ts = datetime.now(timezone.utc).replace(microsecond=0, second=0)

    with SessionLocal() as db:
        plan = db.get(Plan, plan_id)
        assert plan is not None
        validity = dict(plan.validity or {})
        validity.pop("final_exit_ts", None)
        validity.pop("final_exit_realized_r", None)
        validity.pop("final_exit_reason", None)
        validity.pop("final_exit_held_bars", None)
        plan.validity = validity
        plan.valid_from = closed_ts - timedelta(days=45)
        plan.valid_until = closed_ts - timedelta(days=44)
        db.add(plan)
        db.add(
            ExecutionFill(
                fill_id=f"{plan_id}_closed",
                plan_id=plan_id,
                symbol=symbol,
                stage="CLOSED",
                fill_ts=closed_ts,
                price=102.25,
                qty=1.0,
                fee=0.0,
                from_state="PARTIAL_EXIT",
                to_state="CLOSED",
                state_changed=True,
                payload={
                    "source": "paper_adapter",
                    "exit_ts": closed_ts.isoformat(),
                    "realized_r": 1.25,
                    "exit_reason": "target_tp2",
                    "held_bars": 9,
                    "exit_price": 102.25,
                },
                strategy_version="v1",
            )
        )
        db.commit()

    with SessionLocal() as db:
        engine = StrategyEngine(db)
        payload = engine.process_paper_exit_tick(
            families=["sweep_reversal"],
            days=30,
            limit=20,
            sync_candles=False,
            limit_1m=1,
            limit_5m=1,
        )
        assert payload["closed_validity_repairs"] >= 1

    with SessionLocal() as db:
        refreshed = db.get(Plan, plan_id)
        assert refreshed is not None
        validity = dict(refreshed.validity or {})
        assert validity["final_exit_ts"] == closed_ts.isoformat()
        assert validity["final_exit_realized_r"] == 1.25
        assert validity["final_exit_reason"] == "target_tp2"
        assert validity["final_exit_held_bars"] == 9
        assert validity["final_exit_price"] == 102.25


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


def test_plan_upsert_preserves_replaceable_plan_with_execution_fill_artifact() -> None:
    init_db()
    symbol = f"PCOLL{int(datetime.now(timezone.utc).timestamp() * 1_000_000) + 4}USDC"
    plan_id = f"{symbol}_plan"
    _seed_plan(symbol=symbol, family="sweep_reversal", plan_id=plan_id, state="ARMED")

    with SessionLocal() as db:
        db.add(
            ExecutionFill(
                fill_id=f"{plan_id}_entry_fill",
                plan_id=plan_id,
                symbol=symbol,
                stage="ENTRY",
                fill_ts=datetime.now(timezone.utc).replace(microsecond=0),
                price=100.0,
                qty=1.0,
                fee=0.0,
                from_state="ARMED",
                to_state="ENTERED",
                state_changed=True,
                payload={},
                strategy_version="v1",
            )
        )
        db.commit()

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
                    validity={"strategy_family": "legacy_zone_plan"},
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
        assert original.state == "ARMED"
        rows = db.query(Plan).filter(Plan.symbol == symbol).order_by(Plan.valid_from.asc()).all()
        assert len(rows) == 2
        rolled = next(row for row in rows if row.plan_id != plan_id)
        validity = dict(rolled.validity or {})
        assert validity["supersedes_plan_id"] == plan_id
        assert validity["collision_preserved_existing_state"] == "ARMED"
        assert validity["collision_preserved_existing_artifact"] == "execution_fill"


def test_plan_upsert_preserves_replaceable_plan_with_routed_submission_artifact() -> None:
    init_db()
    symbol = f"PCOLL{int(datetime.now(timezone.utc).timestamp() * 1_000_000) + 5}USDC"
    plan_id = f"{symbol}_plan"
    intent_id = f"{plan_id}_intent"
    _seed_plan(symbol=symbol, family="sweep_reversal", plan_id=plan_id, state="ARMED")

    with SessionLocal() as db:
        db.add(
            OrderSubmission(
                submission_id=f"{plan_id}_submission",
                intent_id=intent_id,
                plan_id=plan_id,
                symbol=symbol,
                client_order_id=f"{plan_id}_client",
                exchange_order_id=f"{plan_id}_exchange",
                state=OrderLifecycleState.FILLED.value,
                submit_status="FILLED",
                message="existing routed submission",
                adapter="paper",
                execution_mode=ExecutionMode.PAPER.value,
                side="BUY",
                order_type="LIMIT",
                reduce_only=False,
                requested_live=False,
                attachments={},
                raw={},
                submitted_at=datetime.now(timezone.utc).replace(microsecond=0),
            )
        )
        db.commit()

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
                    validity={"strategy_family": "legacy_zone_plan"},
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
        assert original.state == "ARMED"
        rows = db.query(Plan).filter(Plan.symbol == symbol).order_by(Plan.valid_from.asc()).all()
        assert len(rows) == 2
        rolled = next(row for row in rows if row.plan_id != plan_id)
        validity = dict(rolled.validity or {})
        assert validity["supersedes_plan_id"] == plan_id
        assert validity["collision_preserved_existing_state"] == "ARMED"
        assert validity["collision_preserved_existing_artifact"] == "routed_submission"


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


def test_order_intent_ignores_stale_paper_open_intent_duplicate(monkeypatch) -> None:
    init_db()
    _apply_auto_trading_defaults(monkeypatch)
    settings = get_settings()
    monkeypatch.setattr(settings, "auto_trading_paper_submission_stale_hours", 1)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine.metrics", _good_metrics)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._gate_context_for_symbol", _open_gate_context)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._today_trade_count", lambda self: 0)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._current_exposure_rows", lambda self: [])

    symbol = f"STALEDUPE{int(datetime.now(timezone.utc).timestamp() * 1_000_000) + 11}USDC"
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
                created_at=datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=10),
            )
        )
        db.add(
            OrderSubmission(
                submission_id=f"sub_{symbol}_existing",
                intent_id=f"intent_{symbol}_existing",
                plan_id=existing_plan_id,
                symbol=symbol,
                client_order_id=f"client_{symbol}_existing",
                adapter="paper",
                execution_mode="PAPER",
                state="ACKNOWLEDGED",
                submit_status="ACKNOWLEDGED",
                side="BUY",
                order_type="LIMIT",
                requested_live=False,
                submitted_at=datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=10),
                acknowledged_at=datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=10),
                created_at=datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=10),
                updated_at=datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=10),
            )
        )
        db.commit()

    intent = client.post(
        "/execution/order-intents",
        json={"plan_id": fresh_plan_id, "execution_mode": "PAPER"},
    )
    assert intent.status_code == 200
    intent_payload = intent.json()
    assert intent_payload["submit_decision"] == "SUBMIT"
    assert intent_payload["dedupe_result"]["status"] == "unique"
    self_heal = dict(intent_payload.get("self_heal_summary") or {})
    assert self_heal["stale_paper_duplicate_intents_ignored_count"] >= 1


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


def test_closed_filled_submission_does_not_keep_thesis_open(monkeypatch) -> None:
    init_db()
    _apply_auto_trading_defaults(monkeypatch)
    settings = get_settings()
    monkeypatch.setattr(settings, "auto_trading_execution_mode", ExecutionMode.PAPER)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine.metrics", _good_metrics)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._gate_context_for_symbol", _open_gate_context)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._today_trade_count", lambda self: 0)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._current_exposure_rows", lambda self: [])

    symbol = f"PLCF{int(datetime.now(timezone.utc).timestamp() * 1_000_000) + 131}USDC"
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
        db.add(
            OrderSubmission(
                submission_id=f"sub_{symbol}_existing",
                intent_id=f"intent_{symbol}_existing",
                plan_id=existing_plan_id,
                symbol=symbol,
                client_order_id=f"client_{symbol}_existing",
                adapter="paper",
                execution_mode="PAPER",
                state="FILLED",
                submit_status="FILLED",
                side="BUY",
                order_type="LIMIT",
                requested_live=False,
            )
        )
        db.commit()

    intent = client.post(
        "/execution/order-intents",
        json={"plan_id": fresh_plan_id, "execution_mode": "PAPER"},
    )
    assert intent.status_code == 200
    intent_payload = intent.json()
    assert intent_payload["submit_decision"] == "SUBMIT"
    assert intent_payload["dedupe_result"]["status"] == "unique"


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
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._live_cluster_guard", lambda self, **kwargs: {})

    symbol = f"LIVE{int(datetime.now(timezone.utc).timestamp() * 1_000_000) + 2}USDC"
    plan_id = f"{symbol}_plan"
    _seed_plan(symbol=symbol, family="sweep_reversal", plan_id=plan_id, entry_model="LIMIT")

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


def test_reconcile_route_accepts_hedge_mode_protection_orders_without_reduce_only() -> None:
    init_db()
    symbol = f"RECON{int(datetime.now(timezone.utc).timestamp() * 1_000_000) + 33}USDC"
    plan_id = f"{symbol}_protected"
    _seed_plan(symbol=symbol, family="trend_continuation", plan_id=plan_id, state="ENTERED")

    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        db.add(
            BinancePositionSnapshot(
                position_key=f"{symbol}:LONG",
                symbol=symbol,
                position_side="LONG",
                position_amt=1.0,
                entry_price=100.0,
                break_even_price=100.0,
                mark_price=100.5,
                liquidation_price=80.0,
                unrealized_pnl=0.5,
                notional=100.5,
                leverage=2,
                margin_type="cross",
                isolated_wallet=0.0,
                update_ts=now,
                raw={},
            )
        )
        db.add(
            BinanceOrderLedger(
                client_order_id=f"{symbol}_sl",
                exchange_order_id=223456,
                plan_id=plan_id,
                symbol=symbol,
                side="SELL",
                order_type="STOP_MARKET",
                status="NEW",
                reduce_only=False,
                requested_live=True,
                live_enabled=True,
                test_order=False,
                price=98.5,
                orig_qty=0.0,
                executed_qty=0.0,
                time_in_force="",
                last_event_type="submit",
                last_trade_id=None,
                last_event_ts=now,
                raw={"order_purpose": "live_protection:stop_loss", "close_position": True, "position_side": "LONG"},
            )
        )
        db.add(
            BinanceOrderLedger(
                client_order_id=f"{symbol}_tp1",
                exchange_order_id=223457,
                plan_id=plan_id,
                symbol=symbol,
                side="SELL",
                order_type="LIMIT",
                status="NEW",
                reduce_only=False,
                requested_live=True,
                live_enabled=True,
                test_order=False,
                price=101.5,
                orig_qty=1.0,
                executed_qty=0.0,
                time_in_force="GTC",
                last_event_type="submit",
                last_trade_id=None,
                last_event_ts=now,
                raw={"order_purpose": "live_protection:tp1", "position_side": "LONG"},
            )
        )
        db.commit()

    reconcile = client.post("/execution/reconcile", json={"symbol": symbol})
    assert reconcile.status_code == 200
    payload = reconcile.json()
    mismatch_types = {item["mismatch_type"] for item in payload["mismatches"]}
    assert "MISSING_STOP_ORDER" not in mismatch_types
    assert "MISSING_TP_ORDER" not in mismatch_types
    assert "ORPHAN_ORDER_EXCHANGE" not in mismatch_types
    assert payload["lock_required"] is False


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
    assert state_payload["transition_edge_variant"]["enabled"] is True
    assert state_payload["transition_edge_variant"]["shadow_only"] is True
    assert state_payload["transition_edge_variant"]["killed"] is False
    assert state_payload["transition_edge_variant"]["live_lane"]["counts"]["base"]["intent"] == 0
    assert state_payload["transition_edge_variant"]["live_lane"]["counts"]["variant"]["intent"] == 0

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
    monkeypatch.setattr(settings, "binance_live_position_side_mode", "HEDGE")
    monkeypatch.setattr(settings, "auto_trading_live_sizing_mode", "NOTIONAL_PER_R")
    monkeypatch.setattr(settings, "auto_trading_notional_per_r", 25.0)
    monkeypatch.setattr(settings, "binance_live_min_quantity", 0.001)
    monkeypatch.setattr(settings, "binance_live_quantity_step", 0.001)
    suffix = str(int(datetime.now(timezone.utc).timestamp() * 1_000_000))[-6:]
    symbol = f"LH{suffix}USDC"
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_symbols", symbol)
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_families", "sweep_reversal")
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine.metrics", _good_metrics)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._gate_context_for_symbol", _open_gate_context)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._today_trade_count", lambda self: 0)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._current_exposure_rows", lambda self: [])
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._live_cluster_guard", lambda self, **kwargs: {})

    captured: dict[str, object] = {}

    def _fake_submit(self, **kwargs):
        captured.update(kwargs)
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
    _seed_plan(symbol=symbol, family="sweep_reversal", plan_id=plan_id, entry_model="LIMIT")

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
    assert captured["quantity"] == 0.125
    assert captured["position_side"] == "LONG"
    assert submit_payload["attachments"]["live_position_side"] == "LONG"
    assert submit_payload["attachments"]["live_order_sizing"]["max_position_notional"] == 12.5
    assert submit_payload["attachments"]["live_order_sizing"]["normalized_quantity"] == 0.125


def test_micro_live_filled_submit_attaches_stop_and_take_profit_orders(monkeypatch) -> None:
    init_db()
    _apply_auto_trading_defaults(monkeypatch)
    settings = get_settings()
    monkeypatch.setattr(settings, "binance_trade_live_enabled", True)
    monkeypatch.setattr(settings, "binance_live_position_side_mode", "HEDGE")
    monkeypatch.setattr(settings, "auto_trading_live_sizing_mode", "NOTIONAL_PER_R")
    monkeypatch.setattr(settings, "auto_trading_notional_per_r", 25.0)
    monkeypatch.setattr(settings, "binance_live_min_quantity", 0.001)
    monkeypatch.setattr(settings, "binance_live_quantity_step", 0.001)
    suffix = str(int(datetime.now(timezone.utc).timestamp() * 1_000_000))[-6:]
    symbol = f"PF{suffix}USDC"
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_symbols", symbol)
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_families", "sweep_reversal")
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine.metrics", _good_metrics)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._gate_context_for_symbol", _open_gate_context)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._today_trade_count", lambda self: 0)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._current_exposure_rows", lambda self: [])
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._live_cluster_guard", lambda self, **kwargs: {})

    calls: list[dict[str, object]] = []

    def _fake_submit(self, **kwargs):
        calls.append(dict(kwargs))
        is_entry = len(calls) == 1
        return {
            "symbol": kwargs["symbol"],
            "plan_id": kwargs["plan_id"],
            "order_id": 990000 + len(calls),
            "client_order_id": kwargs["client_order_id"],
            "status": "FILLED" if is_entry else "NEW",
            "side": kwargs["side"],
            "order_type": kwargs["order_type"],
            "reduce_only": kwargs["reduce_only"],
            "position_side": kwargs.get("position_side") or "",
            "executed_qty": kwargs["quantity"] if is_entry else 0.0,
            "avg_price": 100.0 if is_entry else 0.0,
            "raw": {
                "orderId": str(990000 + len(calls)),
                "executedQty": str(kwargs["quantity"] if is_entry else 0.0),
                "avgPrice": "100.0" if is_entry else "0",
            },
        }

    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine.submit_binance_order", _fake_submit)

    plan_id = f"{symbol}_protect_{suffix}"
    _seed_plan(symbol=symbol, family="sweep_reversal", plan_id=plan_id, entry_model="CONFIRM")

    intent = client.post(
        "/execution/order-intents",
        json={"plan_id": plan_id, "execution_mode": "MICRO_LIVE"},
    )
    assert intent.status_code == 200
    intent_payload = intent.json()

    submit = client.post(
        "/execution/submit",
        json={"intent_id": intent_payload["intent_id"], "live": True},
    )
    assert submit.status_code == 200
    payload = submit.json()
    assert payload["state"] == "FILLED"
    assert payload["attachments"]["immediate_fill_ingested"] is True
    assert payload["attachments"]["live_protection_orders"]["status"] == "ATTACHED"

    assert len(calls) == 5
    entry, stop, tp1, tp2, tp3 = calls
    assert entry["order_type"] == "MARKET"
    assert entry["side"] == "BUY"
    assert entry["position_side"] == "LONG"
    assert stop["order_type"] == "STOP_MARKET"
    assert stop["side"] == "SELL"
    assert stop["stop_price"] == 98.5
    assert stop["close_position"] is True
    assert stop["quantity"] is None
    assert stop["position_side"] == "LONG"
    assert stop["working_type"] == "MARK_PRICE"
    assert [tp1["order_type"], tp2["order_type"], tp3["order_type"]] == ["LIMIT", "LIMIT", "LIMIT"]
    assert [tp1["price"], tp2["price"], tp3["price"]] == [101.0, 102.0, 103.0]
    assert [tp1["quantity"], tp2["quantity"], tp3["quantity"]] == [0.075, 0.031, 0.018]
    assert [tp1["reduce_only"], tp2["reduce_only"], tp3["reduce_only"]] == [False, False, False]


def test_micro_live_submit_malformed_live_submitter_response_requires_reconciliation(monkeypatch) -> None:
    init_db()
    _apply_auto_trading_defaults(monkeypatch)
    settings = get_settings()
    monkeypatch.setattr(settings, "binance_trade_live_enabled", True)
    monkeypatch.setattr(settings, "auto_trading_live_sizing_mode", "NOTIONAL_PER_R")
    monkeypatch.setattr(settings, "auto_trading_notional_per_r", 25.0)
    monkeypatch.setattr(settings, "binance_live_min_quantity", 0.001)
    monkeypatch.setattr(settings, "binance_live_quantity_step", 0.001)
    suffix = str(int(datetime.now(timezone.utc).timestamp() * 1_000_000))[-6:]
    symbol = f"LR{suffix}USDC"
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_symbols", symbol)
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_families", "sweep_reversal")
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine.metrics", _good_metrics)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._gate_context_for_symbol", _open_gate_context)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._today_trade_count", lambda self: 0)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._current_exposure_rows", lambda self: [])
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._live_cluster_guard", lambda self, **kwargs: {})
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine.submit_binance_order", lambda self, **kwargs: ["bad-response"])

    plan_id = f"{symbol}_malformed_live_result_{suffix}"
    _seed_plan(symbol=symbol, family="sweep_reversal", plan_id=plan_id, entry_model="LIMIT")

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
    assert submit_payload["state"] == "SUBMITTED"
    assert submit_payload["submit_status"] == "LIVE_SUBMIT_ERROR"
    assert submit_payload["attachments"]["requires_reconciliation"] is True
    assert submit_payload["attachments"]["live_submit_error"]["message"] == "live_submitter_malformed_response:list"


def test_micro_live_submit_uses_defaults_when_symbol_rules_are_malformed(monkeypatch) -> None:
    init_db()
    _apply_auto_trading_defaults(monkeypatch)
    settings = get_settings()
    monkeypatch.setattr(settings, "binance_trade_live_enabled", True)
    monkeypatch.setattr(settings, "auto_trading_live_sizing_mode", "NOTIONAL_PER_R")
    monkeypatch.setattr(settings, "auto_trading_notional_per_r", 25.0)
    monkeypatch.setattr(settings, "binance_live_min_quantity", 0.001)
    monkeypatch.setattr(settings, "binance_live_quantity_step", 0.001)
    suffix = str(int(datetime.now(timezone.utc).timestamp() * 1_000_000))[-6:]
    symbol = f"MF{suffix}USDC"
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_symbols", symbol)
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_families", "sweep_reversal")
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine.metrics", _good_metrics)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._gate_context_for_symbol", _open_gate_context)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._today_trade_count", lambda self: 0)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._current_exposure_rows", lambda self: [])
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._live_cluster_guard", lambda self, **kwargs: {})
    monkeypatch.setattr(
        "app.services.strategy_engine.StrategyEngine.load_binance_symbol_trading_rules",
        lambda self, requested_symbol: {
            "symbol": requested_symbol,
            "quantity_step": "bad-step",
            "min_quantity": "bad-min",
            "tick_size": "bad-tick",
            "source": "binance_exchange_info",
        },
    )

    captured: dict[str, object] = {}

    def _fake_submit(self, **kwargs):
        captured.update(kwargs)
        return {
            "symbol": kwargs["symbol"],
            "plan_id": kwargs["plan_id"],
            "order_id": 987661,
            "client_order_id": kwargs["client_order_id"],
            "status": "NEW",
            "side": kwargs["side"],
            "order_type": kwargs["order_type"],
            "reduce_only": kwargs["reduce_only"],
        }

    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine.submit_binance_order", _fake_submit)

    plan_id = f"{symbol}_malformed_rules_{suffix}"
    _seed_plan(symbol=symbol, family="sweep_reversal", plan_id=plan_id, entry_model="LIMIT")

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
    assert submit_payload["state"] == "ACKNOWLEDGED"
    assert captured["quantity"] == 0.125
    sizing = submit_payload["attachments"]["live_order_sizing"]
    assert sizing["quantity_step"] == 0.001
    assert sizing["min_quantity"] == 0.001


def test_micro_live_submit_rejects_malformed_reference_price_without_500(monkeypatch) -> None:
    init_db()
    _apply_auto_trading_defaults(monkeypatch)
    settings = get_settings()
    monkeypatch.setattr(settings, "binance_trade_live_enabled", True)
    monkeypatch.setattr(settings, "auto_trading_live_sizing_mode", "NOTIONAL_PER_R")
    monkeypatch.setattr(settings, "auto_trading_notional_per_r", 25.0)
    suffix = str(int(datetime.now(timezone.utc).timestamp() * 1_000_000))[-6:]
    symbol = f"MR{suffix}USDC"
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_symbols", symbol)
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_families", "sweep_reversal")
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine.metrics", _good_metrics)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._gate_context_for_symbol", _open_gate_context)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._today_trade_count", lambda self: 0)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._current_exposure_rows", lambda self: [])
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._live_cluster_guard", lambda self, **kwargs: {})

    def _unexpected_submit(self, **kwargs):
        raise AssertionError("live submitter should not be called when reference price is malformed")

    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine.submit_binance_order", _unexpected_submit)

    plan_id = f"{symbol}_bad_ref_{suffix}"
    _seed_plan(symbol=symbol, family="sweep_reversal", plan_id=plan_id, entry_model="LIMIT")

    intent = client.post(
        "/execution/order-intents",
        json={"plan_id": plan_id, "execution_mode": "MICRO_LIVE"},
    )
    assert intent.status_code == 200
    intent_payload = intent.json()

    with SessionLocal() as db:
        intent_row = OrderIntentRepository(db).get(intent_payload["intent_id"])
        assert intent_row is not None
        payload = dict(intent_row.payload or {})
        executable_plan = dict(payload.get("executable_plan") or {})
        executable_plan["entry_limit_price"] = "not-a-number"
        payload["executable_plan"] = executable_plan
        intent_row.payload = payload
        db.add(intent_row)
        db.commit()

    submit = client.post(
        "/execution/submit",
        json={"intent_id": intent_payload["intent_id"], "live": True},
    )
    assert submit.status_code == 200
    submit_payload = submit.json()
    assert submit_payload["state"] == "REJECTED"
    assert submit_payload["submit_status"] == "LIVE_SIZING_INVALID"
    assert "positive reference price" in submit_payload["message"]


def test_micro_live_submit_runs_liquidity_gate_when_enabled(monkeypatch) -> None:
    init_db()
    _apply_auto_trading_defaults(monkeypatch)
    settings = get_settings()
    monkeypatch.setattr(settings, "binance_trade_live_enabled", True)
    monkeypatch.setattr(settings, "auto_trading_live_liquidity_gate_enabled", True)
    monkeypatch.setattr(settings, "auto_trading_live_sizing_mode", "NOTIONAL_PER_R")
    monkeypatch.setattr(settings, "auto_trading_notional_per_r", 25.0)
    suffix = str(int(datetime.now(timezone.utc).timestamp() * 1_000_000))[-6:]
    symbol = f"LG{suffix}USDC"
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_symbols", symbol)
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_families", "sweep_reversal")
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine.metrics", _good_metrics)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._gate_context_for_symbol", _open_gate_context)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._today_trade_count", lambda self: 0)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._current_exposure_rows", lambda self: [])
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._live_cluster_guard", lambda self, **kwargs: {})
    monkeypatch.setattr(
        "app.services.strategy_engine.StrategyEngine.load_binance_live_liquidity_snapshot",
        lambda self, **kwargs: {
            "source": "test_liquidity",
            "symbol": kwargs["symbol"],
            "order_notional": 12.5,
            "spread_bps": 1.0,
            "opposite_depth_notional": 100_000.0,
            "market_slippage_bps": 0.5,
            "recent_1m_quote_volume": 50_000.0,
            "recent_5m_quote_volume": 250_000.0,
        },
    )

    captured: dict[str, object] = {}

    def _fake_submit(self, **kwargs):
        captured.update(kwargs)
        return {
            "symbol": kwargs["symbol"],
            "plan_id": kwargs["plan_id"],
            "order_id": 987658,
            "client_order_id": kwargs["client_order_id"],
            "status": "NEW",
            "side": kwargs["side"],
            "order_type": kwargs["order_type"],
            "reduce_only": kwargs["reduce_only"],
        }

    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine.submit_binance_order", _fake_submit)

    plan_id = f"{symbol}_liq_pass_{suffix}"
    _seed_plan(symbol=symbol, family="sweep_reversal", plan_id=plan_id, entry_model="LIMIT")

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
    assert submit_payload["state"] == "ACKNOWLEDGED"
    assert captured["quantity"] == 0.125
    assert submit_payload["attachments"]["live_liquidity_gate"]["decision"] == "PASS"
    assert submit_payload["attachments"]["live_order_sizing"]["liquidity_gate_decision"] == "PASS"


def test_live_liquidity_snapshot_ignores_open_rest_kline(monkeypatch) -> None:
    init_db()
    _apply_auto_trading_defaults(monkeypatch)
    now = datetime.now(timezone.utc)

    class _FakeBinance:
        def fetch_order_book(self, *, symbol: str, limit: int) -> dict:
            return {
                "bids": [["99.9", "100"]],
                "asks": [["100.1", "100"]],
            }

        def fetch_klines(self, *, symbol: str, interval: str, limit: int):
            return [
                SimpleNamespace(c=100.0, v=10.0, close_time=now - timedelta(minutes=5)),
                SimpleNamespace(c=100.0, v=20.0, close_time=now - timedelta(minutes=4)),
                SimpleNamespace(c=100.0, v=30.0, close_time=now - timedelta(minutes=3)),
                SimpleNamespace(c=100.0, v=40.0, close_time=now - timedelta(minutes=2)),
                SimpleNamespace(c=100.0, v=50.0, close_time=now - timedelta(minutes=1)),
                SimpleNamespace(c=100.0, v=0.01, close_time=now + timedelta(seconds=45)),
            ]

    with SessionLocal() as db:
        engine = StrategyEngine(db)
        engine.market_data.binance = _FakeBinance()
        snapshot = engine.load_binance_live_liquidity_snapshot(
            symbol="BTCUSDC",
            side="BUY",
            order_type="MARKET",
            quantity=1.0,
            reference_price=100.0,
        )

    assert snapshot["recent_1m_quote_volume"] == 5000.0
    assert snapshot["recent_5m_quote_volume"] == 15000.0


def test_micro_live_submit_blocks_thin_liquidity_before_binance_submit(monkeypatch) -> None:
    init_db()
    _apply_auto_trading_defaults(monkeypatch)
    settings = get_settings()
    monkeypatch.setattr(settings, "binance_trade_live_enabled", True)
    monkeypatch.setattr(settings, "auto_trading_live_liquidity_gate_enabled", True)
    monkeypatch.setattr(settings, "auto_trading_live_sizing_mode", "NOTIONAL_PER_R")
    monkeypatch.setattr(settings, "auto_trading_notional_per_r", 25.0)
    suffix = str(int(datetime.now(timezone.utc).timestamp() * 1_000_000))[-6:]
    symbol = f"LB{suffix}USDC"
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_symbols", symbol)
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_families", "sweep_reversal")
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine.metrics", _good_metrics)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._gate_context_for_symbol", _open_gate_context)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._today_trade_count", lambda self: 0)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._current_exposure_rows", lambda self: [])
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._live_cluster_guard", lambda self, **kwargs: {})
    monkeypatch.setattr(
        "app.services.strategy_engine.StrategyEngine.load_binance_live_liquidity_snapshot",
        lambda self, **kwargs: {
            "source": "test_liquidity",
            "symbol": kwargs["symbol"],
            "order_notional": 12.5,
            "spread_bps": 1.0,
            "opposite_depth_notional": 1_000.0,
            "market_slippage_bps": 0.5,
            "recent_1m_quote_volume": 50_000.0,
            "recent_5m_quote_volume": 250_000.0,
        },
    )

    def _unexpected_submit(self, **kwargs):
        raise AssertionError("live submitter should not be called when liquidity gate blocks")

    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine.submit_binance_order", _unexpected_submit)

    plan_id = f"{symbol}_liq_block_{suffix}"
    _seed_plan(symbol=symbol, family="sweep_reversal", plan_id=plan_id, entry_model="LIMIT")

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
    assert submit_payload["submit_status"] == "LIVE_LIQUIDITY_BLOCKED"
    gate = submit_payload["attachments"]["live_liquidity_gate"]
    assert gate["decision"] == "BLOCK"
    assert "visible_depth_below_floor" in gate["reason_codes"]


def test_micro_live_submit_routes_partial_tranche_when_liquidity_size_is_too_large(monkeypatch) -> None:
    init_db()
    _apply_auto_trading_defaults(monkeypatch)
    settings = get_settings()
    monkeypatch.setattr(settings, "binance_trade_live_enabled", True)
    monkeypatch.setattr(settings, "auto_trading_live_liquidity_gate_enabled", True)
    monkeypatch.setattr(settings, "auto_trading_live_liquidity_gate_partial_submit_enabled", True)
    monkeypatch.setattr(settings, "auto_trading_live_liquidity_gate_min_depth_usdt", 0.0)
    monkeypatch.setattr(settings, "auto_trading_live_sizing_mode", "NOTIONAL_PER_R")
    monkeypatch.setattr(settings, "auto_trading_notional_per_r", 2500.0)
    suffix = str(int(datetime.now(timezone.utc).timestamp() * 1_000_000))[-6:]
    symbol = f"LP{suffix}USDC"
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_symbols", symbol)
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_families", "sweep_reversal")
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine.metrics", _good_metrics)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._gate_context_for_symbol", _open_gate_context)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._today_trade_count", lambda self: 0)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._current_exposure_rows", lambda self: [])
    monkeypatch.setattr(
        "app.services.strategy_engine.StrategyEngine.load_binance_live_liquidity_snapshot",
        lambda self, **kwargs: {
            "source": "test_liquidity",
            "symbol": kwargs["symbol"],
            "spread_bps": 1.0,
            "opposite_depth_notional": 1_000.0,
            "market_slippage_bps": 0.5,
            "recent_1m_quote_volume": 1_000_000.0,
            "recent_5m_quote_volume": 5_000_000.0,
        },
    )

    captured: dict[str, object] = {}

    def _fake_submit(self, **kwargs):
        captured.update(kwargs)
        return {
            "symbol": kwargs["symbol"],
            "plan_id": kwargs["plan_id"],
            "order_id": 987659,
            "client_order_id": kwargs["client_order_id"],
            "status": "NEW",
            "side": kwargs["side"],
            "order_type": kwargs["order_type"],
            "reduce_only": kwargs["reduce_only"],
        }

    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine.submit_binance_order", _fake_submit)

    plan_id = f"{symbol}_liq_partial_{suffix}"
    _seed_plan(symbol=symbol, family="sweep_reversal", plan_id=plan_id, entry_model="LIMIT")

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
    assert submit_payload["state"] == "ACKNOWLEDGED"
    assert captured["quantity"] == 1.0
    sizing = submit_payload["attachments"]["live_order_sizing"]
    assert sizing["liquidity_gate_decision"] == "SPLIT_PARTIAL_SUBMIT"
    assert sizing["original_max_position_notional"] == 1250.0
    assert sizing["max_position_notional"] == 100.0
    tranche = submit_payload["attachments"]["live_tranche"]
    assert tranche["tranche_index"] == 1
    assert tranche["submitted_notional"] == 100.0
    assert tranche["remaining_notional"] == 1150.0
    assert tranche["additive_allowed"] is True


def test_micro_live_submit_allows_next_signal_to_fill_remaining_tranche(monkeypatch) -> None:
    init_db()
    _apply_auto_trading_defaults(monkeypatch)
    settings = get_settings()
    monkeypatch.setattr(settings, "binance_trade_live_enabled", True)
    monkeypatch.setattr(settings, "auto_trading_live_liquidity_gate_enabled", True)
    monkeypatch.setattr(settings, "auto_trading_live_liquidity_gate_partial_submit_enabled", True)
    monkeypatch.setattr(settings, "auto_trading_live_liquidity_gate_min_depth_usdt", 0.0)
    monkeypatch.setattr(settings, "auto_trading_live_sizing_mode", "NOTIONAL_PER_R")
    monkeypatch.setattr(settings, "auto_trading_notional_per_r", 2500.0)
    suffix = str(int(datetime.now(timezone.utc).timestamp() * 1_000_000))[-6:]
    symbol = f"LT{suffix}USDC"
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_symbols", symbol)
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_families", "sweep_reversal")
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine.metrics", _good_metrics)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._gate_context_for_symbol", _open_gate_context)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._today_trade_count", lambda self: 0)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._live_cluster_guard", lambda self, **kwargs: {})
    monkeypatch.setattr(
        "app.services.strategy_engine.StrategyEngine.load_binance_live_liquidity_snapshot",
        lambda self, **kwargs: {
            "source": "test_liquidity",
            "symbol": kwargs["symbol"],
            "spread_bps": 1.0,
            "opposite_depth_notional": 1_000.0 if kwargs["quantity"] > 12.0 else 100_000.0,
            "market_slippage_bps": 0.5,
            "recent_1m_quote_volume": 1_000_000.0,
            "recent_5m_quote_volume": 5_000_000.0,
        },
    )

    shared_thesis = {
        "direction": "long",
        "regime": "trend",
        "strategy_family": "sweep_reversal",
        "liquidity_narrative": "session_low_sweep",
        "event_classification": "rejection_confirmed",
        "time_bucket": "2026-05-08T16:00Z",
        "correlation_cluster": "test_cluster",
    }
    first_plan_id = f"{symbol}_first_{suffix}"
    second_plan_id = f"{symbol}_second_{suffix}"
    _seed_plan(symbol=symbol, family="sweep_reversal", plan_id=first_plan_id, entry_model="LIMIT", thesis_fingerprint=shared_thesis)

    def _exposures(self):
        with SessionLocal() as db:
            rows = []
            for plan_id in (first_plan_id, second_plan_id):
                row = db.get(Plan, plan_id)
                if row is not None:
                    rows.append(row)
            return rows

    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._current_exposure_rows", _exposures)

    submitted_quantities: list[float] = []

    def _fake_submit(self, **kwargs):
        submitted_quantities.append(float(kwargs["quantity"]))
        return {
            "symbol": kwargs["symbol"],
            "plan_id": kwargs["plan_id"],
            "order_id": 987660 + len(submitted_quantities),
            "client_order_id": kwargs["client_order_id"],
            "status": "FILLED" if len(submitted_quantities) == 1 else "NEW",
            "side": kwargs["side"],
            "order_type": kwargs["order_type"],
            "reduce_only": kwargs["reduce_only"],
        }

    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine.submit_binance_order", _fake_submit)

    first_intent = client.post(
        "/execution/order-intents",
        json={"plan_id": first_plan_id, "execution_mode": "MICRO_LIVE"},
    )
    assert first_intent.status_code == 200
    first_intent_payload = first_intent.json()
    assert first_intent_payload["submit_decision"] == "SUBMIT"

    first_submit = client.post(
        "/execution/submit",
        json={"intent_id": first_intent_payload["intent_id"], "live": True},
    )
    assert first_submit.status_code == 200
    assert first_submit.json()["attachments"]["live_tranche"]["remaining_notional"] == 1150.0

    _seed_plan(symbol=symbol, family="sweep_reversal", plan_id=second_plan_id, entry_model="LIMIT", thesis_fingerprint=shared_thesis)

    second_intent = client.post(
        "/execution/order-intents",
        json={"plan_id": second_plan_id, "execution_mode": "MICRO_LIVE"},
    )
    assert second_intent.status_code == 200
    second_intent_payload = second_intent.json()
    assert second_intent_payload["submit_decision"] == "SUBMIT"
    assert second_intent_payload["dedupe_result"]["status"] == "tranche_continuation_available"

    second_submit = client.post(
        "/execution/submit",
        json={"intent_id": second_intent_payload["intent_id"], "live": True},
    )
    assert second_submit.status_code == 200
    assert submitted_quantities == [1.0, 11.5]
    second_sizing = second_submit.json()["attachments"]["live_order_sizing"]
    assert second_sizing["liquidity_tranche_continuation"]["remaining_notional_before"] == 1150.0
    assert second_sizing["max_position_notional"] == 1150.0


def test_micro_live_submit_blocks_when_notional_implies_sub_minimum_quantity(monkeypatch) -> None:
    init_db()
    _apply_auto_trading_defaults(monkeypatch)
    settings = get_settings()
    monkeypatch.setattr(settings, "binance_trade_live_enabled", True)
    monkeypatch.setattr(settings, "auto_trading_live_sizing_mode", "NOTIONAL_PER_R")
    monkeypatch.setattr(settings, "auto_trading_notional_per_r", 0.1)
    monkeypatch.setattr(settings, "binance_live_min_quantity", 0.001)
    monkeypatch.setattr(settings, "binance_live_quantity_step", 0.001)
    suffix = str(int(datetime.now(timezone.utc).timestamp() * 1_000_000))[-6:]
    symbol = f"LS{suffix}USDC"
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_symbols", symbol)
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_families", "sweep_reversal")
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine.metrics", _good_metrics)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._gate_context_for_symbol", _open_gate_context)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._today_trade_count", lambda self: 0)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._current_exposure_rows", lambda self: [])
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._live_cluster_guard", lambda self, **kwargs: {})

    def _unexpected_submit(self, **kwargs):
        raise AssertionError("live submitter should not be called when quantity is below minimum")

    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine.submit_binance_order", _unexpected_submit)

    plan_id = f"{symbol}_ml_{suffix}"
    _seed_plan(symbol=symbol, family="sweep_reversal", plan_id=plan_id, entry_model="LIMIT")

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
    assert submit_payload["submit_status"] == "LIVE_SIZING_INVALID"
    assert "below the configured minimum" in submit_payload["message"]
    assert submit_payload["attachments"]["live_order_sizing"]["normalized_quantity"] == 0.0


def test_micro_live_submit_uses_risk_pct_sizing_and_caps_by_leverage(monkeypatch) -> None:
    init_db()
    _apply_auto_trading_defaults(monkeypatch)
    settings = get_settings()
    monkeypatch.setattr(settings, "binance_trade_live_enabled", True)
    monkeypatch.setattr(settings, "auto_trading_live_sizing_mode", "RISK_PCT")
    monkeypatch.setattr(settings, "auto_trading_live_account_equity_usdt", 200.0)
    monkeypatch.setattr(settings, "auto_trading_live_risk_per_trade_pct", 0.005)
    monkeypatch.setattr(settings, "auto_trading_live_usable_margin_fraction", 0.85)
    monkeypatch.setattr(settings, "auto_trading_live_leverage_cap", 6.0)
    monkeypatch.setattr(settings, "binance_live_min_quantity", 0.001)
    monkeypatch.setattr(settings, "binance_live_quantity_step", 0.001)
    suffix = str(int(datetime.now(timezone.utc).timestamp() * 1_000_000))[-6:]
    symbol = f"LR{suffix}USDC"
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_symbols", symbol)
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_families", "sweep_reversal")
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine.metrics", _good_metrics)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._gate_context_for_symbol", _open_gate_context)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._today_trade_count", lambda self: 0)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._current_exposure_rows", lambda self: [])
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._live_cluster_guard", lambda self, **kwargs: {})

    captured: dict[str, object] = {}

    def _fake_submit(self, **kwargs):
        captured.update(kwargs)
        return {
            "symbol": kwargs["symbol"],
            "plan_id": kwargs["plan_id"],
            "order_id": 987655,
            "client_order_id": kwargs["client_order_id"],
            "status": "NEW",
            "side": kwargs["side"],
            "order_type": kwargs["order_type"],
            "reduce_only": kwargs["reduce_only"],
        }

    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine.submit_binance_order", _fake_submit)

    plan_id = f"{symbol}_risk_{suffix}"
    _seed_plan(symbol=symbol, family="sweep_reversal", plan_id=plan_id, entry_model="LIMIT")

    with SessionLocal() as db:
        plan = db.get(Plan, plan_id)
        assert plan is not None
        plan.sl = 99.9
        db.add(plan)
        db.commit()

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
    assert captured["quantity"] == 10.0
    sizing = submit_payload["attachments"]["live_order_sizing"]
    assert sizing["sizing_mode"] == "RISK_PCT"
    assert sizing["target_notional"] == 1000.0
    assert sizing["max_position_notional"] == 1000.0
    assert sizing["required_leverage"] == 5.8824
    assert sizing["leverage_cap"] == 6.0
    assert sizing["leverage_capped"] is False
    assert sizing["actual_risk_usdt"] == 1.0


def test_micro_live_submit_uses_synced_available_balance_for_risk_pct_sizing(monkeypatch) -> None:
    init_db()
    _apply_auto_trading_defaults(monkeypatch)
    settings = get_settings()
    monkeypatch.setattr(settings, "binance_trade_live_enabled", True)
    monkeypatch.setattr(settings, "auto_trading_live_sizing_mode", "RISK_PCT")
    monkeypatch.setattr(settings, "auto_trading_live_account_equity_usdt", 200.0)
    monkeypatch.setattr(settings, "auto_trading_live_balance_sync_enabled", True)
    monkeypatch.setattr(settings, "auto_trading_live_balance_sync_assets", "USDC,USDT")
    monkeypatch.setattr(settings, "auto_trading_live_balance_sync_fail_closed", True)
    monkeypatch.setattr(settings, "auto_trading_live_risk_per_trade_pct", 0.005)
    monkeypatch.setattr(settings, "auto_trading_live_usable_margin_fraction", 0.85)
    monkeypatch.setattr(settings, "auto_trading_live_leverage_cap", 6.0)
    monkeypatch.setattr(settings, "binance_live_min_quantity", 0.001)
    monkeypatch.setattr(settings, "binance_live_quantity_step", 0.001)
    suffix = str(int(datetime.now(timezone.utc).timestamp() * 1_000_000))[-6:]
    symbol = f"LB{suffix}USDC"
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_symbols", symbol)
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_families", "sweep_reversal")
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine.metrics", _good_metrics)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._gate_context_for_symbol", _open_gate_context)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._today_trade_count", lambda self: 0)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._current_exposure_rows", lambda self: [])
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._live_cluster_guard", lambda self, **kwargs: {})
    monkeypatch.setattr(
        "app.services.strategy_engine.StrategyEngine.load_binance_futures_balances",
        lambda self: {
            "source": "test_balance",
            "balances": [
                {"asset": "USDT", "availableBalance": "999.0", "balance": "999.0"},
                {"asset": "USDC", "availableBalance": "170.0", "balance": "170.0"},
            ],
        },
    )

    captured: dict[str, object] = {}

    def _fake_submit(self, **kwargs):
        captured.update(kwargs)
        return {
            "symbol": kwargs["symbol"],
            "plan_id": kwargs["plan_id"],
            "order_id": 987665,
            "client_order_id": kwargs["client_order_id"],
            "status": "NEW",
            "side": kwargs["side"],
            "order_type": kwargs["order_type"],
            "reduce_only": kwargs["reduce_only"],
        }

    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine.submit_binance_order", _fake_submit)

    plan_id = f"{symbol}_balance_{suffix}"
    _seed_plan(symbol=symbol, family="sweep_reversal", plan_id=plan_id, entry_model="LIMIT")

    with SessionLocal() as db:
        plan = db.get(Plan, plan_id)
        assert plan is not None
        plan.sl = 99.9
        db.add(plan)
        db.commit()

    intent = client.post(
        "/execution/order-intents",
        json={"plan_id": plan_id, "execution_mode": "MICRO_LIVE"},
    )
    assert intent.status_code == 200

    submit = client.post(
        "/execution/submit",
        json={"intent_id": intent.json()["intent_id"], "live": True},
    )
    assert submit.status_code == 200
    submit_payload = submit.json()
    assert submit_payload["state"] == "ACKNOWLEDGED"
    assert captured["quantity"] == 8.5
    sizing = submit_payload["attachments"]["live_order_sizing"]
    assert sizing["account_equity_usdt"] == 170.0
    assert sizing["configured_account_equity_usdt"] == 200.0
    assert sizing["account_equity_source"] == "binance_futures_available_balance"
    assert sizing["balance_asset"] == "USDC"
    assert sizing["target_notional"] == 850.0
    assert sizing["actual_risk_usdt"] == 0.85


def test_micro_live_submit_uses_symbol_specific_quantity_filters(monkeypatch) -> None:
    init_db()
    _apply_auto_trading_defaults(monkeypatch)
    settings = get_settings()
    monkeypatch.setattr(settings, "binance_trade_live_enabled", True)
    monkeypatch.setattr(settings, "auto_trading_live_sizing_mode", "NOTIONAL_PER_R")
    monkeypatch.setattr(settings, "auto_trading_notional_per_r", 25.0)
    monkeypatch.setattr(settings, "binance_live_min_quantity", 0.001)
    monkeypatch.setattr(settings, "binance_live_quantity_step", 0.001)
    suffix = str(int(datetime.now(timezone.utc).timestamp() * 1_000_000))[-6:]
    symbol = f"XQ{suffix}USDC"
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_symbols", symbol)
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_families", "sweep_reversal")
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine.metrics", _good_metrics)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._gate_context_for_symbol", _open_gate_context)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._today_trade_count", lambda self: 0)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._current_exposure_rows", lambda self: [])
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._live_cluster_guard", lambda self, **kwargs: {})
    monkeypatch.setattr(
        "app.services.strategy_engine.StrategyEngine.load_binance_symbol_trading_rules",
        lambda self, requested_symbol: {
            "symbol": requested_symbol,
            "quantity_step": 0.1,
            "min_quantity": 0.1,
            "source": "binance_exchange_info",
        },
    )

    captured: dict[str, object] = {}

    def _fake_submit(self, **kwargs):
        captured.update(kwargs)
        return {
            "symbol": kwargs["symbol"],
            "plan_id": kwargs["plan_id"],
            "order_id": 987656,
            "client_order_id": kwargs["client_order_id"],
            "status": "NEW",
            "side": kwargs["side"],
            "order_type": kwargs["order_type"],
            "reduce_only": kwargs["reduce_only"],
        }

    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine.submit_binance_order", _fake_submit)

    plan_id = f"{symbol}_filters_{suffix}"
    _seed_plan(symbol=symbol, family="sweep_reversal", plan_id=plan_id, entry_model="LIMIT")

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
    assert submit_payload["state"] == "ACKNOWLEDGED"
    assert captured["quantity"] == 0.1
    sizing = submit_payload["attachments"]["live_order_sizing"]
    assert sizing["symbol_rules_source"] == "binance_exchange_info"
    assert sizing["quantity_step"] == 0.1
    assert sizing["min_quantity"] == 0.1
    assert sizing["normalized_quantity"] == 0.1


def test_micro_live_submit_rejects_when_symbol_specific_min_quantity_not_met(monkeypatch) -> None:
    init_db()
    _apply_auto_trading_defaults(monkeypatch)
    settings = get_settings()
    monkeypatch.setattr(settings, "binance_trade_live_enabled", True)
    monkeypatch.setattr(settings, "auto_trading_live_sizing_mode", "NOTIONAL_PER_R")
    monkeypatch.setattr(settings, "auto_trading_notional_per_r", 25.0)
    monkeypatch.setattr(settings, "binance_live_min_quantity", 0.001)
    monkeypatch.setattr(settings, "binance_live_quantity_step", 0.001)
    suffix = str(int(datetime.now(timezone.utc).timestamp() * 1_000_000))[-6:]
    symbol = f"AQ{suffix}USDC"
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_symbols", symbol)
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_families", "sweep_reversal")
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine.metrics", _good_metrics)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._gate_context_for_symbol", _open_gate_context)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._today_trade_count", lambda self: 0)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._current_exposure_rows", lambda self: [])
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._live_cluster_guard", lambda self, **kwargs: {})
    monkeypatch.setattr(
        "app.services.strategy_engine.StrategyEngine.load_binance_symbol_trading_rules",
        lambda self, requested_symbol: {
            "symbol": requested_symbol,
            "quantity_step": 1.0,
            "min_quantity": 1.0,
            "source": "binance_exchange_info",
        },
    )

    def _unexpected_submit(self, **kwargs):
        raise AssertionError("live submitter should not be called when symbol min quantity is not met")

    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine.submit_binance_order", _unexpected_submit)

    plan_id = f"{symbol}_filters_{suffix}"
    _seed_plan(symbol=symbol, family="sweep_reversal", plan_id=plan_id, entry_model="LIMIT")

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
    assert submit_payload["submit_status"] == "LIVE_SIZING_INVALID"
    assert "below the configured minimum" in submit_payload["message"]
    sizing = submit_payload["attachments"]["live_order_sizing"]
    assert sizing["symbol_rules_source"] == "binance_exchange_info"
    assert sizing["quantity_step"] == 1.0
    assert sizing["min_quantity"] == 1.0
    assert sizing["normalized_quantity"] == 0.0


def test_micro_live_submit_normalizes_limit_price_by_symbol_tick_size(monkeypatch) -> None:
    init_db()
    _apply_auto_trading_defaults(monkeypatch)
    settings = get_settings()
    monkeypatch.setattr(settings, "binance_trade_live_enabled", True)
    monkeypatch.setattr(settings, "auto_trading_live_sizing_mode", "NOTIONAL_PER_R")
    monkeypatch.setattr(settings, "auto_trading_notional_per_r", 25.0)
    suffix = str(int(datetime.now(timezone.utc).timestamp() * 1_000_000))[-6:]
    symbol = f"PQ{suffix}USDC"
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_symbols", symbol)
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_families", "sweep_reversal")
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine.metrics", _good_metrics)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._gate_context_for_symbol", _open_gate_context)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._today_trade_count", lambda self: 0)
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._current_exposure_rows", lambda self: [])
    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine._live_cluster_guard", lambda self, **kwargs: {})
    monkeypatch.setattr(
        "app.services.strategy_engine.StrategyEngine.load_binance_symbol_trading_rules",
        lambda self, requested_symbol: {
            "symbol": requested_symbol,
            "quantity_step": 0.001,
            "min_quantity": 0.001,
            "tick_size": 0.1,
            "source": "binance_exchange_info",
        },
    )

    captured: dict[str, object] = {}

    def _fake_submit(self, **kwargs):
        captured.update(kwargs)
        return {
            "symbol": kwargs["symbol"],
            "plan_id": kwargs["plan_id"],
            "order_id": 987657,
            "client_order_id": kwargs["client_order_id"],
            "status": "NEW",
            "side": kwargs["side"],
            "order_type": kwargs["order_type"],
            "reduce_only": kwargs["reduce_only"],
        }

    monkeypatch.setattr("app.services.strategy_engine.StrategyEngine.submit_binance_order", _fake_submit)

    plan_id = f"{symbol}_price_{suffix}"
    _seed_plan(symbol=symbol, family="sweep_reversal", plan_id=plan_id, entry_model="LIMIT")
    with SessionLocal() as db:
        plan = db.get(Plan, plan_id)
        assert plan is not None
        plan.entry_price = 100.03
        db.add(plan)
        db.commit()

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
    assert submit_payload["state"] == "ACKNOWLEDGED"
    assert captured["price"] == 100.0
    live_price = submit_payload["attachments"]["live_order_sizing"]["live_limit_price"]
    assert live_price["requested_limit_price"] == 100.03
    assert live_price["tick_size"] == 0.1
    assert live_price["normalized_limit_price"] == 100.0


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


def test_transition_edge_variant_lock_does_not_block_baseline_entries_globally() -> None:
    init_db()
    with SessionLocal() as db:
        service = SafetyLockService(repo=SafetyLockRepository(db), settings=get_settings())
        service.set_transition_edge_variant_disabled(
            active=True,
            family="sweep_reversal",
            reason_message="variant disabled for transition validation",
        )
        state = service.safety_state(
            symbol="BTCUSDC",
            family="sweep_reversal",
            session_name="london",
        )
        assert state["new_entry_allowed"] is True
        assert state["transition_edge_variant_disabled_active"] is True
        reason_codes = {item["reason_code"] for item in state["transition_edge_variant_matching_locks"]}
        assert SafetyLockService.TRANSITION_EDGE_VARIANT_DISABLED_REASON in reason_codes


def test_execution_lane_tracker_separates_base_and_variant() -> None:
    tracker = reset_execution_lane_tracker(window=5)

    tracker.record_intent(is_variant=False)
    tracker.record_submitted(is_variant=False)
    tracker.record_filled(is_variant=False)
    tracker.record_closed(is_variant=False, realized_r=0.5)

    tracker.record_intent(is_variant=True)
    tracker.record_submitted(is_variant=True)
    tracker.record_filled(is_variant=True)
    tracker.record_closed(is_variant=True, realized_r=1.0)

    snapshot = tracker.snapshot()
    assert snapshot["counts"]["base"]["intent"] == 1
    assert snapshot["counts"]["variant"]["intent"] == 1
    assert snapshot["counts"]["base"]["closed"] == 1
    assert snapshot["counts"]["variant"]["closed"] == 1
    assert snapshot["ev"]["base"] == 0.5
    assert snapshot["ev"]["variant"] == 1.0
    assert snapshot["downstream"]["base"]["filled_rate"] == 1.0
    assert snapshot["downstream"]["variant"]["closed_rate"] == 1.0
    assert get_execution_lane_tracker(window=5).snapshot()["window"] == 5
