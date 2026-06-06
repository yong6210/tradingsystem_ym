import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from scripts.run_market_state_rotation_v6_safety_evidence_collect import (
    build_safety_evidence_collection_report,
)


def _write(path: Path, payload: dict) -> str:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def _report_paths(tmp_path: Path, generated_at: str) -> dict[str, str]:
    return {
        "live_leverage_cap_sync": _write(
            tmp_path / "leverage.json",
            {
                "generated_at": generated_at,
                "overall_status": "OK",
                "pending_count": 0,
                "fail_count": 0,
                "target_leverage": 10,
                "configured_leverage_cap": 10,
            },
        ),
        "live_reconciliation_watchdog": _write(
            tmp_path / "reconciliation.json",
            {
                "generated_at": generated_at,
                "overall_status": "OK",
                "evaluation": {
                    "status": "OK",
                    "issue_count": 0,
                    "fail_count": 0,
                },
            },
        ),
        "live_account_protection": _write(
            tmp_path / "protection.json",
            {
                "generated_at": generated_at,
                "overall_status": "OK",
                "fail_count": 0,
                "issue_count": 0,
                "open_position_count": 0,
            },
        ),
        "micro_live_runtime_guard": _write(
            tmp_path / "runtime.json",
            {
                "generated_at": generated_at,
                "overall_status": "PASS",
                "checks": [
                    {"name": "live_protection_config", "status": "PASS"},
                    {"name": "session_impulse_retest_exit_contract", "status": "PASS"},
                    {"name": "macro_blackout_contract", "status": "PASS"},
                    {"name": "macro_blackout_live_coverage", "status": "PASS"},
                    {"name": "macro_blackout_horizon", "status": "PASS"},
                ],
            },
        ),
        "micro_live_failure_drill": _write(
            tmp_path / "failure.json",
            {
                "generated_at": generated_at,
                "overall_status": "PASS",
                "scenario_count": 8,
                "failed_count": 0,
            },
        ),
        "micro_live_synthetic_canary": _write(
            tmp_path / "canary.json",
            {
                "generated_at": generated_at,
                "overall_status": "PASS",
                "checks": [],
            },
        ),
    }


def test_safety_evidence_collector_maps_fresh_operation_reports(tmp_path: Path) -> None:
    now = datetime(2026, 1, 2, 0, 0, tzinfo=UTC)
    generated_at = (now - timedelta(hours=1)).isoformat()
    report = build_safety_evidence_collection_report(
        report_paths=_report_paths(tmp_path, generated_at),
        now=now,
        max_report_age_hours=24,
    )

    controls = report["controls"]
    assert controls["leverage_cap_verified"]["verified"] is True
    assert controls["position_sync_verified"]["verified"] is True
    assert controls["reduce_only_exit_verified"]["verified"] is True
    assert controls["partial_fill_handling_verified"]["verified"] is True
    assert controls["maintenance_window_block_verified"]["verified"] is True
    assert controls["exchange_reject_handling_verified"]["verified"] is True
    assert controls["stale_signal_block_verified"]["verified"] is True
    assert report["verified_count"] == 7
    assert "kill_switch_verified" in report["missing_or_failed"]
    assert "max_daily_loss_verified" in report["missing_or_failed"]
    assert "idempotent_client_order_id_verified" in report["missing_or_failed"]


def test_safety_evidence_collector_blocks_stale_operation_reports(tmp_path: Path) -> None:
    now = datetime(2026, 1, 2, 0, 0, tzinfo=UTC)
    generated_at = (now - timedelta(hours=48)).isoformat()
    report = build_safety_evidence_collection_report(
        report_paths=_report_paths(tmp_path, generated_at),
        now=now,
        max_report_age_hours=24,
    )

    assert report["verified_count"] == 0
    assert report["controls"]["leverage_cap_verified"]["verified"] is False
    assert report["source_reports"]["live_leverage_cap_sync"]["fresh"] is False
    assert "source_report_stale" in report["controls"]["leverage_cap_verified"]["blockers"]


def test_safety_evidence_collector_merges_manual_evidence(tmp_path: Path) -> None:
    now = datetime(2026, 1, 2, 0, 0, tzinfo=UTC)
    generated_at = (now - timedelta(hours=1)).isoformat()
    manual = {
        "controls": {
            "kill_switch_verified": {
                "verified": True,
                "verified_at": generated_at,
                "evidence": "kill switch drill passed",
            }
        }
    }
    report = build_safety_evidence_collection_report(
        report_paths=_report_paths(tmp_path, generated_at),
        manual_evidence=manual,
        now=now,
        max_report_age_hours=24,
    )

    assert report["controls"]["kill_switch_verified"]["verified"] is True
    assert "kill_switch_verified" not in report["missing_or_failed"]
