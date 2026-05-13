from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.db.models import BinanceOrderLedger, ExecutionFill, OrderIntent, OrderSubmission, Plan
from app.db.session import SessionLocal
from app.services.live_order_lifecycle import LiveOrderLifecycleReporter


def test_blocked_intent_detail_filters_blank_collections_without_crashing() -> None:
    row = SimpleNamespace(
        approval_snapshot={
            "validation_block_detail": {
                "grade": "C",
                "failed_checks": ["drawdown"],
                "empty_checks": [],
                "empty_metadata": {},
                "empty_text": "",
                "missing": None,
            }
        },
        decision_reason_code="validation_do_not_deploy",
    )

    assert LiveOrderLifecycleReporter._blocked_intent_detail(row) == {
        "grade": "C",
        "failed_checks": ["drawdown"],
    }


def test_blocked_intent_detail_enriches_legacy_validation_do_not_deploy_detail() -> None:
    row = SimpleNamespace(
        approval_snapshot={
            "validation_block_detail": {
                "recommendation": "do-not-deploy",
                "grade": "F",
                "risk_state": "OPEN",
                "risk_reason": "normal",
                "metrics": {"sample_size": 0, "win_rate": 0.0, "ev": 0.0, "total_score": 28.33},
            }
        },
        decision_reason_code="validation_do_not_deploy",
    )

    detail = LiveOrderLifecycleReporter._blocked_intent_detail(row)

    assert detail["primary_cause"] == "validation_sample_missing"
    assert [item["code"] for item in detail["root_causes"]][:2] == [
        "validation_sample_missing",
        "validation_expectancy_non_positive",
    ]
    assert "candidate_block_reason_message" not in detail


def test_blocked_intent_detail_keeps_real_candidate_block_message() -> None:
    row = SimpleNamespace(
        approval_snapshot={
            "validation_block_detail": {
                "recommendation": "do-not-deploy",
                "grade": "F",
                "risk_state": "OPEN",
                "risk_reason": "normal",
                "candidate_block_reason": "portfolio_cap",
                "candidate_block_reason_message": "Portfolio cap is full.",
                "metrics": {"sample_size": 1, "win_rate": 0.0, "ev": 0.0, "total_score": 28.33},
            }
        },
        decision_reason_code="validation_do_not_deploy",
    )

    detail = LiveOrderLifecycleReporter._blocked_intent_detail(row)

    assert detail["candidate_block_reason_message"] == "Portfolio cap is full."


def test_live_order_lifecycle_report_links_intent_submission_fill_and_ledger() -> None:
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        plan = Plan(
            plan_id="plan_lifecycle_1",
            zone_id="zone_lifecycle_1",
            symbol="BTCUSDC",
            timeframe="5m",
            direction="long",
            entry_model="LIMIT",
            entry_price=100.0,
            sl=99.0,
            tp1=101.0,
            tp2=102.0,
            tp3=103.0,
            split={},
            rr_min=1.0,
            rr_base=2.0,
            rr_opt=3.0,
            ev=0.2,
            cost_est=0.01,
            confidence=80.0,
            validity={"strategy_family": "sweep_reversal"},
            state="PLANNED",
            valid_from=now - timedelta(minutes=10),
            valid_until=now + timedelta(minutes=60),
            strategy_version="v1",
        )
        intent = OrderIntent(
            intent_id="intent_lifecycle_1",
            plan_id=plan.plan_id,
            symbol=plan.symbol,
            strategy_family="sweep_reversal",
            execution_mode="MICRO_LIVE",
            approval_state="APPROVED_AUTO",
            submit_decision="SUBMIT",
            decision_reason_code="submit_ready",
            decision_reason_message="ready",
            created_at=now - timedelta(minutes=9),
        )
        submission = OrderSubmission(
            submission_id="sub_lifecycle_1",
            intent_id=intent.intent_id,
            plan_id=plan.plan_id,
            symbol=plan.symbol,
            client_order_id="intent-lifecycle-1",
            exchange_order_id="123",
            state="FILLED",
            submit_status="FILLED",
            message="ok",
            adapter="binance",
            execution_mode="MICRO_LIVE",
            side="BUY",
            order_type="LIMIT",
            reduce_only=False,
            requested_live=True,
            submitted_at=now - timedelta(minutes=8),
            acknowledged_at=now - timedelta(minutes=8),
        )
        entry_fill = ExecutionFill(
            fill_id="fill_lifecycle_entry",
            plan_id=plan.plan_id,
            symbol=plan.symbol,
            stage="ENTRY",
            fill_ts=now - timedelta(minutes=7),
            price=100.2,
            qty=1.0,
            fee=0.01,
            from_state="PLANNED",
            to_state="ENTERED",
            state_changed=True,
            payload={"client_order_id": submission.client_order_id},
            strategy_version="v1",
        )
        close_fill = ExecutionFill(
            fill_id="fill_lifecycle_close",
            plan_id=plan.plan_id,
            symbol=plan.symbol,
            stage="CLOSED",
            fill_ts=now - timedelta(minutes=1),
            price=101.0,
            qty=1.0,
            fee=0.02,
            from_state="ENTERED",
            to_state="CLOSED",
            state_changed=True,
            payload={"exit_reason": "target_tp1", "realized_r": 0.8},
            strategy_version="v1",
        )
        ledger = BinanceOrderLedger(
            client_order_id=submission.client_order_id,
            exchange_order_id=123,
            plan_id=plan.plan_id,
            symbol=plan.symbol,
            side="BUY",
            order_type="LIMIT",
            status="FILLED",
            reduce_only=False,
            requested_live=True,
            live_enabled=True,
            test_order=False,
            price=100.0,
            orig_qty=1.0,
            executed_qty=1.0,
            time_in_force="GTC",
        )
        db.add_all([plan, intent, submission, entry_fill, close_fill, ledger])
        db.flush()

        payload = LiveOrderLifecycleReporter(db).generate(days=1, live_only=True, generated_at=now)

    assert payload["summary"]["submission_count"] == 1
    assert payload["summary"]["closed_count"] == 1
    assert payload["summary"]["avg_entry_slippage_bps"] == pytest.approx(20.0)
    assert payload["summary"]["avg_realized_r"] == pytest.approx(0.8)
    row = payload["rows"][0]
    assert row["lifecycle_status"] == "closed"
    assert row["binance_ledger_status"] == "FILLED"
    assert row["binance_test_order"] is False


def test_live_order_lifecycle_filters_intents_by_family_and_start_at() -> None:
    now = datetime.now(timezone.utc)
    suffix = uuid4().hex
    with SessionLocal() as db:
        db.add_all(
            [
                OrderIntent(
                    intent_id=f"intent_lifecycle_filter_sweep_{suffix}",
                    plan_id=f"plan_lifecycle_filter_sweep_{suffix}",
                    symbol="BTCUSDC",
                    strategy_family="sweep_reversal",
                    execution_mode="MICRO_LIVE",
                    approval_state="BLOCKED",
                    submit_decision="SKIP_BLOCKED",
                    decision_reason_code="validation_do_not_deploy",
                    decision_reason_message="old family",
                    created_at=now - timedelta(minutes=5),
                ),
                OrderIntent(
                    intent_id=f"intent_lifecycle_filter_sir_{suffix}",
                    plan_id=f"plan_lifecycle_filter_sir_{suffix}",
                    symbol="BTCUSDC",
                    strategy_family="session_impulse_retest",
                    execution_mode="MICRO_LIVE",
                    approval_state="BLOCKED",
                    submit_decision="SKIP_BLOCKED",
                    decision_reason_code="candidate_waiting",
                    decision_reason_message="current family",
                    created_at=now - timedelta(minutes=4),
                ),
                OrderIntent(
                    intent_id=f"intent_lifecycle_filter_old_{suffix}",
                    plan_id=f"plan_lifecycle_filter_old_{suffix}",
                    symbol="BTCUSDC",
                    strategy_family="session_impulse_retest",
                    execution_mode="MICRO_LIVE",
                    approval_state="BLOCKED",
                    submit_decision="SKIP_BLOCKED",
                    decision_reason_code="old_runtime",
                    decision_reason_message="before runtime",
                    created_at=now - timedelta(days=2),
                ),
            ]
        )
        db.flush()

        payload = LiveOrderLifecycleReporter(db).generate(
            days=3,
            live_only=True,
            generated_at=now,
            start_at=now - timedelta(hours=1),
            strategy_families=["session_impulse_retest"],
        )

    live_intents = payload["summary"]["live_intents"]
    assert live_intents["family_filter"] == ["session_impulse_retest"]
    assert live_intents["total"] == 1
    assert live_intents["top_block_reasons"] == {"candidate_waiting": 1}
