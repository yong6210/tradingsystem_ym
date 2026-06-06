from datetime import UTC, datetime

from scripts.run_market_state_rotation_v6_near_miss_promotion_gate import build_near_miss_promotion_gate_report


def _smoke(name: str, *, decision: str, d_return: float, d_dd: float, d_adds: int) -> dict:
    return {
        "window": {"days": 120},
        "candidates": [
            {
                "name": "base",
                "delta_vs_base": {"return_pct": 0, "max_drawdown_pct": 0, "add_events": 0},
            },
            {
                "name": name,
                "total_return_pct": 10 + d_return,
                "max_drawdown_pct": 5 + d_dd,
                "add_events": 10 + d_adds,
                "smoke_decision": decision,
                "primary_use": "paper_evidence_collection_probe",
                "delta_vs_base": {
                    "return_pct": d_return,
                    "max_drawdown_pct": d_dd,
                    "add_events": d_adds,
                },
            },
        ],
    }


def test_near_miss_promotion_gate_blocks_candidate_that_fails_any_window() -> None:
    report = build_near_miss_promotion_gate_report(
        [
            (
                "120d.json",
                _smoke(
                    "near_miss_probe_00025_guarded",
                    decision="promote_to_full_walk_forward_evidence_probe_candidate",
                    d_return=-3,
                    d_dd=0,
                    d_adds=10,
                ),
            ),
            (
                "365d.json",
                _smoke(
                    "near_miss_probe_00025_guarded",
                    decision="reject_or_keep_for_manual_review",
                    d_return=-12,
                    d_dd=0,
                    d_adds=30,
                ),
            ),
        ],
        generated_at=datetime(2026, 6, 5, tzinfo=UTC),
    )

    assert report["overall_status"] == "no_candidate_promoted"
    assert report["candidates"][0]["status"] == "blocked"
    assert report["candidates"][0]["passed_window_count"] == 1
    assert report["candidates"][0]["failed_window_count"] == 1


def test_near_miss_promotion_gate_promotes_only_when_all_windows_pass() -> None:
    report = build_near_miss_promotion_gate_report(
        [
            (
                "120d.json",
                _smoke(
                    "near_miss_probe_00025_guarded",
                    decision="promote_to_full_walk_forward_evidence_probe_candidate",
                    d_return=-2,
                    d_dd=0,
                    d_adds=10,
                ),
            ),
            (
                "365d.json",
                _smoke(
                    "near_miss_probe_00025_guarded",
                    decision="promote_to_full_walk_forward_evidence_probe_candidate",
                    d_return=-4,
                    d_dd=1,
                    d_adds=30,
                ),
            ),
        ]
    )

    assert report["overall_status"] == "candidate_promoted"
    assert report["candidates"][0]["status"] == "promote_to_full_walk_forward"
