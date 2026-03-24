from __future__ import annotations

from app.services.split_review_followup_ledger import (
    record_split_review_followup_ledger_entry,
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
            "true_edge_ratio": 0.81,
            "edge_decay_rate": -0.04,
        },
        "edge_evolution_rule": {
            "evolution_state": "reduce_candidate",
            "recommended_action": "reduce_baseline_allocation_review",
            "allocation_bias": "reduce_baseline",
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
    assert summary["last_action"] == "reduce_baseline_allocation_review"
    assert summary["last_target_contract"]["strategy_family"] == "sweep_reversal"
    assert summary["last_followup_command"].endswith(
        "--symbol BTCUSDC --universe usdc_perp_top30 --days 7 --action reduce_baseline_allocation_review"
    )
    assert summary["recent_status_counts"] == {"NO_TARGET": 1, "READY": 1}
    assert {row["action"] for row in summary["recent_action_counts"]} == {
        "reduce_baseline_allocation_review",
        "run_entry_timing_split_review",
    }


def test_split_review_followup_ledger_summary_handles_missing_history(tmp_path) -> None:
    summary = summarize_split_review_followup_ledger(
        symbol="ETHUSDC",
        universe="usdc_perp_top30",
        ledger_path=tmp_path / "missing.jsonl",
    )

    assert summary["available"] is False
    assert summary["recent_entry_count"] == 0
    assert summary["last_status"] == "none"
    assert summary["last_action"] == "none"
