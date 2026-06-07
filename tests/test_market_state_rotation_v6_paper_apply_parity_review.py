import json
from datetime import UTC, datetime

from scripts.run_market_state_rotation_v6_paper_apply_parity_review import (
    REPORT_NAME,
    build_paper_apply_parity_review,
    main,
)


def _evidence(
    *,
    rows: int,
    missing: int,
    will_credit: bool,
    projected_rows: int | None = None,
    events_after_apply: int | None = None,
    apply_requested: bool = False,
    journal_jsonl: str | None = None,
    expected_action: str = "remove",
    expected_side: str = "short",
    source_event_ts: str = "2026-06-07T00:00:00+00:00",
) -> dict:
    payload = {
        "generated_at": "2026-06-07T00:00:00+00:00",
        "overall_status": "healthy_abstention_waiting_for_quality_signal",
        "no_live_order_sent": True,
        "collection_progress": {
            "execution_parity_journal_rows": rows,
            "execution_parity_missing_samples": missing,
            "paper_fill_rows": rows,
        },
        "paper_bridge_apply_gate": {
            "status": "paper_apply_requested" if apply_requested else "paper_apply_request_available",
            "apply_requested": apply_requested,
            "bridge_action": "remove",
            "fresh_signal": True,
            "can_request_paper_apply_now": not apply_requested,
        },
        "execution_parity_collection_plan": {
            "status": "ready_to_credit_next_paper_apply" if will_credit else "waiting_for_fresh_signal",
            "will_credit_current_apply_after_operator_review": will_credit,
            "projected_journal_rows_after_current_creditable_apply": projected_rows,
            "estimated_future_paper_apply_events_needed": missing,
            "estimated_events_needed_after_current_creditable_apply": events_after_apply,
            "currently_creditable_actions": ["remove"] if will_credit else [],
            "accepted_actions": ["add", "remove"],
            "execution_parity_preflight": {
                "expected_journal_action": expected_action,
                "expected_journal_side": expected_side,
                "source_event_ts": source_event_ts,
                "no_live_order_sent": True,
            },
            "non_substitutable": True,
            "no_live_order_sent": True,
        },
        "execution_parity_journal": {
            "conversion": {"journal_row_count": rows},
            "collection_plan": {"sample_count": rows, "missing_samples": missing},
            "contract_summary": {"sample_count": rows},
        },
    }
    if journal_jsonl is not None:
        payload["report_paths"] = {"execution_parity_journal_jsonl": journal_jsonl}
    return payload


def _write_jsonl(path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + ("\n" if rows else ""), encoding="utf-8")


def test_paper_apply_parity_review_confirms_expected_credit() -> None:
    report = build_paper_apply_parity_review(
        before_report=_evidence(rows=0, missing=20, will_credit=True, projected_rows=1, events_after_apply=19),
        after_report=_evidence(rows=1, missing=19, will_credit=False, apply_requested=True),
        input_before_report="before.json",
        input_after_report="after.json",
        generated_at=datetime(2026, 6, 7, tzinfo=UTC),
    )

    assert report["status"] == "paper_apply_parity_credit_confirmed"
    assert report["expected_credit_from_before_forecast"] == 1
    assert report["expected_after_journal_rows"] == 1
    assert report["actual_journal_row_delta"] == 1
    assert report["actual_missing_sample_delta"] == -1
    assert report["credit_confirmed"] is True
    assert report["no_live_order_sent"] is True


def test_paper_apply_parity_review_confirms_new_journal_row_identity(tmp_path) -> None:
    before_jsonl = tmp_path / "before.jsonl"
    after_jsonl = tmp_path / "after.jsonl"
    new_row = {
        "timestamp": "2026-06-07T00:01:00+00:00",
        "actual_action": "remove",
        "expected_action": "remove",
        "actual_side": "short",
        "expected_side": "short",
        "source_bar_ts": "2026-06-07T00:00:00+00:00",
        "decision_id": "client-1:exit",
    }
    _write_jsonl(before_jsonl, [])
    _write_jsonl(after_jsonl, [new_row])

    report = build_paper_apply_parity_review(
        before_report=_evidence(
            rows=0,
            missing=20,
            will_credit=True,
            projected_rows=1,
            events_after_apply=19,
            journal_jsonl=str(before_jsonl),
        ),
        after_report=_evidence(
            rows=1,
            missing=19,
            will_credit=False,
            apply_requested=True,
            journal_jsonl=str(after_jsonl),
        ),
        generated_at=datetime(2026, 6, 7, tzinfo=UTC),
    )

    assert report["status"] == "paper_apply_parity_credit_confirmed"
    assert report["new_journal_row_count"] == 1
    assert report["expected_journal_row_identity_check"]["matching_new_row_found"] is True
    assert report["expected_journal_row_identity_check"]["new_rows_checked"][0]["all_expected_fields_match"] is True


def test_paper_apply_parity_review_flags_new_journal_row_identity_mismatch(tmp_path) -> None:
    before_jsonl = tmp_path / "before.jsonl"
    after_jsonl = tmp_path / "after.jsonl"
    _write_jsonl(before_jsonl, [])
    _write_jsonl(
        after_jsonl,
        [
            {
                "timestamp": "2026-06-07T00:01:00+00:00",
                "actual_action": "add",
                "expected_action": "add",
                "actual_side": "long",
                "expected_side": "long",
                "source_bar_ts": "2026-06-07T00:00:00+00:00",
                "decision_id": "client-1",
            }
        ],
    )

    report = build_paper_apply_parity_review(
        before_report=_evidence(
            rows=0,
            missing=20,
            will_credit=True,
            projected_rows=1,
            events_after_apply=19,
            journal_jsonl=str(before_jsonl),
            expected_action="remove",
            expected_side="short",
        ),
        after_report=_evidence(
            rows=1,
            missing=19,
            will_credit=False,
            apply_requested=True,
            journal_jsonl=str(after_jsonl),
        ),
        generated_at=datetime(2026, 6, 7, tzinfo=UTC),
    )

    assert report["status"] == "paper_apply_parity_credit_missing"
    assert "new_execution_parity_journal_row_does_not_match_expected_signal" in report["blockers"]
    assert report["expected_journal_row_identity_check"]["matching_new_row_found"] is False
    assert "inspect_new_execution_parity_journal_row_identity" in report["next_actions"]


def test_paper_apply_parity_review_flags_missing_expected_credit() -> None:
    report = build_paper_apply_parity_review(
        before_report=_evidence(rows=0, missing=20, will_credit=True, projected_rows=1, events_after_apply=19),
        after_report=_evidence(rows=0, missing=20, will_credit=False, apply_requested=True),
        generated_at=datetime(2026, 6, 7, tzinfo=UTC),
    )

    assert report["status"] == "paper_apply_parity_credit_missing"
    assert "expected_execution_parity_credit_missing" in report["blockers"]
    assert "projected_execution_parity_journal_row_not_reached" in report["blockers"]
    assert report["credit_confirmed"] is False
    assert "inspect_paper_bridge_apply_result_and_lifecycle_export" in report["next_actions"]


def test_paper_apply_parity_review_flags_unexpected_credit_without_forecast() -> None:
    report = build_paper_apply_parity_review(
        before_report=_evidence(rows=0, missing=20, will_credit=False),
        after_report=_evidence(rows=1, missing=19, will_credit=False, apply_requested=True),
        generated_at=datetime(2026, 6, 7, tzinfo=UTC),
    )

    assert report["status"] == "unexpected_execution_parity_credit_review_required"
    assert "unexpected_execution_parity_credit_without_pre_apply_forecast" in report["blockers"]
    assert report["expected_credit_from_before_forecast"] == 0
    assert report["actual_journal_row_delta"] == 1


def test_paper_apply_parity_review_cli_writes_report(monkeypatch, tmp_path, capsys) -> None:
    before = tmp_path / "before.json"
    after = tmp_path / "after.json"
    report_dir = tmp_path / "review"
    before.write_text(
        json.dumps(_evidence(rows=0, missing=20, will_credit=True, projected_rows=1, events_after_apply=19)),
        encoding="utf-8",
    )
    after.write_text(json.dumps(_evidence(rows=1, missing=19, will_credit=False, apply_requested=True)), encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_market_state_rotation_v6_paper_apply_parity_review.py",
            "--before-evidence-report",
            str(before),
            "--after-evidence-report",
            str(after),
            "--report-dir",
            str(report_dir),
            "--write-report",
        ],
    )

    assert main() == 0
    payload = json.loads((report_dir / REPORT_NAME).read_text(encoding="utf-8"))
    assert payload["status"] == "paper_apply_parity_credit_confirmed"
    assert (report_dir / "market_state_rotation_v6_paper_apply_parity_review.md").exists()
    assert "paper_apply_parity_credit_confirmed" in capsys.readouterr().out
