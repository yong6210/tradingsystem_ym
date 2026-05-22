from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT_DIR / "scripts" / "run_sir_exit_shadow_review.py"
spec = importlib.util.spec_from_file_location("run_sir_exit_shadow_review", MODULE_PATH)
assert spec and spec.loader
shadow_review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shadow_review)


def _row(name: str, *, closed: int, total_r: float, score: float, cost_x2: float, max_dd: float = 10.0) -> dict:
    return {
        "policy": {"name": name},
        "summary": {
            "closed": closed,
            "total_r": total_r,
            "ev_r": total_r / max(closed, 1),
            "win_rate": 0.65,
            "max_dd_r": max_dd,
            "score": score,
        },
        "cost_stress": {"cost_x2_0": {"total_r": cost_x2}},
    }


def _report(*rows: dict, days: int = 1095) -> dict:
    return {
        "scope": {"days": days, "entry_delay_minutes": 0},
        "all_results": list(rows),
    }


def test_shadow_review_keeps_candidate_shadow_when_total_return_lags(tmp_path, monkeypatch) -> None:
    report_path = tmp_path / "report.json"
    report_path.write_text(
        shadow_review.json.dumps(
            _report(
                _row("legacy_full_2r", closed=100, total_r=100.0, score=90.0, cost_x2=80.0),
                _row("important_zone", closed=100, total_r=92.0, score=110.0, cost_x2=70.0),
            )
        )
    )
    monkeypatch.setattr(shadow_review, "get_settings", lambda: type("S", (), {"session_impulse_retest_exit_policy_name": "legacy_full_2r"})())

    payload = shadow_review.build_payload(
        baseline_policy="legacy_full_2r",
        candidate_policies=["important_zone"],
        validation_reports=[report_path],
        generated_at=datetime(2026, 5, 19, tzinfo=UTC),
    )

    assert payload["decision"] == "KEEP_CURRENT_LIVE_ROUTE_UNCHANGED"
    assert payload["overall_status"] == "PASS"
    assert payload["authority"] == "sir_exit_shadow_review_only_no_order_submission"
    assert payload["live_action"] == "KEEP_CURRENT_LIVE_ROUTE_UNCHANGED"
    assert payload["live_ready"] is False
    assert payload["order_submission_allowed"] is False
    assert payload["order_submission_authority"] == "shadow_review_has_no_live_order_authority"
    assert payload["live_exit_policy"] == "legacy_full_2r"
    assert payload["baseline_policy"] == "legacy_full_2r"
    assert payload["comparison_baseline_is_current_live_policy"] is True
    assert payload["live_policy_present_in_validation_reports"] is True
    assert payload["candidate_action"] == "SHADOW_ONLY"
    assert payload["operator_summary"]["order_submission_allowed"] is False
    assert payload["operator_summary"]["action"].startswith("Keep the current live route unchanged")
    assert payload["candidates"][0]["candidate_policy"] == "important_zone"
    review = payload["candidates"][0]["report_reviews"][0]
    assert "total_r_does_not_beat_live_baseline" in review["reasons"]
    assert "risk_adjusted_improvement_only_total_return_lower" in review["reasons"]


def test_shadow_review_warns_when_baseline_is_not_current_live_policy(tmp_path, monkeypatch) -> None:
    report_path = tmp_path / "report.json"
    report_path.write_text(
        shadow_review.json.dumps(
            _report(
                _row("legacy_full_2r", closed=100, total_r=100.0, score=90.0, cost_x2=80.0),
                _row("important_zone", closed=100, total_r=92.0, score=110.0, cost_x2=70.0),
            )
        )
    )
    monkeypatch.setattr(
        shadow_review,
        "get_settings",
        lambda: type("S", (), {"session_impulse_retest_exit_policy_name": "structure_buffered_live"})(),
    )

    payload = shadow_review.build_payload(
        baseline_policy="legacy_full_2r",
        candidate_policies=["important_zone"],
        validation_reports=[report_path],
        generated_at=datetime(2026, 5, 19, tzinfo=UTC),
    )

    assert payload["decision"] == "KEEP_CURRENT_LIVE_ROUTE_UNCHANGED"
    assert payload["comparison_baseline_is_current_live_policy"] is False
    assert payload["live_policy_present_in_validation_reports"] is False
    assert payload["comparison_scope_status"] == (
        "comparison_baseline_not_current_live_policy:live_policy_not_in_validation_reports"
    )
    assert payload["operator_summary"]["comparison_scope_status"] == payload["comparison_scope_status"]


def test_shadow_review_marks_candidate_ready_only_when_all_reports_beat_baseline(tmp_path, monkeypatch) -> None:
    report_3y = tmp_path / "report_3y.json"
    report_5y = tmp_path / "report_5y.json"
    for path, days in ((report_3y, 1095), (report_5y, 1825)):
        path.write_text(
            shadow_review.json.dumps(
                _report(
                    _row("legacy_full_2r", closed=100, total_r=100.0, score=90.0, cost_x2=80.0),
                    _row("important_zone", closed=100, total_r=104.0, score=91.0, cost_x2=82.0),
                    days=days,
                )
            )
        )
    monkeypatch.setattr(shadow_review, "get_settings", lambda: type("S", (), {"session_impulse_retest_exit_policy_name": "legacy_full_2r"})())

    payload = shadow_review.build_payload(
        baseline_policy="legacy_full_2r",
        candidate_policies=["important_zone"],
        validation_reports=[report_3y, report_5y],
        generated_at=datetime(2026, 5, 19, tzinfo=UTC),
    )

    assert payload["decision"] == "PROMOTE_CANDIDATE_TO_PAPER_REVIEW"
    assert payload["overall_status"] == "WATCH"
    assert payload["candidate_action"] == "PAPER_REVIEW_REQUIRED_BEFORE_LIVE"
    assert payload["promotion_ready_candidates"][0]["policy"] == "important_zone"


def test_shadow_review_keeps_baseline_when_validation_report_is_missing(tmp_path, monkeypatch) -> None:
    missing_path = tmp_path / "missing.json"
    monkeypatch.setattr(shadow_review, "get_settings", lambda: type("S", (), {"session_impulse_retest_exit_policy_name": "legacy_full_2r"})())

    payload = shadow_review.build_payload(
        baseline_policy="legacy_full_2r",
        candidate_policies=["important_zone"],
        validation_reports=[missing_path],
        generated_at=datetime(2026, 5, 19, tzinfo=UTC),
    )

    assert payload["decision"] == "KEEP_CURRENT_LIVE_ROUTE_UNCHANGED"
    assert payload["candidate_action"] == "SHADOW_ONLY"
    review = payload["candidates"][0]["report_reviews"][0]
    assert review["status"] == "MISSING"
    assert review["reasons"] == ["validation_report_missing"]


def test_shadow_review_resolves_reports_from_runtime_parent(tmp_path, monkeypatch) -> None:
    runtime_src = tmp_path / "runtime_src"
    app_root = tmp_path
    report_path = app_root / "reports/validation/example/latest.json"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(
        shadow_review.json.dumps(
            _report(
                _row("legacy_full_2r", closed=100, total_r=100.0, score=90.0, cost_x2=80.0),
                _row("important_zone", closed=100, total_r=104.0, score=91.0, cost_x2=82.0),
            )
        )
    )
    monkeypatch.setattr(shadow_review, "ROOT_DIR", runtime_src)

    resolved = shadow_review._resolve_path("reports/validation/example/latest.json")

    assert resolved == report_path


def test_shadow_review_output_path_stays_under_runtime_root(tmp_path, monkeypatch) -> None:
    runtime_src = tmp_path / "runtime_src"
    workspace = tmp_path / "Documents/trading"
    existing_workspace_report_dir = workspace / "reports/operations/sir_exit_shadow_review"
    existing_workspace_report_dir.mkdir(parents=True)
    monkeypatch.setattr(shadow_review, "ROOT_DIR", runtime_src)
    monkeypatch.setattr(shadow_review.Path, "home", lambda: tmp_path)

    resolved = shadow_review._resolve_output_path("reports/operations/sir_exit_shadow_review")

    assert resolved == runtime_src / "reports/operations/sir_exit_shadow_review"
