from __future__ import annotations

from app.services.split_review_followup_ledger import (
    record_split_review_followup_ledger_entry,
    record_split_review_followup_ledger_transition,
    resolve_split_review_followup_ledger_packet,
    summarize_split_review_followup_ledger,
)


def test_split_review_followup_ledger_records_and_summarizes_recent_packets(tmp_path) -> None:
    ledger_path = tmp_path / "review_ledger.jsonl"
    base_payload = {
        "generated_at": "2026-03-25T12:00:00+00:00",
        "symbol": "BTCUSDC",
        "universe": "usdc_perp_top30",
        "days": 7,
        "operator_action_priority": {
            "top_action": "run_entry_timing_split_review",
            "top_reason": "preferred branch looks stronger post-cost",
            "priority_level": "watch",
            "priority_source": "edge_experiment",
        },
        "edge_experiment_review": {
            "edge_state": "watch_edge",
            "closed_trade_count": 6,
            "true_edge_ratio": 0.81,
            "recent_true_edge_ratio": 0.84,
            "prior_true_edge_ratio": 0.78,
            "edge_decay_rate": -0.04,
            "entry_timing_preferred_variant": "early_limit",
            "execution_style_preferred_variant": "passive_limit",
        },
        "edge_evolution_rule": {
            "evolution_state": "reduce_candidate",
            "recommended_action": "reduce_baseline_allocation_review",
            "allocation_bias": "reduce_baseline",
            "confidence": "medium",
            "recommendation_strength": "confirmed",
            "promotion_candidate_axis": "entry_timing",
            "promotion_candidate_variant": "early_limit",
        },
    }
    record_split_review_followup_ledger_entry(
        {
            **base_payload,
            "status": "READY",
            "selected_action": "run_entry_timing_split_review",
            "selection_reason": "top_action",
            "target_contract": {
                "action": "run_entry_timing_split_review",
                "axis": "entry_timing",
                "preferred_variant": "early_limit",
                "symbol": "BTCUSDC",
                "status": "ACTIONABLE_ENTRY",
                "strategy_family": "sweep_reversal",
                "focus_source": "accepted_candidate_focus",
            },
            "report_path": "reports/operations/split_review_followups/first.md",
        },
        ledger_path=ledger_path,
    )
    record_split_review_followup_ledger_entry(
        {
            **base_payload,
            "generated_at": "2026-03-25T12:05:00+00:00",
            "status": "NO_TARGET",
            "selected_action": "reduce_baseline_allocation_review",
            "selection_reason": "top_action",
            "target_contract": {
                "action": "reduce_baseline_allocation_review",
                "axis": "entry_timing",
                "preferred_variant": "early_limit",
                "symbol": "BTCUSDC",
                "status": "BLOCKED_ENTRY",
                "strategy_family": "sweep_reversal",
                "focus_source": "blocked_candidate_focus",
            },
            "report_path": "reports/operations/split_review_followups/second.md",
        },
        ledger_path=ledger_path,
    )

    summary = summarize_split_review_followup_ledger(
        symbol="BTCUSDC",
        universe="usdc_perp_top30",
        ledger_path=ledger_path,
    )

    assert summary["available"] is True
    assert summary["recent_entry_count"] == 2
    assert summary["last_status"] == "NO_TARGET"
    assert summary["last_generated_status"] == "NO_TARGET"
    assert summary["last_decision_status"] == "none"
    assert summary["last_effective_status"] == "NO_TARGET"
    assert summary["last_action"] == "reduce_baseline_allocation_review"
    assert summary["last_target_contract"]["strategy_family"] == "sweep_reversal"
    assert summary["last_closed_trade_count"] == 6
    assert summary["last_entry_timing_preferred_variant"] == "early_limit"
    assert summary["last_recommendation_strength"] == "confirmed"
    assert summary["last_followup_command"].endswith(
        "--symbol BTCUSDC --universe usdc_perp_top30 --days 7 --action reduce_baseline_allocation_review"
    )
    assert summary["latest_action_streak"] == 1
    assert summary["latest_no_target_action_streak"] == 1
    assert summary["recent_status_counts"] == {"NO_TARGET": 1, "READY": 1}
    assert len(summary["recent_packets"]) == 2
    assert summary["recent_packets"][0]["packet_key"] == (
        "reduce_baseline_allocation_review|entry_timing|early_limit|BTCUSDC|sweep_reversal"
    )
    assert summary["recent_packets"][0]["edge_experiment_review"]["closed_trade_count"] == 6
    assert {row["action"] for row in summary["recent_action_counts"]} == {
        "reduce_baseline_allocation_review",
        "run_entry_timing_split_review",
    }


def test_split_review_followup_ledger_records_decision_transitions(tmp_path) -> None:
    ledger_path = tmp_path / "review_ledger.jsonl"
    packet = record_split_review_followup_ledger_entry(
        {
            "generated_at": "2026-03-25T12:00:00+00:00",
            "symbol": "BTCUSDC",
            "universe": "usdc_perp_top30",
            "days": 7,
            "status": "READY",
            "selected_action": "reduce_baseline_allocation_review",
            "selection_reason": "top_action",
            "operator_action_priority": {
                "top_action": "reduce_baseline_allocation_review",
                "top_reason": "preferred branch still looks stronger post-cost",
                "priority_level": "watch",
                "priority_source": "edge_evolution",
            },
            "edge_experiment_review": {
                "edge_state": "watch_edge",
                "closed_trade_count": 6,
                "true_edge_ratio": 0.84,
                "recent_true_edge_ratio": 0.82,
                "prior_true_edge_ratio": 0.9,
                "edge_decay_rate": -0.08,
                "entry_timing_preferred_variant": "early_limit",
                "execution_style_preferred_variant": "passive_limit",
            },
            "edge_evolution_rule": {
                "evolution_state": "reduce_candidate",
                "recommended_action": "reduce_baseline_allocation_review",
                "allocation_bias": "reduce_baseline",
                "confidence": "medium",
                "recommendation_strength": "confirmed",
                "promotion_candidate_axis": "entry_timing",
                "promotion_candidate_variant": "early_limit",
            },
            "target_contract": {
                "action": "reduce_baseline_allocation_review",
                "axis": "entry_timing",
                "preferred_variant": "early_limit",
                "symbol": "BTCUSDC",
                "status": "ACTIONABLE_ENTRY",
                "strategy_family": "sweep_reversal",
                "focus_source": "accepted_candidate_focus",
            },
        },
        ledger_path=ledger_path,
    )

    transition = record_split_review_followup_ledger_transition(
        symbol="BTCUSDC",
        universe="usdc_perp_top30",
        decision_status="ACKED",
        packet_id=str(packet.get("packet_id") or ""),
        decision_actor="micro_live_preflight",
        decision_notes="packet acknowledged by operator",
        transition_reason="handoff_confirmed",
        ledger_path=ledger_path,
    )

    resolved = resolve_split_review_followup_ledger_packet(
        symbol="BTCUSDC",
        universe="usdc_perp_top30",
        packet_id=str(packet.get("packet_id") or ""),
        ledger_path=ledger_path,
    )
    summary = summarize_split_review_followup_ledger(
        symbol="BTCUSDC",
        universe="usdc_perp_top30",
        ledger_path=ledger_path,
    )

    assert transition["status_phase"] == "decision"
    assert resolved is not None
    assert resolved["latest_decision_status"] == "ACKED"
    assert summary["recent_entry_count"] == 1
    assert summary["recent_decision_entry_count"] == 1
    assert summary["total_event_count"] == 2
    assert summary["last_status"] == "READY"
    assert summary["last_decision_status"] == "ACKED"
    assert summary["last_effective_status"] == "ACKED"
    assert summary["last_decision_actor"] == "micro_live_preflight"
    assert summary["last_decision_notes"] == "packet acknowledged by operator"
    assert summary["last_transition_reason"] == "handoff_confirmed"
    assert summary["recent_decision_status_counts"] == {"ACKED": 1}
    assert summary["recent_packets"][0]["generated_status"] == "READY"
    assert summary["recent_packets"][0]["decision_status"] == "ACKED"


def test_split_review_followup_ledger_summary_handles_missing_history(tmp_path) -> None:
    summary = summarize_split_review_followup_ledger(
        symbol="ETHUSDC",
        universe="usdc_perp_top30",
        ledger_path=tmp_path / "missing.jsonl",
    )

    assert summary["available"] is False
    assert summary["recent_entry_count"] == 0
    assert summary["last_status"] == "none"
    assert summary["last_decision_status"] == "none"
    assert summary["last_action"] == "none"
