from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.enums import ExecutionMode
from app.db.models import BinancePositionSnapshot, ExecutionReconciliationEvent, OrderIntent, OrderSubmission
from app.db.session import SessionLocal, init_db
from app.main import app
from app.db.repositories import (
    BinancePositionRepository,
    ExecutionReconciliationEventRepository,
    OrderIntentRepository,
    OrderSubmissionRepository,
)
from app.services.execution.rollout import RolloutPolicyService
from app.services.execution.safety import SafetyLockService
from app.services.execution_operator_dashboard import ExecutionOperatorDashboardService
from app.repositories.execution import (
    FamilyRolloutPolicyRepository,
    SafetyLockRepository,
)

client = TestClient(app)


def _empty_review_followup_ledger(*args, **kwargs) -> dict:
    return {
        "available": False,
        "advisory_only": True,
        "symbol": str(kwargs.get("symbol") or ""),
        "universe": str(kwargs.get("universe") or ""),
        "ledger_path": "reports/operations/split_review_followups/review_ledger.jsonl",
        "total_entry_count": 0,
        "recent_entry_count": 0,
        "summary": "No split review follow-up packets have been recorded yet.",
        "reason_codes": ["recent_entries:0", "ledger:not_recorded"],
        "last_generated_at": "",
        "last_recorded_at": "",
        "last_status": "none",
        "last_action": "none",
        "last_selection_reason": "",
        "last_followup_command": "",
        "last_report_path": "",
        "last_target_contract": {},
        "last_priority_source": "monitor",
        "last_priority_level": "monitor",
        "last_edge_state": "insufficient_edge_measurement",
        "last_true_edge_ratio": 0.0,
        "last_edge_decay_rate": 0.0,
        "last_evolution_state": "insufficient_sample",
        "last_recommended_action": "keep_current_baseline",
        "last_allocation_bias": "hold_current_baseline",
        "recent_status_counts": {},
        "recent_action_counts": [],
    }


def _apply_defaults(monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "auto_trading_enabled", True)
    monkeypatch.setattr(settings, "auto_trading_execution_mode", ExecutionMode.MICRO_LIVE)
    monkeypatch.setattr(settings, "portfolio_overlay_enabled", False)
    monkeypatch.setattr(settings, "alert_discord_webhook_url", "")
    monkeypatch.setattr(settings, "alert_push_webhook_url", "")
    monkeypatch.setattr(settings, "alert_telegram_bot_token", "")
    monkeypatch.setattr(settings, "alert_telegram_chat_id", "")
    monkeypatch.setattr(
        "app.services.execution_operator_dashboard.summarize_split_review_followup_ledger",
        _empty_review_followup_ledger,
    )


def _seed_rollout_and_lock(symbol: str) -> None:
    with SessionLocal() as db:
        rollout = RolloutPolicyService(repo=FamilyRolloutPolicyRepository(db))
        rollout.upsert(
            family="trend_continuation",
            live_enabled=True,
            max_execution_mode="MICRO_LIVE",
            max_risk_r=1.0,
            allowed_sessions=["london", "new_york"],
            min_quality_score=75.0,
            updated_by="test_operator_dashboard",
        )
        safety = SafetyLockService(repo=SafetyLockRepository(db), settings=get_settings())
        safety.set_close_only(
            active=True,
            reason_message=f"Close-only enabled for {symbol} dashboard test.",
            metadata={"updated_by": "test_operator_dashboard"},
        )
        db.commit()


def test_execution_operator_dashboard_aggregates_runtime_state(monkeypatch) -> None:
    init_db()
    _apply_defaults(monkeypatch)
    symbol = f"OPS{int(datetime.now(timezone.utc).timestamp() * 1_000_000)}USDC"
    now = datetime.now(timezone.utc).replace(microsecond=0)
    _seed_rollout_and_lock(symbol)

    with SessionLocal() as db:
        db.add(
            OrderIntent(
                intent_id=f"intent_{symbol}",
                plan_id=f"plan_{symbol}",
                symbol=symbol,
                strategy_family="trend_continuation",
                execution_mode="MICRO_LIVE",
                approval_state="APPROVED_AUTO",
                submit_decision="SUBMIT",
                decision_reason_code="submit_ready",
                decision_reason_message="Intent is approved for MICRO_LIVE submit.",
                thesis_fingerprint={"family": "trend_continuation"},
                dedupe_result={"status": "unique"},
                session_guidance={"state": "preferred"},
                quality_snapshot={"expected_ev_r": 0.42},
                approval_snapshot={
                    "allowed_execution_mode": "MICRO_LIVE",
                    "deployment_go_no_go": "GO",
                    "deployment_code": "go_runtime_gate_open",
                    "playbook_go_no_go": "GO",
                    "playbook_code": "go_runtime_gate_open",
                    "playbook_action": "allow_new_entry",
                    "outcome_approval_penalty": {
                        "status": "watch",
                        "penalty_tier": "reason_only",
                        "applied": True,
                        "reason_codes": ["execution_degradation:watch"],
                    },
                },
                payload={"thesis_cluster_id": f"cluster_{symbol}"},
                created_at=now,
            )
        )
        db.add(
            OrderIntent(
                intent_id=f"intent_old_{symbol}",
                plan_id=f"plan_old_{symbol}",
                symbol=symbol,
                strategy_family="trend_continuation",
                execution_mode="MICRO_LIVE",
                approval_state="APPROVED_AUTO",
                submit_decision="SUBMIT",
                decision_reason_code="submit_ready",
                decision_reason_message="Old intent should be filtered by days.",
                thesis_fingerprint={"family": "trend_continuation"},
                dedupe_result={"status": "unique"},
                session_guidance={"state": "preferred"},
                quality_snapshot={"expected_ev_r": 0.21},
                approval_snapshot={
                    "allowed_execution_mode": "MICRO_LIVE",
                    "deployment_go_no_go": "GO",
                    "deployment_code": "go_runtime_gate_open",
                    "playbook_go_no_go": "GO",
                    "playbook_code": "go_runtime_gate_open",
                    "playbook_action": "allow_new_entry",
                },
                payload={"thesis_cluster_id": f"cluster_old_{symbol}"},
                created_at=now - timedelta(days=10),
            )
        )
        db.add(
            OrderSubmission(
                submission_id=f"sub_{symbol}",
                intent_id=f"intent_{symbol}",
                plan_id=f"plan_{symbol}",
                symbol=symbol,
                client_order_id=f"client_{symbol}",
                exchange_order_id="12345",
                state="ACKNOWLEDGED",
                submit_status="acknowledged",
                message="submitted",
                adapter="paper",
                execution_mode="MICRO_LIVE",
                requested_live=False,
                submitted_at=now,
                acknowledged_at=now + timedelta(seconds=1),
            )
        )
        db.add(
            BinancePositionSnapshot(
                position_key=f"{symbol}:LONG",
                symbol=symbol,
                position_side="LONG",
                position_amt=0.01,
                entry_price=100.0,
                break_even_price=100.0,
                mark_price=101.0,
                liquidation_price=50.0,
                unrealized_pnl=1.0,
                notional=1.01,
                leverage=5,
                margin_type="cross",
                isolated_wallet=0.0,
                update_ts=now,
                raw={},
            )
        )
        db.add(
            ExecutionReconciliationEvent(
                event_id=f"recon_{symbol}",
                symbol=symbol,
                mismatch_type="MISSING_STOP_ORDER",
                severity="HIGH",
                message="Stop order is missing.",
                local_snapshot={"expected_stop": True},
                exchange_snapshot={"open_stop": False},
                payload={},
                lock_required=True,
                lock_applied=True,
                lock_scope="SYMBOL",
                created_at=now,
            )
        )
        db.add(
            ExecutionReconciliationEvent(
                event_id=f"recon_old_{symbol}",
                symbol=symbol,
                mismatch_type="ORPHAN_ORDER_LOCAL",
                severity="LOW",
                message="Old reconciliation event should be filtered by days.",
                local_snapshot={"order": "old"},
                exchange_snapshot={},
                payload={},
                lock_required=False,
                lock_applied=False,
                lock_scope=None,
                created_at=now - timedelta(days=10),
            )
        )
        db.commit()

    response = client.get(
        f"/execution/operator-dashboard?symbol={symbol}&universe=usdc_perp_top30&portfolio_limit=5&intent_limit=5&reconcile_limit=5&days=7"
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["symbol"] == symbol
    assert payload["report_window_days"] == 7
    assert payload["source_of_truth_hint"] == "execution_runtime_aggregate"
    assert payload["recent_intent_count"] == 1
    assert payload["open_order_count"] >= 1
    assert payload["open_position_count"] >= 1
    assert payload["recent_reconciliation_count"] == 1
    assert payload["recent_reconciliation_summary"]["highest_severity"] == "WARNING"
    assert payload["signal_funnel"]["recent_intents"] == 1
    assert payload["signal_funnel"]["submit_decision_counts"]["SUBMIT"] == 1
    assert payload["signal_funnel"]["runtime_candidates"] == (
        payload["portfolio_summary"]["accepted_candidate_count"]
        + payload["portfolio_summary"]["blocked_candidate_count"]
    )
    assert "family_pass_rates" in payload["signal_funnel"]
    assert "regime_pass_rates" in payload["signal_funnel"]
    assert "session_pass_rates" in payload["signal_funnel"]
    assert isinstance(payload["signal_funnel"]["family_pass_rates"], list)
    assert isinstance(payload["signal_funnel"]["regime_pass_rates"], list)
    assert isinstance(payload["signal_funnel"]["session_pass_rates"], list)
    assert "outcome_control_trace" in payload["signal_funnel"]
    assert payload["recent_intents"][0]["allowed_execution_mode"] == "MICRO_LIVE"
    assert payload["recent_intents"][0]["playbook_action"] == "allow_new_entry"
    assert payload["recent_intents"][0]["outcome_approval_penalty"]["penalty_tier"] == "reason_only"
    assert all(item["plan_id"] != f"plan_old_{symbol}" for item in payload["recent_intents"])
    assert payload["open_orders"][0]["state"] == "ACKNOWLEDGED"
    assert payload["open_positions"][0]["symbol"] == symbol
    assert payload["recent_reconciliation_events"][0]["mismatch_type"] == "MISSING_STOP_ORDER"
    assert "portfolio_summary" in payload
    assert payload["approval_strip_summary"]["approve_value"] in {"approval usable", "entry gate blocked", "runtime no_go"}
    assert "align_value" in payload["approval_strip_summary"]
    assert "act_value" in payload["approval_strip_summary"]
    assert isinstance(payload["portfolio_summary"]["blocked_reason_counts"], dict)
    if payload["portfolio_summary"]["blocked_candidate_count"] > 0:
        assert sum(payload["portfolio_summary"]["blocked_reason_counts"].values()) >= payload["portfolio_summary"]["blocked_candidate_count"]
    assert "alert_summary" in payload


def test_execution_operator_dashboard_groups_blocked_reasons_by_gate_type(monkeypatch) -> None:
    init_db()
    _apply_defaults(monkeypatch)

    with SessionLocal() as db:
        service = ExecutionOperatorDashboardService(
            intent_repo=OrderIntentRepository(db),
            submission_repo=OrderSubmissionRepository(db),
            reconciliation_repo=ExecutionReconciliationEventRepository(db),
            position_repo=BinancePositionRepository(db),
            settings=get_settings(),
        )
        payload = service.generate(
            symbol="BTCUSDC",
            days=7,
            intent_limit=5,
            reconcile_limit=5,
            safety_state={
                "new_entry_allowed": False,
                "blocking_reason_code": "reconciliation_fill_event_gap",
                "blocking_reason_message": "Open submissions exist but no execution fill event has been recorded recently.",
            },
            portfolio_summary={
                "accepted_candidates": [
                    {
                        "symbol": "BTCUSDC",
                        "plan_id": "plan_accept",
                        "strategy_family": "trend_continuation",
                        "strategy_cluster": "b_continuation",
                        "strategy_cluster_status": "available_but_guarded",
                        "multi_strategy_overlay": {
                            "available": True,
                            "cluster": "b_continuation",
                            "strategy_cluster_status": "available_but_guarded",
                            "mode": "A_PLUS_B",
                            "guarded": True,
                            "live_eligible": False,
                        },
                        "b_continuation_activation": {
                            "available": True,
                            "family": "trend_continuation",
                            "activation_state": "blocked",
                            "activation_bias": "clear_guardrails",
                        },
                        "strategy_cluster_balance": {
                            "available": True,
                            "cluster": "b_continuation",
                            "balance_state": "a_concentrated",
                            "balance_pressure": "guardrail_limited",
                            "balance_bias": "preserve_a_anchor",
                        },
                        "regime": "trend",
                        "session_guidance": {"state": "preferred"},
                        "expected_ev_r": 0.12,
                        "expected_win_prob": 0.55,
                        "recommended_risk_r": 0.5,
                        "allocated_risk_r": 0.55,
                        "outcome_bias": {"tier": "positive", "score_delta": 2.5, "applied": True},
                        "edge_experiment_focus": {
                            "edge_state": "watch_edge",
                            "entry_timing_preferred_variant": "early_limit",
                            "execution_style_preferred_variant": "passive_limit",
                        },
                        "capital_allocator": {
                            "tier": "boost",
                            "allocation_weight": 1.1,
                            "allocated_risk_r": 0.55,
                            "capital_pressure": "underallocated_positive",
                        },
                        "capital_pressure": "underallocated_positive",
                        "strategy_sizing": {
                            "outcome_risk_adjustment": {
                                "status": "watch",
                                "penalty_tier": "soft_clamp",
                                "applied": True,
                                "multiplier": 0.75,
                                "reason_codes": ["family_execution_degradation:watch"],
                            }
                        },
                    }
                ],
                "blocked_candidates": [
                    {
                        "symbol": "ETHUSDC",
                        "plan_id": "plan_block_1",
                        "block_reason": "mode_shadow_only",
                        "strategy_family": "trend_continuation",
                        "strategy_cluster": "b_continuation",
                        "strategy_cluster_status": "available_but_guarded",
                        "multi_strategy_overlay": {
                            "available": True,
                            "cluster": "b_continuation",
                            "strategy_cluster_status": "available_but_guarded",
                            "mode": "A_PLUS_B",
                            "guarded": True,
                            "live_eligible": False,
                        },
                        "b_continuation_activation": {
                            "available": True,
                            "family": "trend_continuation",
                            "activation_state": "blocked",
                            "activation_bias": "clear_guardrails",
                        },
                        "strategy_cluster_balance": {
                            "available": True,
                            "cluster": "b_continuation",
                            "balance_state": "a_concentrated",
                            "balance_pressure": "guardrail_limited",
                            "balance_bias": "preserve_a_anchor",
                        },
                        "regime": "trend",
                        "session_guidance": {"state": "preferred"},
                        "allocated_risk_r": 0.375,
                        "outcome_bias": {"tier": "negative", "score_delta": -2.5, "applied": True},
                        "edge_experiment_focus": {
                            "edge_state": "fragile_edge",
                            "entry_timing_preferred_variant": "reaction_confirmed",
                            "execution_style_preferred_variant": "market",
                        },
                        "capital_allocator": {
                            "tier": "reduce",
                            "allocation_weight": 0.75,
                            "allocated_risk_r": 0.375,
                            "capital_pressure": "overallocated_negative",
                        },
                        "capital_pressure": "overallocated_negative",
                        "strategy_sizing": {
                            "outcome_risk_adjustment": {
                                "status": "watch",
                                "penalty_tier": "soft_clamp",
                                "applied": True,
                                "multiplier": 0.75,
                                "reason_codes": ["mode_advisory:family:research_only"],
                            }
                        },
                    },
                    {
                        "symbol": "SOLUSDC",
                        "plan_id": "plan_block_2",
                        "block_reason": "total_cap_reached",
                        "strategy_family": "sweep_reversal",
                        "strategy_cluster": "a_reversal",
                        "strategy_cluster_status": "current_anchor",
                        "multi_strategy_overlay": {
                            "available": True,
                            "cluster": "a_reversal",
                            "strategy_cluster_status": "current_anchor",
                            "mode": "A_PLUS_B",
                            "guarded": False,
                            "live_eligible": True,
                        },
                        "regime": "range",
                        "session_guidance": {"state": "dead_session"},
                        "allocated_risk_r": 0.375,
                        "outcome_bias": {"tier": "negative", "score_delta": -2.5, "applied": True},
                        "capital_allocator": {
                            "tier": "reduce",
                            "allocation_weight": 0.75,
                            "allocated_risk_r": 0.375,
                            "capital_pressure": "neutral",
                        },
                        "capital_pressure": "neutral",
                        "strategy_sizing": {
                            "outcome_risk_adjustment": {
                                "status": "manual_review",
                                "penalty_tier": "hard_clamp",
                                "applied": True,
                                "multiplier": 0.5,
                                "reason_codes": ["post_cost_conversion:weak_family_alignment"],
                            }
                        },
                    },
                    {
                        "symbol": "XRPUSDC",
                        "plan_id": "plan_block_3",
                        "block_reason": "risk_budget_below_min",
                        "strategy_family": "sweep_reversal",
                        "strategy_cluster": "a_reversal",
                        "strategy_cluster_status": "current_anchor",
                        "multi_strategy_overlay": {
                            "available": True,
                            "cluster": "a_reversal",
                            "strategy_cluster_status": "current_anchor",
                            "mode": "A_PLUS_B",
                            "guarded": False,
                            "live_eligible": True,
                        },
                        "regime": "range",
                        "session_guidance": {"state": "dead_session"},
                        "expected_ev_r": 0.08,
                        "expected_win_prob": 0.48,
                        "alpha_research_candidate": True,
                        "alpha_research_reason": "risk_budget_below_min",
                        "alpha_research_softened_risk_r": 0.175,
                        "alpha_research_gap": 4.5,
                        "outcome_bias": {"tier": "negative", "score_delta": -2.5, "applied": True},
                        "strategy_sizing": {
                            "outcome_risk_adjustment": {
                                "status": "watch",
                                "penalty_tier": "soft_clamp",
                                "applied": True,
                                "multiplier": 0.75,
                                "reason_codes": ["regime_outcome:weak_alignment"],
                            }
                        },
                    },
                ],
                "blocked_reason_counts": {
                    "mode_shadow_only": 1,
                    "total_cap_reached": 1,
                    "risk_budget_below_min": 1,
                },
                "capital_allocator_summary": {
                    "available": True,
                    "allocator_state": "active",
                    "family_focus": "sweep_reversal",
                    "capital_pressure": "neutral",
                    "family_weights": [
                        {
                            "family": "sweep_reversal",
                            "tier": "reduce",
                            "allocation_weight": 0.75,
                            "allocated_risk_r": 0.375,
                            "capital_pressure": "neutral",
                        }
                    ],
                },
                "multi_strategy_ab_summary": {
                    "available": True,
                    "advisory_only": True,
                    "mode": "A_PLUS_B",
                    "raw_family_anchor": "sweep_reversal",
                    "summary": "A reversal remains the current production anchor while B continuation stays available but guarded under first-wave activation rules; range rotation remains research-only sidecar.",
                    "reason_codes": [
                        "mode:a_plus_b",
                        "cluster:a_reversal",
                        "cluster:b_continuation",
                        "b_guardrail:thin_sample",
                    ],
                    "a_cluster": {
                        "cluster": "a_reversal",
                        "strategy_cluster_status": "current_anchor",
                        "live_eligible": True,
                        "guarded": False,
                    },
                    "b_cluster": {
                        "cluster": "b_continuation",
                        "strategy_cluster_status": "available_but_guarded",
                        "live_eligible": False,
                        "guarded": True,
                        "guardrail_reasons": ["b_guardrail:thin_sample"],
                    },
                    "research_sidecar": {
                        "cluster": "research_only_sidecar",
                        "strategy_cluster_status": "research_only_sidecar",
                        "guarded": True,
                    },
                    "family_mix": [
                        {
                            "raw_family": "sweep_reversal",
                            "cluster": "a_reversal",
                            "total_candidates": 2,
                            "accepted_candidates": 1,
                            "blocked_candidates": 1,
                            "alpha_research_candidates": 1,
                        },
                        {
                            "raw_family": "trend_continuation",
                            "cluster": "b_continuation",
                            "total_candidates": 2,
                            "accepted_candidates": 1,
                            "blocked_candidates": 1,
                            "alpha_research_candidates": 0,
                        },
                    ],
                },
                "strategy_cluster_balance_summary": {
                    "available": True,
                    "advisory_only": True,
                    "mode": "A_PLUS_B",
                    "balance_state": "a_concentrated",
                    "balance_bias": "preserve_a_anchor",
                    "headline_cluster": "a_reversal",
                    "target_mix": "a_anchor_with_b_underweight",
                    "confidence": "low",
                    "summary": "The current mix remains concentrated in A while B continuation is still underweight or blocked.",
                    "family_mix": [
                        {
                            "raw_family": "sweep_reversal",
                            "cluster": "a_reversal",
                            "total_candidates": 2,
                            "accepted_candidates": 1,
                            "blocked_candidates": 1,
                            "alpha_research_candidates": 1,
                        },
                        {
                            "raw_family": "trend_continuation",
                            "cluster": "b_continuation",
                            "total_candidates": 2,
                            "accepted_candidates": 1,
                            "blocked_candidates": 1,
                            "alpha_research_candidates": 0,
                        },
                    ],
                },
            },
            alert_summary={},
            execution_quality_summary=None,
            performance_decomposition_summary={
                "available": True,
                "tuning_focus": [
                    {
                        "focus": "session",
                        "bucket": "dead_session",
                        "metric": "post_cost_expectancy_r",
                        "value": -0.08,
                        "samples": 6,
                    }
                ],
            },
            execution_friction_measurement_summary={
                "available": True,
                "advisory_only": True,
                "friction_state": "watch_friction",
                "friction_bias": "monitor_execution_drag",
                "fill_conversion_state": "healthy_fill_conversion",
                "slippage_state": "watch_slippage",
                "latency_state": "healthy_latency",
                "fee_state": "watch_fee_drag",
                "reconciliation_state": "healthy_reconciliation",
                "measurement_coverage_state": "mature_measurement",
                "stress_drag_state": "unknown_stress_drag",
                "fill_rate": 0.61,
                "fills_matched": 9,
                "fill_events_total": 11,
                "execution_fill_coverage": 0.8889,
                "avg_slippage_bps": 6.2,
                "p95_slippage_bps": 7.8,
                "avg_entry_latency_seconds": 210.0,
                "p95_entry_latency_seconds": 600.0,
                "avg_fee_component_r": 0.06,
                "p95_fee_component_r": 0.11,
                "approval_slippage_cap_bps": 12.0,
                "approval_fee_bps_reference": 4.0,
                "weakest_axis": "slippage_state",
                "confidence": "medium",
                "summary": "Execution drag is still manageable, but slippage is softening current post-cost confidence.",
                "reason_codes": [
                    "coverage:mature_measurement",
                    "slippage:watch_slippage",
                    "fee:watch_fee_drag",
                    "stress:unknown_stress_drag",
                ],
                "source_summary": {
                    "execution_quality_report_path": "reports/execution/execution_quality.md",
                    "stress_validation_report_path": None,
                    "stress_available": False,
                    "fill_sources": {"execution_fills": 8, "zone_outcomes_fallback": 1},
                    "reconciliation_highest_severity": "INFO",
                },
            },
            alpha_research_pipeline_summary={
                "analysis_symbol": "BTCUSDC",
                "summary": {
                    "alpha_research_candidate_count": 1,
                },
                "recommended_action_summary": {
                    "analysis_symbol": "BTCUSDC",
                    "recommended_action": "run_shadow_exit_review",
                    "recommended_scope": "family",
                    "recommended_reason": "information_failure_rate is elevated for this family",
                    "shadow_experiment_type": "exit_failure_review",
                    "bucket": "sweep_reversal",
                    "focus": "family_information_failure",
                    "confidence": "medium",
                    "sample_note": "usable evidence, but still limited",
                    "aligned_candidates": 1,
                    "deferred_by_experiment_sequence": True,
                    "experiment_sequence_state": "entry_timing_first",
                    "current_priority_experiment": "entry_timing",
                    "current_priority_action": "run_entry_timing_split_review",
                    "exit_optimization_allowed": False,
                    "sequencing_reason": "Lock entry timing first: compare early_limit versus reaction_confirmed before changing execution style or reviewing exit optimization.",
                },
                "recommended_actions": [
                    {
                        "recommended_action": "run_shadow_exit_review",
                        "recommended_scope": "family",
                        "recommended_reason": "information_failure_rate is elevated for this family",
                        "shadow_experiment_type": "exit_failure_review",
                        "bucket": "sweep_reversal",
                        "focus": "family_information_failure",
                        "confidence": "medium",
                        "sample_note": "usable evidence, but still limited",
                        "aligned_candidates": 1,
                        "deferred_by_experiment_sequence": True,
                        "experiment_sequence_state": "entry_timing_first",
                        "current_priority_experiment": "entry_timing",
                        "current_priority_action": "run_entry_timing_split_review",
                        "exit_optimization_allowed": False,
                        "sequencing_reason": "Lock entry timing first: compare early_limit versus reaction_confirmed before changing execution style or reviewing exit optimization.",
                    }
                ],
                "top_shadow_experiment": {
                    "analysis_symbol": "BTCUSDC",
                    "experiment_id": "shadow_exit_review_family",
                    "title": "Family Exit Failure Review",
                    "objective": "Determine whether elevated information failure in this family is an exit issue or a deeper quality problem.",
                    "recommended_action": "run_shadow_exit_review",
                    "recommended_scope": "family",
                    "shadow_experiment_type": "exit_failure_review",
                    "target": "family=sweep_reversal",
                    "focus": "family_information_failure",
                    "bucket": "sweep_reversal",
                    "confidence": "medium",
                    "sample_note": "usable evidence, but still limited",
                    "deferred_by_experiment_sequence": True,
                    "experiment_sequence_state": "entry_timing_first",
                    "current_priority_experiment": "entry_timing",
                    "current_priority_action": "run_entry_timing_split_review",
                    "exit_optimization_allowed": False,
                    "sequencing_reason": "Lock entry timing first: compare early_limit versus reaction_confirmed before changing execution style or reviewing exit optimization.",
                    "observe_metrics": ["information_failure_rate", "forced_exit_rate", "post_cost_ev"],
                    "success_criteria": [
                        "information failure looks reducible without weakening hard gates",
                        "forced exit overlap trends lower while post-cost EV remains stable",
                    ],
                    "stop_conditions": [
                        "sample is too thin to separate exit failure from noise",
                        "the same family also shows safety or structural violations",
                    ],
                    "promotion_guardrails": [
                        "do_not_promote_if_information_failure_persists",
                        "do_not_weaken_safety_or_structural_gates",
                    ],
                },
                "shadow_experiment_templates": [
                    {
                        "experiment_id": "shadow_exit_review_family",
                        "title": "Family Exit Failure Review",
                        "objective": "Determine whether elevated information failure in this family is an exit issue or a deeper quality problem.",
                        "recommended_action": "run_shadow_exit_review",
                        "recommended_scope": "family",
                        "shadow_experiment_type": "exit_failure_review",
                        "analysis_symbol": "BTCUSDC",
                        "target": "family=sweep_reversal",
                        "focus": "family_information_failure",
                        "bucket": "sweep_reversal",
                        "steps": [
                            "collect recent candidates for the target family in shadow mode",
                            "compare information failure against forced exit and time failure patterns",
                            "review whether the family keeps post-cost EV after filtering obvious failures",
                        ],
                        "observe_metrics": ["information_failure_rate", "forced_exit_rate", "post_cost_ev"],
                        "success_criteria": [
                            "information failure looks reducible without weakening hard gates",
                            "forced exit overlap trends lower while post-cost EV remains stable",
                        ],
                        "stop_conditions": [
                            "sample is too thin to separate exit failure from noise",
                            "the same family also shows safety or structural violations",
                        ],
                        "promotion_guardrails": [
                            "do_not_promote_if_information_failure_persists",
                            "do_not_weaken_safety_or_structural_gates",
                        ],
                        "confidence": "medium",
                        "sample_note": "usable evidence, but still limited",
                    }
                ],
                "research_focus_alignment": {
                    "available": True,
                    "analysis_symbol": "BTCUSDC",
                    "aligned_candidate_count": 1,
                    "top_focus": "family_information_failure",
                    "top_bucket": "sweep_reversal",
                    "focus_items": [
                        {
                            "focus": "family_information_failure",
                            "bucket": "sweep_reversal",
                            "metric": "information_failure_rate",
                            "value": 0.4,
                            "candidates": 1,
                            "top_reason": "risk_budget_below_min",
                            "top_symbol": "BTCUSDC",
                        }
                    ],
                },
                "alpha_research_evidence_summary": {
                    "available": True,
                    "analysis_symbol": "BTCUSDC",
                    "near_miss_reason_summary": {
                        "top_reason": "risk_budget_below_min",
                    },
                    "focus_alignment_summary": {
                        "aligned_candidate_count": 1,
                        "top_focus": "family_information_failure",
                        "top_bucket": "sweep_reversal",
                    },
                    "outcome_alignment_summary": {
                        "top_family_bottleneck": {"key": "sweep_reversal"},
                        "top_regime_bottleneck": {"key": "range"},
                        "top_session_bottleneck": {"key": "dead_session"},
                    },
                    "false_negative_suspects": [
                        {
                            "reason": "risk_budget_below_min",
                            "axis": "family",
                            "bucket": "sweep_reversal",
                            "matched_candidates": 1,
                            "alignment_strength": "high",
                        }
                    ],
                },
                "softening_candidate_review": {
                    "available": True,
                    "top_candidate": {
                        "reason": "risk_budget_below_min",
                        "axis": "family",
                        "bucket": "sweep_reversal",
                        "review_priority": "p1",
                    },
                    "review_items": [
                        {
                            "reason": "risk_budget_below_min",
                            "axis": "family",
                            "bucket": "sweep_reversal",
                            "review_priority": "p1",
                        }
                    ],
                },
                "promotion_watchlist": {
                    "available": True,
                    "watchlist_count": 1,
                    "watch_items": [
                        {
                            "focus": "family_information_failure",
                            "bucket": "sweep_reversal",
                            "matched_candidates": 1,
                            "not_ready_reason": None,
                        }
                    ],
                },
                "experiment_sequence": {
                    "state": "entry_timing_first",
                    "entry_timing_locked": False,
                    "execution_style_locked": False,
                    "exit_optimization_allowed": False,
                    "current_priority_experiment": "entry_timing",
                    "current_priority_action": "run_entry_timing_split_review",
                    "summary": "Lock entry timing first: compare early_limit versus reaction_confirmed before changing execution style or reviewing exit optimization.",
                },
            },
            score_to_outcome_funnel_summary={
                "available": True,
                "reason": "ok",
                "report_window_days": 30,
                "coverage_note": "selection is snapshot, execution outcomes are windowed history",
                "snapshot_selection": {
                    "runtime_candidates": 4,
                    "accepted_candidates": 1,
                    "blocked_candidates": 3,
                    "accept_rate": 0.25,
                },
                "historical_execution_outcomes": {
                    "submitted": 3,
                    "filled": 2,
                    "closed": 2,
                    "profitable": 1,
                    "baseline_cost_profitable": 1,
                    "fill_rate_from_submitted": 0.6667,
                    "close_rate_from_filled": 1.0,
                    "profitable_rate_from_closed": 0.5,
                    "baseline_cost_profitable_rate_from_closed": 0.5,
                },
                "money_funnel": {
                    "available": True,
                    "snapshot_expected_r": {
                        "runtime_candidates": 0.84,
                        "accepted_candidates": 0.24,
                        "blocked_candidates": 0.60,
                    },
                    "historical_expected_r": {
                        "generated": 1.42,
                        "submitted": 0.96,
                        "filled": 0.61,
                        "closed": 0.46,
                    },
                    "historical_realized_r": {
                        "raw_closed": 0.38,
                        "post_cost_closed": 0.31,
                        "cost_drag": -0.07,
                    },
                    "historical_windows": {
                        "recent": {
                            "closed": 1,
                            "closed_expected_r": 0.22,
                            "raw_closed_realized_r": 0.18,
                            "post_cost_closed_realized_r": 0.15,
                            "true_edge_ratio": 0.6818,
                        },
                        "prior": {
                            "closed": 1,
                            "closed_expected_r": 0.24,
                            "raw_closed_realized_r": 0.20,
                            "post_cost_closed_realized_r": 0.16,
                            "true_edge_ratio": 0.6667,
                        },
                    },
                    "historical_gap_r": {
                        "generated_to_submitted": 0.46,
                        "submitted_to_filled": 0.35,
                        "filled_to_closed": 0.15,
                        "closed_expected_to_raw_realized": -0.08,
                        "closed_expected_to_post_cost_realized": -0.15,
                    },
                    "summary": "expected_closed_r=0.4600, post_cost_closed_r=0.3100, submitted_to_filled_gap_r=0.3500",
                },
                "decomposition": {
                    "family": [{"key": "sweep_reversal"}],
                    "regime": [{"key": "range"}],
                    "session": [{"key": "dead_session"}],
                    "entry_model": [{"key": "LIMIT"}],
                    "entry_timing_variant": [
                        {
                            "key": "early_limit",
                            "submitted": 1,
                            "filled": 1,
                            "closed": 1,
                            "submitted_expected_r": 0.28,
                            "filled_expected_r": 0.28,
                            "closed_expected_r": 0.22,
                            "baseline_adjusted_r": 0.15,
                            "fill_rate_from_submitted": 1.0,
                        },
                        {
                            "key": "reaction_confirmed",
                            "submitted": 2,
                            "filled": 1,
                            "closed": 1,
                            "submitted_expected_r": 0.68,
                            "filled_expected_r": 0.33,
                            "closed_expected_r": 0.24,
                            "baseline_adjusted_r": 0.16,
                            "fill_rate_from_submitted": 0.5,
                        },
                    ],
                    "execution_mode": [{"key": "PAPER"}],
                    "execution_style": [
                        {
                            "key": "passive_limit",
                            "submitted": 1,
                            "filled": 1,
                            "closed": 1,
                            "submitted_expected_r": 0.28,
                            "filled_expected_r": 0.28,
                            "closed_expected_r": 0.22,
                            "baseline_adjusted_r": 0.15,
                            "fill_rate_from_submitted": 1.0,
                        },
                        {
                            "key": "market",
                            "submitted": 2,
                            "filled": 1,
                            "closed": 1,
                            "submitted_expected_r": 0.68,
                            "filled_expected_r": 0.33,
                            "closed_expected_r": 0.24,
                            "baseline_adjusted_r": 0.16,
                            "fill_rate_from_submitted": 0.5,
                        },
                    ],
                },
            },
            execution_degradation_advisory_summary={
                "available": True,
                "status": "watch",
                "healthy": False,
                "summary": "forced exits are elevated and runtime execution drag is rising.",
                    "recommended_action": "review_runtime_execution_drag_before_expansion",
                    "reason_codes": ["forced_exit_watch"],
                    "sample_context": {"plans_matured": 6, "fill_events_total": 4},
                    "reasons": [
                        {
                        "code": "forced_exit_watch",
                        "severity": "watch",
                            "message": "forced exits are elevated",
                        }
                    ],
                },
            family_execution_degradation_advisory_summary={
                "available": True,
                "coverage_note": "family execution advisory is advisory-only",
                "families": [
                    {
                        "family": "sweep_reversal",
                        "status": "watch",
                        "summary": "family execution quality is drifting and should be reviewed before scaling",
                        "reason_codes": ["family_forced_exit_ratio_drift"],
                        "recommended_action": "monitor_family_execution_drag_and_hold_size",
                        "fill_rate": 0.3333,
                        "avg_slippage_bps": None,
                        "forced_exit_ratio": 0.5,
                        "information_failure_ratio": 0.25,
                        "time_failure_ratio": 0.0,
                        "post_cost_alignment": "aligned_negative",
                        "confidence": "medium",
                        "sample_note": "family sample is usable, but still limited",
                        "advisory_only": True,
                    }
                ],
            },
            mode_advisory_summary={
                "available": True,
                "coverage_note": "mode advisory is evidence-backed but advisory only",
                "family": [
                    {
                        "axis": "family",
                        "bucket": "sweep_reversal",
                        "advisory_state": "research_only",
                        "confidence": "medium",
                    }
                ],
                "regime": [
                    {
                        "axis": "regime",
                        "bucket": "range",
                        "advisory_state": "watch",
                        "confidence": "medium",
                    }
                ],
                "session": [
                    {
                        "axis": "session",
                        "bucket": "dead_session",
                        "advisory_state": "watch",
                        "confidence": "low",
                    }
                ],
            },
            operator_action_priority_summary={
                "available": True,
                "top_action": "review_runtime_execution_drag_before_expansion",
                "top_reason": "global execution degradation requires manual review",
                "priority_level": "urgent",
                "priority_source": "execution_degradation",
                "action_family": "execution_review",
                "supporting_signals": [
                    "execution:watch",
                    "family:sweep_reversal:watch",
                    "mode:family=sweep_reversal:research_only",
                ],
                "blocking_signals": [
                    "entry_gate:reconciliation_fill_event_gap",
                    "research_only:family=sweep_reversal",
                ],
                "next_actions": [
                    {
                        "action": "run_shadow_exit_review",
                        "reason": "information_failure_rate is elevated for this family",
                        "priority_level": "research",
                        "source": "alpha_research",
                        "advisory_only": True,
                    }
                ],
                "capture_context": {
                    "available": True,
                    "dominant_bottleneck": {"stage": "submit_to_fill", "reason": "execution_fill_shortfall"},
                    "family_focus": {"key": "sweep_reversal"},
                    "maturity": "usable_activity",
                },
                "experiment_context": {
                    "available": True,
                    "edge_state": "watch_edge",
                    "true_edge_ratio": 0.67,
                    "edge_decay_rate": -0.03,
                    "entry_timing_preferred_variant": "early_limit",
                    "entry_timing_recommendation_reason": "higher_post_cost_true_edge_ratio",
                    "entry_timing_comparison_ready": True,
                    "execution_style_preferred_variant": "passive_limit",
                    "execution_style_recommendation_reason": "better_fill_capture_ratio",
                    "execution_style_comparison_ready": True,
                    "accepted_candidate_focus": {
                        "symbol": "BTCUSDC",
                        "status": "ACTIONABLE_ENTRY",
                        "strategy_family": "trend_continuation",
                        "edge_state": "watch_edge",
                        "entry_timing_preferred_variant": "early_limit",
                        "execution_style_preferred_variant": "passive_limit",
                        "focus_source": "accepted_candidate_focus",
                    },
                    "entry_timing_target": {
                        "symbol": "BTCUSDC",
                        "status": "ACTIONABLE_ENTRY",
                        "strategy_family": "trend_continuation",
                        "edge_state": "watch_edge",
                        "entry_timing_preferred_variant": "early_limit",
                        "execution_style_preferred_variant": "passive_limit",
                        "focus_source": "accepted_candidate_focus",
                    },
                    "execution_style_target": {
                        "symbol": "BTCUSDC",
                        "status": "ACTIONABLE_ENTRY",
                        "strategy_family": "trend_continuation",
                        "edge_state": "watch_edge",
                        "entry_timing_preferred_variant": "early_limit",
                        "execution_style_preferred_variant": "passive_limit",
                        "focus_source": "accepted_candidate_focus",
                    },
                },
                "advisory_only": True,
            },
            rollout_recommendation_summary={
                "available": True,
                "advisory_only": True,
                "family": "sweep_reversal",
                "recommendation": "research_only",
                "confidence": "low",
                "maturity": "thin_sample",
                "summary": "family=sweep_reversal should remain compare-only research while evidence matures; keep rollout policy unchanged and collect more outcome data.",
                "reason_codes": ["mode_advisory:research_only", "sample:thin_sample"],
                "current_policy": {
                    "live_enabled": False,
                    "max_execution_mode": "PAPER",
                    "max_risk_r": 0.5,
                },
                "suggested_policy_delta": {
                    "action": "keep_research_only",
                    "suggested_max_execution_mode": "PAPER",
                    "suggested_max_risk_r": 0.5,
                    "change_hint": "keep_research_bucket_and_collect_evidence",
                },
            },
            strategy_lifecycle_summary={
                "available": True,
                "advisory_only": True,
                "family": "sweep_reversal",
                "state": "research",
                "previous_state": "probation",
                "transition_bias": "observe",
                "confidence": "low",
                "summary": "family=sweep_reversal remains research-led and the current window is still too thin to separate promotion from noise.",
                "reason_codes": ["lifecycle:research", "rollout_recommendation:research_only", "sample:thin_sample"],
                "source_summary": {
                    "family_closed": 2,
                    "family_post_cost_rate": 0.0,
                    "family_execution_status": "watch",
                    "family_mode_advisory_state": "research_only",
                    "rollout_recommendation": "research_only",
                    "rollout_maturity": "thin_sample",
                    "previous_state": "probation",
                    "alpha_research_signal": "promotion_watch",
                    "modifier_state": "neutral",
                },
            },
            promotion_governance_summary={
                "available": True,
                "advisory_only": True,
                "family": "sweep_reversal",
                "state": "defer",
                "promotion_bias": "defer",
                "target_posture": "keep_current",
                "confidence": "low",
                "summary": "family=sweep_reversal promotion review should be deferred while guardrails remain active.",
                "reason_codes": [
                    "promotion_governance:defer",
                    "lifecycle:research",
                    "rollout_recommendation:research_only",
                    "sample:thin_sample",
                ],
                "source_summary": {
                    "lifecycle_state": "research",
                    "rollout_recommendation": "research_only",
                    "rollout_maturity": "thin_sample",
                    "positive_expansion_state": "not_ready",
                    "family_execution_status": "watch",
                    "condition_modifier_state": "negative",
                    "condition_modifier_axis": "liquidity_condition",
                    "allocator_tier": "boost",
                    "capital_pressure": "underallocated_positive",
                },
            },
            promotion_review_queue_summary={
                "available": True,
                "advisory_only": True,
                "queue_state": "defer_first_queue",
                "headline_family": "sweep_reversal",
                "top_review_action": "defer_review",
                "summary": "family=sweep_reversal should be reviewed first for defer causes before broader promotion review resumes.",
                "reason_codes": [
                    "promotion_review_queue:defer_first_queue",
                    "headline_family:sweep_reversal",
                    "top_review_action:defer_review",
                ],
                "review_queue": [
                    {
                        "family": "sweep_reversal",
                        "review_action": "defer_review",
                        "promotion_state": "defer",
                        "target_posture": "keep_current",
                        "priority_rank": 17,
                        "confidence": "low",
                        "summary": "family=sweep_reversal should be reviewed for guardrail causes before any promotion discussion.",
                        "reason_codes": ["promotion_governance:defer", "sample:thin_sample"],
                    }
                ],
                "source_summary": {
                    "promotion_ready_count": 0,
                    "defer_count": 1,
                    "hold_count": 0,
                    "thin_sample_count": 1,
                    "top_lifecycle_state": "research",
                    "top_promotion_state": "defer",
                    "top_allocator_tier": "boost",
                },
            },
            promotion_remediation_queue_summary={
                "available": True,
                "advisory_only": True,
                "queue_state": "execution_first_queue",
                "headline_family": "sweep_reversal",
                "top_remediation_action": "execution_remediation",
                "summary": "family=sweep_reversal should be reviewed first for execution drag and exit or fill guardrails before promotion review resumes.",
                "reason_codes": [
                    "promotion_remediation_queue:execution_first_queue",
                    "headline_family:sweep_reversal",
                    "top_remediation_action:execution_remediation",
                ],
                "remediation_queue": [
                    {
                        "family": "sweep_reversal",
                        "remediation_action": "execution_remediation",
                        "promotion_state": "defer",
                        "remediation_domain": "execution",
                        "priority_rank": 6,
                        "confidence": "high",
                        "summary": "family=sweep_reversal should review execution drag and exit or fill guardrails before reopening promotion review.",
                        "reason_codes": [
                            "promotion_governance:defer",
                            "family_execution:manual_review",
                            "sample:thin_sample",
                        ],
                    }
                ],
                "source_summary": {
                    "execution_first_count": 1,
                    "policy_first_count": 0,
                    "condition_first_count": 0,
                    "observe_count": 0,
                    "thin_sample_count": 0,
                    "top_promotion_state": "defer",
                    "top_review_action": "defer_review",
                    "top_remediation_domain": "execution",
                },
            },
            promotion_clearance_tracker_summary={
                "available": True,
                "advisory_only": True,
                "family": "sweep_reversal",
                "clearance_state": "blocked",
                "clearance_bias": "continue_remediation",
                "confidence": "medium",
                "summary": "family=sweep_reversal clearance remains blocked while active guardrail domains remain unresolved.",
                "reason_codes": [
                    "promotion_clearance:blocked",
                    "promotion_governance:defer",
                    "remediation_queue:execution_remediation",
                ],
                "remaining_guardrail_domains": ["execution", "policy"],
                "cleared_guardrail_domains": ["condition"],
                "source_summary": {
                    "promotion_state": "defer",
                    "review_action": "defer_review",
                    "remediation_action": "execution_remediation",
                    "family_execution_status": "manual_review",
                    "rollout_recommendation": "research_only",
                    "lifecycle_state": "research",
                    "top_condition_axis": "",
                    "allocator_tier": "boost",
                },
            },
            promotion_reopen_queue_summary={
                "available": True,
                "advisory_only": True,
                "queue_state": "clearance_first_queue",
                "headline_family": "sweep_reversal",
                "top_reopen_action": "continue_clearance",
                "summary": "family=sweep_reversal should continue guardrail clearing before promotion review re-opens.",
                "reason_codes": [
                    "promotion_reopen_queue:clearance_first_queue",
                    "headline_family:sweep_reversal",
                    "top_reopen_action:continue_clearance",
                ],
                "reopen_queue": [
                    {
                        "family": "sweep_reversal",
                        "reopen_action": "continue_clearance",
                        "clearance_state": "blocked",
                        "promotion_state": "defer",
                        "priority_rank": 16,
                        "confidence": "medium",
                        "summary": "family=sweep_reversal should continue guardrail clearing before promotion review re-opens.",
                        "reason_codes": [
                            "promotion_reopen_queue:continue_clearance",
                            "promotion_clearance:blocked",
                            "remediation_queue:execution_remediation",
                        ],
                    }
                ],
                "source_summary": {
                    "reopen_ready_count": 0,
                    "continue_clearance_count": 1,
                    "observe_count": 0,
                    "thin_sample_count": 0,
                    "top_clearance_state": "blocked",
                    "top_promotion_state": "defer",
                    "top_remediation_action": "execution_remediation",
                },
            },
            promotion_decision_brief_summary={
                "available": True,
                "advisory_only": True,
                "family": "sweep_reversal",
                "brief_state": "clearance_required",
                "decision_bias": "continue_clearance",
                "target_posture": "keep_current",
                "confidence": "medium",
                "summary": "family=sweep_reversal still needs guardrail clearing before promotion review should be reopened.",
                "reason_codes": [
                    "promotion_decision_brief:clearance_required",
                    "promotion_clearance:blocked",
                    "promotion_reopen_queue:continue_clearance",
                ],
                "source_summary": {
                    "governance_state": "defer",
                    "review_action": "defer_review",
                    "remediation_action": "execution_remediation",
                    "clearance_state": "blocked",
                    "reopen_action": "continue_clearance",
                    "family_execution_status": "manual_review",
                    "lifecycle_state": "research",
                    "positive_expansion_state": "not_ready",
                    "allocator_tier": "boost",
                },
            },
            auto_promotion_rollout_execution_summary={
                "available": True,
                "advisory_only": True,
                "execution_stage": "auto_execution_blocked",
                "execution_bias": "block_auto_execution",
                "action_domain": "no_write_observe",
                "target_family": "sweep_reversal",
                "target_posture": "keep_current",
                "write_scope": "none",
                "dry_run_only": False,
                "confidence": "low",
                "summary": "family=sweep_reversal auto execution remains blocked; keep governance changes advisory-only until guardrails clear.",
                "reason_codes": [
                    "auto_execution:auto_execution_blocked",
                    "promotion_decision_brief:clearance_required",
                    "promotion_reopen_queue:continue_clearance",
                    "execution_guardrail:watch",
                ],
                "source_summary": {
                    "promotion_state": "defer",
                    "brief_state": "clearance_required",
                    "reopen_action": "continue_clearance",
                    "clearance_state": "blocked",
                    "remediation_action": "execution_remediation",
                    "rollout_recommendation": "research_only",
                    "lifecycle_state": "research",
                    "family_execution_status": "watch",
                    "mode_state": "research_only",
                    "approval_penalty_status": "watch",
                    "positive_expansion_state": "not_ready",
                    "governance_target_posture": "keep_current",
                },
            },
            promotion_lifecycle_history_summary={
                "available": True,
                "advisory_only": True,
                "family": "sweep_reversal",
                "history_state": "history_attention_required",
                "latest_event_type": "remediation_started",
                "latest_event_ts": "2026-03-23T00:00:00+00:00",
                "event_count_30d": 3,
                "recent_transitions": [
                    "defer -> execution_remediation",
                    "defer -> blocked",
                    "blocked -> continue_clearance",
                ],
                "summary": "family=sweep_reversal history still points to active remediation or blocked clearance before promotion can progress.",
                "reason_codes": [
                    "history:history_attention_required",
                    "latest_event:remediation_started",
                    "history_event:remediation_started",
                ],
                "source_summary": {
                    "latest_source_key": "promotion_remediation_queue",
                    "latest_bias": "continue_remediation",
                    "latest_state_from": "defer",
                    "latest_state_to": "execution_remediation",
                },
            },
            research_promotion_operating_loop_summary={
                "available": True,
                "advisory_only": True,
                "family": "sweep_reversal",
                "loop_state": "shadow_test_ready",
                "loop_bias": "queue_shadow_test",
                "target_stage": "tested",
                "recommended_action": "run_shadow_exit_timing_review",
                "shadow_experiment_id": "shadow_exit_timing_family",
                "watchlist_ready": False,
                "confidence": "medium",
                "summary": "family=sweep_reversal has a concrete shadow-test path; queue the research test before any probation or promotion move.",
                "reason_codes": [
                    "research_loop:shadow_test_ready",
                    "target_stage:tested",
                    "governance:defer",
                ],
                "source_summary": {
                    "recommended_scope": "family",
                    "recommended_bucket": "sweep_reversal",
                    "watchlist_not_ready_reason": "thin_sample",
                    "governance_state": "defer",
                    "governance_target_posture": "keep_current",
                    "brief_state": "clearance_required",
                    "execution_stage": "auto_execution_blocked",
                    "history_state": "history_attention_required",
                    "family_execution_status": "watch",
                    "strategy_cluster_status": "current_anchor",
                },
            },
            multi_strategy_ab_summary={
                "available": True,
                "advisory_only": True,
                "mode": "A_PLUS_B",
                "raw_family_anchor": "sweep_reversal",
                "summary": "A reversal remains the current production anchor while B continuation stays available but guarded under first-wave activation rules; range rotation remains research-only sidecar.",
                "reason_codes": [
                    "mode:a_plus_b",
                    "cluster:a_reversal",
                    "cluster:b_continuation",
                    "b_guardrail:thin_sample",
                ],
                "a_cluster": {
                    "cluster": "a_reversal",
                    "strategy_cluster_status": "current_anchor",
                    "live_eligible": True,
                    "guarded": False,
                },
                "b_cluster": {
                    "cluster": "b_continuation",
                    "strategy_cluster_status": "available_but_guarded",
                    "live_eligible": False,
                    "guarded": True,
                    "guardrail_reasons": ["b_guardrail:thin_sample"],
                },
                "research_sidecar": {
                    "cluster": "research_only_sidecar",
                    "strategy_cluster_status": "research_only_sidecar",
                    "guarded": True,
                },
                "family_mix": [
                    {
                        "raw_family": "sweep_reversal",
                        "cluster": "a_reversal",
                        "total_candidates": 2,
                        "accepted_candidates": 1,
                        "blocked_candidates": 1,
                        "alpha_research_candidates": 1,
                    },
                    {
                        "raw_family": "trend_continuation",
                        "cluster": "b_continuation",
                        "total_candidates": 2,
                        "accepted_candidates": 1,
                        "blocked_candidates": 1,
                        "alpha_research_candidates": 0,
                    },
                ],
            },
            b_continuation_activation_summary={
                "available": True,
                "advisory_only": True,
                "family": "trend_continuation",
                "activation_state": "blocked",
                "activation_bias": "clear_guardrails",
                "target_mode": "A_PLUS_B",
                "confidence": "medium",
                "live_eligible": False,
                "summary": "B continuation still has hard first-wave blockers; clear execution, policy, or clearance guardrails before activation review.",
                "reason_codes": [
                    "b_activation:blocked",
                    "mode:a_plus_b",
                    "cluster_status:available_but_guarded",
                    "b_activation_block:family_execution_manual_review",
                ],
                "source_summary": {
                    "cluster_status": "available_but_guarded",
                    "family_closed": 10,
                    "family_execution_status": "manual_review",
                    "rollout_recommendation": "reduce",
                    "lifecycle_state": "degraded",
                    "governance_state": "defer",
                    "clearance_state": "blocked",
                    "reopen_action": "continue_clearance",
                    "brief_state": "clearance_required",
                    "execution_stage": "auto_execution_blocked",
                    "positive_expansion_state": "not_ready",
                    "thin_sample": False,
                    "guardrail_reasons": ["b_guardrail:thin_sample"],
                },
            },
            forward_stress_regime_validation_summary={
                "available": True,
                "advisory_only": True,
                "validation_state": "fragile_generalization",
                "validation_bias": "monitor_regime_stress_fragility",
                "coverage_state": "usable_validation",
                "walk_forward_state": "validated_walk_forward",
                "stress_state": "fragile_stress",
                "replay_state": "replay_followup_required",
                "regime_split_state": "validated_regime_split",
                "session_split_state": "fragile_session_split",
                "preferred_live_mode": "A_ONLY",
                "worst_scenario": "shock_concentration",
                "best_regime": "range",
                "best_session": "overlap",
                "weakest_axis": "stress_state",
                "summary": "Generalization still holds directionally, but stress evidence is fragile around shock_concentration; monitor deployment confidence before trusting current validation.",
                "reason_codes": [
                    "usable_validation_coverage",
                    "stress_catastrophic_drawdown",
                    "replay_followup_required",
                    "fragile_session_bucket",
                ],
            },
            kill_condition_automation_summary={
                "available": True,
                "advisory_only": True,
                "kill_condition_state": "close_only_review",
                "automation_bias": "propose_close_only",
                "write_scope": "proposal_only",
                "trigger_axis": "reconciliation_axis",
                "trigger_reason_codes": [
                    "kill_condition:close_only_review",
                    "risk_gate:closed",
                    "friction:degraded",
                    "generalization:insufficient",
                    "reconciliation:critical",
                ],
                "active_manual_override": False,
                "manual_override_reason": "",
                "arm_required": True,
                "summary": "Current evidence is weak enough that close-only review should happen before new entries continue.",
                "reason_codes": [
                    "kill_condition:close_only_review",
                    "risk_gate:closed",
                    "friction:degraded",
                    "generalization:insufficient",
                    "reconciliation:critical",
                    "execution_degradation:manual_review",
                ],
                "source_summary": {
                    "risk_gate_state": "closed",
                    "risk_gate_reason": "max_consecutive_losses",
                    "friction_state": "degraded",
                    "generalization_state": "insufficient",
                    "reconciliation_state": "critical",
                    "execution_degradation_state": "manual_review",
                    "family_execution_degradation_state": "watch",
                    "kill_switch_active": False,
                    "close_only_active": False,
                    "active_lock_count": 0,
                    "available_source_count": 7,
                },
            },
            b_continuation_edge_validation_summary={
                "available": True,
                "advisory_only": True,
                "raw_family": "trend_continuation",
                "strategy_cluster": "b_continuation",
                "edge_state": "fragile_edge",
                "validation_bias": "monitor_diversification",
                "sample_state": "mature_sample",
                "family_post_cost_rate": 0.5,
                "family_post_cost_ev": None,
                "diversification_state": "correlation_heavy",
                "drawdown_contribution_state": "drawdown_neutral",
                "a_b_correlation_proxy": "high_overlap_proxy",
                "weakest_axis": "liquidity_condition",
                "weakest_bucket": "shallow_liquidity",
                "confidence": "medium",
                "summary": "family=trend_continuation still has usable B evidence, but diversification remains fragile because the current A/B overlap proxy is still heavy.",
                "reason_codes": [
                    "b_edge:fragile_edge",
                    "sample:mature_sample",
                    "diversification:correlation_heavy",
                ],
                "source_summary": {"raw_family_anchor": "trend_continuation"},
            },
            strategy_cluster_balance_summary={
                "available": True,
                "advisory_only": True,
                "mode": "A_PLUS_B",
                "balance_state": "a_concentrated",
                "balance_bias": "preserve_a_anchor",
                "headline_cluster": "a_reversal",
                "target_mix": "a_anchor_with_b_underweight",
                "confidence": "low",
                "summary": "The current mix remains concentrated in A while B continuation is still underweight or blocked.",
                "family_mix": [
                    {
                        "raw_family": "sweep_reversal",
                        "cluster": "a_reversal",
                        "total_candidates": 2,
                        "accepted_candidates": 1,
                        "blocked_candidates": 1,
                        "alpha_research_candidates": 1,
                    },
                    {
                        "raw_family": "trend_continuation",
                        "cluster": "b_continuation",
                        "total_candidates": 2,
                        "accepted_candidates": 1,
                        "blocked_candidates": 1,
                        "alpha_research_candidates": 0,
                    },
                ],
            },
            a_strategy_post_cost_edge_validation_summary={
                "available": True,
                "advisory_only": True,
                "family": "sweep_reversal",
                "edge_state": "fragile_edge",
                "validation_bias": "monitor_fragility",
                "sample_state": "mature",
                "family_post_cost_rate": 0.375,
                "family_post_cost_ev": None,
                "weakest_axis": "liquidity_condition",
                "weakest_bucket": "shallow_liquidity",
                "confidence": "medium",
                "summary": "family=sweep_reversal still has usable A-anchor evidence, but fragility is concentrated in liquidity_condition:shallow_liquidity; monitor anchor confidence before treating A as fully stable.",
                "reason_codes": [
                    "a_edge:fragile_edge",
                    "sample:mature",
                    "weakest_axis:liquidity_condition",
                ],
                "source_summary": {"raw_family_anchor": "sweep_reversal"},
            },
            positive_evidence_expansion_summary={
                "available": True,
                "advisory_only": True,
                "family": "sweep_reversal",
                "state": "not_ready",
                "expansion_bias": "do_not_expand",
                "confidence": "low",
                "summary": "family=sweep_reversal is not ready for positive expansion language because evidence or execution guardrails remain incomplete.",
                "reason_codes": [
                    "positive_expansion:not_ready",
                    "rollout_recommendation:research_only",
                    "lifecycle:research",
                    "sample:thin_sample",
                ],
                "source_summary": {
                    "family_closed": 2,
                    "family_post_cost_rate": 0.0,
                    "family_execution_status": "watch",
                    "family_mode_advisory_state": "research_only",
                    "rollout_recommendation": "research_only",
                    "rollout_maturity": "thin_sample",
                    "lifecycle_state": "research",
                    "allocator_tier": "boost",
                    "modifier_state": "neutral",
                },
            },
            outcome_bucket_granularity_summary={
                "available": True,
                "advisory_only": True,
                "report_window_days": 30,
                "family_focus": {
                    "key": "sweep_reversal",
                    "closed": 8,
                    "baseline_cost_profitable_rate_from_closed": 0.375,
                },
                "top_condition_axis": "liquidity_condition",
                "top_condition_bucket": {
                    "key": "shallow_liquidity",
                    "closed": 4,
                    "baseline_cost_profitable_rate_from_closed": 0.25,
                },
                "confidence": "medium",
                "summary": "family=sweep_reversal shows the largest liquidity-proxy split in shallow_liquidity; treat shallow-liquidity drag as an informational condition modifier, not a root-cause certainty.",
                "reason_codes": [
                    "family_focus:sweep_reversal",
                    "top_axis:liquidity_condition",
                    "top_bucket:shallow_liquidity",
                    "coverage:usable_condition_split",
                ],
                "condition_axes": [
                    {"axis": "volatility_condition", "divergence": 0.04},
                    {"axis": "cost_condition", "divergence": 0.1},
                    {
                        "axis": "liquidity_condition",
                        "divergence": 0.18,
                        "proxy_note": "liquidity_proxy",
                    },
                ],
            },
            opportunity_capture_summary={
                "available": True,
                "advisory_only": True,
                "summary": "signal flow reaches submission but degrades at fill; family focus is sweep_reversal",
                "report_window_days": 30,
                "trades_per_day": {"submitted": 0.4, "filled": 0.2, "closed": 0.1},
                "capture_rates": {
                    "accept_rate": 0.4,
                    "submit_rate_from_runtime": 0.4,
                    "fill_rate_from_submitted": 0.5,
                    "close_rate_from_filled": 0.5,
                },
                "capture_gap": {
                    "runtime_to_submit_gap": 0.6,
                    "submit_to_fill_gap": 0.5,
                    "fill_to_close_gap": 0.5,
                },
                "blocked_mix": {"quality": 1, "rollout": 1, "structural": 1, "safety": 0, "unknown": 0},
                "dominant_bottleneck": {"stage": "submit_to_fill", "reason": "execution_fill_shortfall"},
                "family_focus": {
                    "key": "sweep_reversal",
                    "runtime_candidates": 4,
                    "submitted": 2,
                    "filled": 1,
                    "closed": 1,
                },
                "regime_modifier": {"key": "range", "state": "neutral"},
                "session_modifier": {"key": "dead_session", "state": "negative"},
            },
        )

    signal_funnel = payload["signal_funnel"]
    assert signal_funnel["blocked_gate_group_counts"]["rollout"] == 1
    assert signal_funnel["blocked_gate_group_counts"]["structural"] == 1
    assert signal_funnel["blocked_gate_group_counts"]["quality"] == 1
    assert signal_funnel["current_entry_gate_group"] == "safety"
    assert signal_funnel["hard_block_summary"]["blocked"] == 2
    assert signal_funnel["hard_block_summary"]["top_reason"] == "reconciliation_fill_event_gap"
    assert signal_funnel["softening_candidate_summary"]["blocked"] == 1
    assert signal_funnel["softening_candidate_summary"]["top_reason"] == "risk_budget_below_min"
    assert signal_funnel["rollout_block_summary"]["blocked"] == 1
    assert signal_funnel["rollout_block_summary"]["top_reason"] == "mode_shadow_only"
    assert signal_funnel["alpha_research_summary"]["candidates"] == 1
    assert signal_funnel["alpha_research_summary"]["top_reason"] == "risk_budget_below_min"
    assert signal_funnel["alpha_research_focus_alignment"]["available"] is True
    assert signal_funnel["alpha_research_focus_alignment"]["analysis_symbol"] == "BTCUSDC"
    assert signal_funnel["alpha_research_focus_alignment"]["top_focus"] == "family_information_failure"
    assert signal_funnel["alpha_research_focus_alignment"]["top_bucket"] == "sweep_reversal"
    assert signal_funnel["alpha_research_evidence_summary"]["available"] is True
    assert signal_funnel["alpha_research_evidence_summary"]["top_reason"] == "risk_budget_below_min"
    assert signal_funnel["alpha_research_evidence_summary"]["top_focus"] == "family_information_failure"
    assert signal_funnel["alpha_research_evidence_summary"]["top_family_bottleneck"] == "sweep_reversal"
    assert signal_funnel["alpha_research_evidence_summary"]["suspect_count"] == 1
    assert signal_funnel["alpha_research_softening_review"]["available"] is True
    assert signal_funnel["alpha_research_softening_review"]["top_candidate"]["bucket"] == "sweep_reversal"
    assert signal_funnel["alpha_research_promotion_watchlist"]["available"] is True
    assert signal_funnel["alpha_research_promotion_watchlist"]["watchlist_count"] == 1
    assert signal_funnel["alpha_research_promotion_watchlist"]["top_watch"]["bucket"] == "sweep_reversal"
    assert signal_funnel["alpha_research_recommended_action"]["available"] is True
    assert signal_funnel["alpha_research_recommended_action"]["analysis_symbol"] == "BTCUSDC"
    assert signal_funnel["alpha_research_recommended_action"]["recommended_action"] == "run_shadow_exit_review"
    assert signal_funnel["alpha_research_recommended_action"]["recommended_scope"] == "family"
    assert signal_funnel["alpha_research_recommended_action"]["focus"] == "family_information_failure"
    assert signal_funnel["alpha_research_recommended_action"]["bucket"] == "sweep_reversal"
    assert signal_funnel["alpha_research_recommended_action"]["confidence"] == "medium"
    assert signal_funnel["alpha_research_recommended_action"]["deferred_by_experiment_sequence"] is True
    assert signal_funnel["alpha_research_recommended_action"]["current_priority_experiment"] == "entry_timing"
    assert signal_funnel["alpha_research_recommended_action"]["current_priority_action"] == "run_entry_timing_split_review"
    assert len(signal_funnel["alpha_research_recommended_action"]["recommended_actions"]) == 1
    assert signal_funnel["alpha_research_top_shadow_experiment"]["available"] is True
    assert signal_funnel["alpha_research_top_shadow_experiment"]["analysis_symbol"] == "BTCUSDC"
    assert signal_funnel["alpha_research_top_shadow_experiment"]["experiment_id"] == "shadow_exit_review_family"
    assert signal_funnel["alpha_research_top_shadow_experiment"]["target"] == "family=sweep_reversal"
    assert signal_funnel["alpha_research_top_shadow_experiment"]["focus"] == "family_information_failure"
    assert signal_funnel["alpha_research_top_shadow_experiment"]["deferred_by_experiment_sequence"] is True
    assert signal_funnel["alpha_research_top_shadow_experiment"]["current_priority_experiment"] == "entry_timing"
    assert "post_cost_ev" in signal_funnel["alpha_research_top_shadow_experiment"]["observe_metrics"]
    assert len(signal_funnel["alpha_research_top_shadow_experiment"]["shadow_experiment_templates"]) == 1
    assert signal_funnel["quality_softening_priorities"][0]["reason"] == "risk_budget_below_min"
    assert signal_funnel["quality_softening_priorities"][0]["top_family"] == "sweep_reversal"
    assert signal_funnel["quality_softening_priorities"][0]["top_regime"] == "range"
    assert signal_funnel["quality_softening_priorities"][0]["top_session"] == "dead_session"
    assert signal_funnel["family_bottlenecks"][0]["key"] == "sweep_reversal"
    assert signal_funnel["regime_bottlenecks"][0]["key"] == "range"
    assert signal_funnel["session_bottlenecks"][0]["key"] == "dead_session"
    assert signal_funnel["score_to_outcome_funnel"]["available"] is True
    assert signal_funnel["score_to_outcome_funnel"]["runtime_candidates"] == 4
    assert signal_funnel["score_to_outcome_funnel"]["submitted"] == 3
    assert signal_funnel["score_to_outcome_funnel"]["money_funnel"]["historical_expected_r"]["closed"] == 0.46
    assert signal_funnel["score_to_outcome_funnel"]["operating_kpis"]["primary_focus"] == "after_cost_edge_proof"
    assert signal_funnel["score_to_outcome_funnel"]["operating_kpis"]["stage_conversion_rates"]["runtime_to_accepted"] == 0.25
    assert signal_funnel["score_to_outcome_funnel"]["operating_kpis"]["stage_conversion_rates"]["submitted_to_filled"] == 0.6667
    assert signal_funnel["score_to_outcome_funnel"]["operating_kpis"]["stage_conversion_rates"]["filled_to_closed"] == 1.0
    assert signal_funnel["score_to_outcome_funnel"]["operating_kpis"]["cost_adjusted_survival_rate"] == 0.5
    assert signal_funnel["score_to_outcome_funnel"]["top_family_bucket"]["key"] == "sweep_reversal"
    assert signal_funnel["execution_degradation_advisory"]["available"] is True
    assert signal_funnel["execution_degradation_advisory"]["status"] == "watch"
    assert signal_funnel["execution_degradation_advisory"]["recommended_action"] == (
        "review_runtime_execution_drag_before_expansion"
    )
    assert signal_funnel["family_execution_degradation_advisory"]["available"] is True
    assert signal_funnel["family_execution_degradation_advisory"]["family_count"] == 1
    assert signal_funnel["family_execution_degradation_advisory"]["top_family"]["family"] == "sweep_reversal"
    assert signal_funnel["family_execution_degradation_advisory"]["top_family"]["status"] == "watch"
    assert signal_funnel["mode_advisory"]["available"] is True
    assert signal_funnel["mode_advisory"]["family_top"]["bucket"] == "sweep_reversal"
    assert signal_funnel["mode_advisory"]["family_top"]["advisory_state"] == "research_only"
    assert signal_funnel["mode_advisory"]["regime_top"]["bucket"] == "range"
    assert signal_funnel["mode_advisory"]["session_top"]["bucket"] == "dead_session"
    assert signal_funnel["operator_action_priority"]["available"] is True
    assert signal_funnel["operator_action_priority"]["top_action"] == "review_runtime_execution_drag_before_expansion"
    assert signal_funnel["operator_action_priority"]["priority_level"] == "urgent"
    assert signal_funnel["operator_action_priority"]["priority_source"] == "execution_degradation"
    assert signal_funnel["operator_action_priority"]["action_family"] == "execution_review"
    assert signal_funnel["operator_action_priority"]["top_action_followup_command"] == ""
    assert signal_funnel["operator_action_priority"]["capture_context"]["dominant_bottleneck"]["reason"] == "execution_fill_shortfall"
    assert signal_funnel["operator_action_priority"]["experiment_context"]["entry_timing_target"]["symbol"] == "BTCUSDC"
    assert signal_funnel["operator_action_priority"]["experiment_context"]["entry_timing_target"]["followup_command"].endswith(
        "--symbol BTCUSDC --universe usdc_perp_top30 --days 7 --action run_entry_timing_split_review"
    )
    assert signal_funnel["operator_action_priority"]["experiment_context"]["execution_style_target"]["symbol"] == "BTCUSDC"
    assert signal_funnel["operator_action_priority"]["experiment_context"]["execution_style_target"]["followup_command"].endswith(
        "--symbol BTCUSDC --universe usdc_perp_top30 --days 7 --action run_execution_style_split_review"
    )
    assert signal_funnel["operator_action_priority"]["experiment_context"]["accepted_candidate_focus"]["symbol"] == "BTCUSDC"
    assert signal_funnel["operator_action_priority"]["advisory_only"] is True
    assert len(signal_funnel["operator_action_priority"]["next_actions"]) == 1
    assert signal_funnel["operator_action_priority"]["next_actions"][0]["followup_command"] == ""
    assert payload["approval_strip_summary"]["approve_value"] == "entry gate blocked"
    assert payload["approval_strip_summary"]["align_value"] == "aligned"
    assert payload["approval_strip_summary"]["act_value"] == "review_runtime_execution_drag_before_expansion"
    assert payload["approval_strip_summary"]["act_priority_level"] == "urgent"
    assert signal_funnel["outcome_control_trace"]["available"] is True
    assert signal_funnel["outcome_control_trace"]["approval_penalty_tier"] == "reason_only"
    assert signal_funnel["outcome_control_trace"]["sizing_penalty_tier"] == "hard_clamp"
    assert signal_funnel["outcome_control_trace"]["portfolio_bias_tier"] == "negative"
    assert signal_funnel["outcome_control_trace"]["portfolio_bias_distribution"]["negative"] == 3
    assert signal_funnel["outcome_attribution"]["available"] is True
    assert signal_funnel["outcome_attribution"]["strongest_drag_source"] == "fill_capture_gap"
    assert signal_funnel["outcome_attribution"]["fill_capture_gap_r"] == 0.35
    assert signal_funnel["outcome_attribution"]["reason_codes"] == [
        "closed_trades:2",
        "strongest_drag:fill_capture_gap",
        "friction:watch_friction",
        "execution_axis:slippage_state",
        "condition_focus:session",
        "condition_bucket:dead_session",
    ]
    assert signal_funnel["outcome_attribution"]["source_summary"]["weakest_execution_axis"] == "slippage_state"
    assert signal_funnel["outcome_attribution"]["source_summary"]["condition_bucket"] == "dead_session"
    assert signal_funnel["edge_experiment_review"]["available"] is True
    assert signal_funnel["edge_experiment_review"]["edge_state"] == "insufficient_edge_measurement"
    assert signal_funnel["edge_experiment_review"]["entry_timing_preferred_variant"] == "early_limit"
    assert signal_funnel["edge_experiment_review"]["execution_style_preferred_variant"] == "passive_limit"
    assert signal_funnel["edge_experiment_review"]["edge_proof_goal_closed_trades"] == 100
    assert signal_funnel["edge_experiment_review"]["edge_proof_posture"]["state"] == "sample_building"
    assert signal_funnel["edge_experiment_review"]["operating_discipline"]["discipline_state"] == "research_only_until_edge_proof_goal"
    assert signal_funnel["edge_experiment_review"]["operating_discipline"]["evaluation_focus"] == "after_cost_edge_only"
    assert signal_funnel["edge_experiment_review"]["operating_discipline"]["early_loss_rewrite_embargo_active"] is True
    assert signal_funnel["edge_experiment_review"]["operating_discipline"]["loss_driven_rewrite_allowed"] is False
    assert signal_funnel["edge_experiment_review"]["operating_discipline"]["rollout_expansion_allowed"] is False
    assert (
        signal_funnel["edge_experiment_review"]["operating_discipline"]["improvement_priority"]
        == "prove_single_edge_before_density_or_strategy_expansion"
    )
    assert signal_funnel["edge_experiment_review"]["operating_discipline"]["current_system_identity"] == "edge_proof_engine"
    assert signal_funnel["edge_experiment_review"]["operating_discipline"]["next_system_stage"] == "post_first_verified_edge"
    assert signal_funnel["edge_experiment_review"]["operating_discipline"]["resilience_claim"] == (
        "harder_to_fail_from_self_deception"
    )
    assert signal_funnel["edge_experiment_review"]["operating_discipline"]["fail_safe_claim"] is False
    assert signal_funnel["edge_experiment_review"]["operating_discipline"]["realized_edge_dependency_domains"] == [
        "market_edge",
        "execution_quality",
        "operating_discipline",
    ]
    assert signal_funnel["edge_experiment_review"]["operating_discipline"]["alpha_generator_review_allowed"] is False
    assert signal_funnel["edge_experiment_review"]["operating_discipline"]["signal_density_control_review_allowed"] is False
    assert signal_funnel["edge_experiment_review"]["operating_discipline"]["execution_strategy_automation_review_allowed"] is False
    assert signal_funnel["edge_experiment_review"]["operating_discipline"]["multi_strategy_expansion_review_allowed"] is False
    assert signal_funnel["edge_experiment_review"]["operating_discipline"]["deferred_system_upgrade_backlog"] == [
        "alpha_generator_layer",
        "capital_scale_curve",
        "signal_density_controller",
        "execution_strategy_automation",
        "multi_strategy_activation",
    ]
    assert signal_funnel["edge_experiment_review"]["daily_edge_kpis"]["regime_dependency_state"] == "insufficient_regime_closes"
    assert signal_funnel["edge_evolution_rule"]["available"] is True
    assert signal_funnel["edge_evolution_rule"]["evolution_state"] == "insufficient_sample"
    assert signal_funnel["edge_evolution_rule"]["recommended_action"] == "keep_research_only_until_sample_matures"
    assert signal_funnel["review_followup_ledger"]["available"] is False
    assert signal_funnel["review_followup_ledger"]["last_status"] == "none"
    assert signal_funnel["rollout_recommendation"]["family"] == "sweep_reversal"
    assert signal_funnel["rollout_recommendation"]["recommendation"] == "research_only"
    assert signal_funnel["rollout_recommendation"]["suggested_policy_delta"]["action"] == "keep_research_only"
    assert signal_funnel["strategy_lifecycle"]["available"] is True
    assert signal_funnel["strategy_lifecycle"]["family"] == "sweep_reversal"
    assert signal_funnel["strategy_lifecycle"]["state"] == "research"
    assert signal_funnel["strategy_lifecycle"]["transition_bias"] == "observe"
    assert signal_funnel["promotion_governance"]["available"] is True
    assert signal_funnel["promotion_governance"]["family"] == "sweep_reversal"
    assert signal_funnel["promotion_governance"]["state"] == "defer"
    assert signal_funnel["promotion_governance"]["promotion_bias"] == "defer"
    assert signal_funnel["promotion_review_queue"]["available"] is True
    assert signal_funnel["promotion_review_queue"]["queue_state"] == "defer_first_queue"
    assert signal_funnel["promotion_review_queue"]["headline_family"] == "sweep_reversal"
    assert signal_funnel["promotion_review_queue"]["top_review_action"] == "defer_review"
    assert signal_funnel["promotion_remediation_queue"]["available"] is True
    assert signal_funnel["promotion_remediation_queue"]["queue_state"] == "execution_first_queue"
    assert signal_funnel["promotion_remediation_queue"]["headline_family"] == "sweep_reversal"
    assert signal_funnel["promotion_remediation_queue"]["top_remediation_action"] == "execution_remediation"
    assert signal_funnel["promotion_clearance_tracker"]["available"] is True
    assert signal_funnel["promotion_clearance_tracker"]["family"] == "sweep_reversal"
    assert signal_funnel["promotion_clearance_tracker"]["clearance_state"] == "blocked"
    assert signal_funnel["promotion_clearance_tracker"]["clearance_bias"] == "continue_remediation"
    assert signal_funnel["promotion_reopen_queue"]["available"] is True
    assert signal_funnel["promotion_reopen_queue"]["queue_state"] == "clearance_first_queue"
    assert signal_funnel["promotion_reopen_queue"]["headline_family"] == "sweep_reversal"
    assert signal_funnel["promotion_reopen_queue"]["top_reopen_action"] == "continue_clearance"
    assert signal_funnel["promotion_decision_brief"]["available"] is True
    assert signal_funnel["promotion_decision_brief"]["family"] == "sweep_reversal"
    assert signal_funnel["promotion_decision_brief"]["brief_state"] == "clearance_required"
    assert signal_funnel["promotion_decision_brief"]["decision_bias"] == "continue_clearance"
    assert signal_funnel["auto_promotion_rollout_execution"]["available"] is True
    assert signal_funnel["auto_promotion_rollout_execution"]["execution_stage"] == "auto_execution_blocked"
    assert signal_funnel["auto_promotion_rollout_execution"]["execution_bias"] == "block_auto_execution"
    assert signal_funnel["auto_promotion_rollout_execution"]["target_family"] == "sweep_reversal"
    assert signal_funnel["promotion_lifecycle_history"]["available"] is True
    assert signal_funnel["promotion_lifecycle_history"]["family"] == "sweep_reversal"
    assert signal_funnel["promotion_lifecycle_history"]["history_state"] == "history_attention_required"
    assert signal_funnel["promotion_lifecycle_history"]["latest_event_type"] == "remediation_started"
    assert signal_funnel["research_promotion_operating_loop"]["available"] is True
    assert signal_funnel["research_promotion_operating_loop"]["family"] == "sweep_reversal"
    assert signal_funnel["research_promotion_operating_loop"]["loop_state"] == "shadow_test_ready"
    assert signal_funnel["research_promotion_operating_loop"]["target_stage"] == "tested"
    assert signal_funnel["multi_strategy_ab_expansion"]["available"] is True
    assert signal_funnel["multi_strategy_ab_expansion"]["mode"] == "A_PLUS_B"
    assert signal_funnel["multi_strategy_ab_expansion"]["b_cluster"]["strategy_cluster_status"] == "available_but_guarded"
    assert signal_funnel["b_continuation_activation"]["available"] is True
    assert signal_funnel["b_continuation_activation"]["family"] == "trend_continuation"
    assert signal_funnel["b_continuation_activation"]["activation_state"] == "blocked"
    assert signal_funnel["b_continuation_activation"]["activation_bias"] == "clear_guardrails"
    assert signal_funnel["execution_friction_measurement"]["available"] is True
    assert signal_funnel["execution_friction_measurement"]["friction_state"] == "watch_friction"
    assert signal_funnel["execution_friction_measurement"]["friction_bias"] == "monitor_execution_drag"
    assert signal_funnel["execution_friction_measurement"]["weakest_axis"] == "slippage_state"
    assert signal_funnel["forward_stress_regime_validation"]["available"] is True
    assert signal_funnel["forward_stress_regime_validation"]["validation_state"] == "fragile_generalization"
    assert (
        signal_funnel["forward_stress_regime_validation"]["validation_bias"]
        == "monitor_regime_stress_fragility"
    )
    assert signal_funnel["forward_stress_regime_validation"]["weakest_axis"] == "stress_state"
    assert signal_funnel["kill_condition_automation"]["available"] is True
    assert signal_funnel["kill_condition_automation"]["kill_condition_state"] == "close_only_review"
    assert signal_funnel["kill_condition_automation"]["automation_bias"] == "propose_close_only"
    assert signal_funnel["kill_condition_automation"]["trigger_axis"] == "reconciliation_axis"
    assert signal_funnel["b_continuation_edge_validation"]["available"] is True
    assert signal_funnel["b_continuation_edge_validation"]["raw_family"] == "trend_continuation"
    assert signal_funnel["b_continuation_edge_validation"]["edge_state"] == "fragile_edge"
    assert signal_funnel["b_continuation_edge_validation"]["validation_bias"] == "monitor_diversification"
    assert signal_funnel["strategy_cluster_balance"]["available"] is True
    assert signal_funnel["strategy_cluster_balance"]["mode"] == "A_PLUS_B"
    assert signal_funnel["strategy_cluster_balance"]["balance_state"] == "a_concentrated"
    assert signal_funnel["strategy_cluster_balance"]["balance_bias"] == "preserve_a_anchor"
    assert signal_funnel["a_strategy_post_cost_edge_validation"]["available"] is True
    assert signal_funnel["a_strategy_post_cost_edge_validation"]["family"] == "sweep_reversal"
    assert signal_funnel["a_strategy_post_cost_edge_validation"]["edge_state"] == "fragile_edge"
    assert signal_funnel["a_strategy_post_cost_edge_validation"]["validation_bias"] == "monitor_fragility"
    assert signal_funnel["positive_evidence_expansion"]["available"] is True
    assert signal_funnel["positive_evidence_expansion"]["family"] == "sweep_reversal"
    assert signal_funnel["positive_evidence_expansion"]["state"] == "not_ready"
    assert signal_funnel["positive_evidence_expansion"]["expansion_bias"] == "do_not_expand"
    assert signal_funnel["outcome_bucket_granularity"]["available"] is True
    assert signal_funnel["outcome_bucket_granularity"]["top_condition_axis"] == "liquidity_condition"
    assert signal_funnel["outcome_bucket_granularity"]["top_condition_bucket"]["key"] == "shallow_liquidity"
    assert signal_funnel["opportunity_capture"]["available"] is True
    assert signal_funnel["opportunity_capture"]["dominant_bottleneck"]["reason"] == "execution_fill_shortfall"
    assert signal_funnel["opportunity_capture"]["family_focus"]["key"] == "sweep_reversal"
    assert signal_funnel["capital_allocator"]["available"] is True
    assert signal_funnel["capital_allocator"]["family_focus"] == "sweep_reversal"
    assert payload["portfolio_summary"]["accepted_candidates"][0]["outcome_bias"]["tier"] == "positive"
    assert payload["portfolio_summary"]["accepted_candidates"][0]["strategy_cluster"] == "b_continuation"
    assert (
        payload["portfolio_summary"]["accepted_candidates"][0]["multi_strategy_overlay"]["strategy_cluster_status"]
        == "available_but_guarded"
    )
    assert (
        payload["portfolio_summary"]["accepted_candidates"][0]["b_continuation_activation"]["activation_state"]
        == "blocked"
    )
    assert (
        payload["portfolio_summary"]["accepted_candidates"][0]["strategy_cluster_balance"]["balance_state"]
        == "a_concentrated"
    )
    assert payload["portfolio_summary"]["accepted_candidates"][0]["capital_allocator"]["tier"] == "boost"
    assert payload["portfolio_summary"]["accepted_candidates"][0]["allocated_risk_r"] == 0.55
    assert payload["portfolio_summary"]["accepted_candidates"][0]["edge_experiment_focus"]["edge_state"] == "watch_edge"
    assert (
        payload["portfolio_summary"]["accepted_candidates"][0]["edge_experiment_focus"]["entry_timing_preferred_variant"]
        == "early_limit"
    )
    assert (
        payload["portfolio_summary"]["blocked_candidates"][0]["strategy_sizing"]["outcome_risk_adjustment"]["applied"]
        is True
    )
