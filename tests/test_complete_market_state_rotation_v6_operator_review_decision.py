import json
import hashlib
from datetime import UTC, datetime

from scripts.complete_market_state_rotation_v6_operator_review_decision import (
    complete_operator_review_decision,
)


def _fingerprint_payload(payload: dict[str, object]) -> str:
    normalized = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _draft_metadata(
    output_report,
    *,
    status: str = "operator_review_accepted_or_rejected",
    identity: dict[str, object] | None = None,
) -> dict[str, object]:
    skeleton = output_report.parent / f"{output_report.stem}_skeleton.json"
    skeleton_payload = {
        "status": status,
        "order_submission_allowed": False,
        "no_live_order_sent": True,
    }
    skeleton_payload.update(identity or {})
    skeleton.write_text(json.dumps(skeleton_payload), encoding="utf-8")
    return {
        "status": "operator_review_draft_prepared",
        "source_skeleton_report": str(skeleton),
        "source_skeleton_fingerprint": _fingerprint_payload(skeleton_payload),
        "source_skeleton_fingerprint_algorithm": "sha256-json-v1",
        "source_skeleton_fingerprint_required": True,
        "output_report": str(output_report),
        "generated_at": "2026-01-01T12:00:00+00:00",
        "operator_must_choose_accept_or_reject": True,
        "auto_accept_allowed": False,
        "min_rationale_chars": 30,
        "min_evidence_anchors": 1,
        "order_submission_allowed": False,
        "no_live_order_sent": True,
    }


def test_complete_operator_review_decision_accepts_explicit_operator_decision(tmp_path) -> None:
    review = tmp_path / "draft.json"
    output = tmp_path / "completed.json"
    skeleton = review.parent / "draft_skeleton.json"
    expected_skeleton_fingerprint = _fingerprint_payload(
        {
            "status": "conditional_overfit_review_accepted_or_rejected",
            "order_submission_allowed": False,
            "no_live_order_sent": True,
            "candidate_recipe_id": "conditional_refill_formal",
            "source_promotion_gate_generated_at": "2026-01-01T12:00:00+00:00",
        }
    )
    review.write_text(
        json.dumps(
            {
                "status": "conditional_overfit_review_accepted_or_rejected",
                "draft_metadata": _draft_metadata(
                    review,
                    status="conditional_overfit_review_accepted_or_rejected",
                    identity={
                        "candidate_recipe_id": "conditional_refill_formal",
                        "source_promotion_gate_generated_at": "2026-01-01T12:00:00+00:00",
                    },
                ),
                "candidate_recipe_id": "conditional_refill_formal",
                "source_promotion_gate_generated_at": "2026-01-01T12:00:00+00:00",
                "reviewer": "operator_name_or_initials",
                "reviewed_at": "iso8601_timestamp_after_source_promotion_gate_generated_at",
                "rationale": "why_the_conditional_overlay_proxy_evidence_is_accepted_or_rejected_for_paper_only",
                "order_submission_allowed": False,
                "no_live_order_sent": True,
            }
        ),
        encoding="utf-8",
    )

    summary = complete_operator_review_decision(
        review_report=review,
        output_report=output,
        decision="accept",
        reviewer="op",
        rationale=(
            "conditional_refill_formal historical proxy is accepted for paper-only routing review; "
            "live still requires realtime gates."
        ),
        reviewed_at="2026-01-01T12:05:00+00:00",
        generated_at=datetime(2026, 1, 1, 12, 10, tzinfo=UTC),
    )

    assert summary == {
        "status": "operator_review_decision_completed",
        "created": True,
        "review_report": str(review),
        "output_report": str(output),
        "backup_report": None,
        "backup_created": False,
        "decision": "accept",
        "new_status": "conditional_overfit_review_accepted",
        "blockers": [],
        "next_action": "run_validation_command_for_completed_operator_review",
        "order_submission_allowed": False,
        "no_live_order_sent": True,
    }
    completed = json.loads(output.read_text(encoding="utf-8"))
    assert completed["status"] == "conditional_overfit_review_accepted"
    assert completed["reviewer"] == "op"
    assert completed["reviewed_at"] == "2026-01-01T12:05:00+00:00"
    assert completed["order_submission_allowed"] is False
    assert completed["no_live_order_sent"] is True
    assert completed["decision_metadata"]["auto_accept_allowed"] is False
    assert completed["decision_metadata"]["decision"] == "accept"
    assert completed["decision_metadata"]["draft_status"] == "operator_review_draft_prepared"
    assert completed["decision_metadata"]["draft_metadata_required"] is True
    assert completed["decision_metadata"]["draft_metadata_quality"] == {
        "status": "pass",
        "draft_status": "operator_review_draft_prepared",
        "source_skeleton_report": str(skeleton),
        "output_report": str(review),
        "generated_at": "2026-01-01T12:00:00+00:00",
        "min_rationale_chars": 30,
        "min_evidence_anchors": 1,
        "max_future_minutes": 5.0,
        "source_skeleton_quality": {
            "status": "pass",
            "source_skeleton_report": str(skeleton),
            "resolved_source_skeleton_report": str(skeleton),
            "source_status": "conditional_overfit_review_accepted_or_rejected",
            "draft_status": "conditional_overfit_review_accepted_or_rejected",
            "identity_checked_keys": [
                "candidate_recipe_id",
                "source_promotion_gate_generated_at",
            ],
            "identity_mismatch_keys": [],
            "source_skeleton_fingerprint_required": True,
            "source_skeleton_fingerprint_algorithm": "sha256-json-v1",
            "expected_source_skeleton_fingerprint": expected_skeleton_fingerprint,
            "actual_source_skeleton_fingerprint": expected_skeleton_fingerprint,
            "source_skeleton_fingerprint_checked": True,
            "blockers": [],
        },
        "blockers": [],
    }
    assert completed["decision_metadata"]["min_rationale_chars"] == 30
    assert completed["decision_metadata"]["min_evidence_anchors"] == 1
    assert completed["decision_metadata"]["rationale_quality"]["status"] == "pass"
    assert completed["decision_metadata"]["rationale_quality"]["matched_evidence_anchor_count"] == 1
    assert completed["decision_metadata"]["rationale_decision_alignment"] == {
        "status": "pass",
        "decision": "accept",
        "conflict_patterns": [],
        "blockers": [],
    }
    assert completed["decision_metadata"]["reviewed_at_quality"] == {
        "status": "pass",
        "source_check_applied": True,
        "source_promotion_gate_generated_at": "2026-01-01T12:00:00+00:00",
        "reviewed_at": "2026-01-01T12:05:00+00:00",
        "generated_at": "2026-01-01T12:10:00+00:00",
        "max_future_minutes": 5.0,
        "blockers": [],
    }


def test_complete_operator_review_decision_allows_regenerated_current_skeleton_timestamp(tmp_path) -> None:
    review = tmp_path / "draft.json"
    output = tmp_path / "completed.json"
    skeleton = tmp_path / "draft_skeleton.json"
    snapshot_payload = {
        "status": "conditional_overfit_review_accepted_or_rejected",
        "candidate_recipe_id": "conditional_refill_formal",
        "review_packet_fingerprint": "abcdef1234567890abcdef1234567890",
        "source_promotion_gate_report": "reports/gate.json",
        "source_promotion_gate_generated_at": "2026-01-01T12:00:00+00:00",
        "order_submission_allowed": False,
        "no_live_order_sent": True,
    }
    snapshot_fingerprint = _fingerprint_payload(snapshot_payload)
    current_skeleton_payload = dict(snapshot_payload)
    current_skeleton_payload["source_promotion_gate_generated_at"] = "2026-01-01T12:08:00+00:00"
    skeleton.write_text(json.dumps(current_skeleton_payload), encoding="utf-8")
    review.write_text(
        json.dumps(
            {
                "status": "conditional_overfit_review_accepted_or_rejected",
                "draft_metadata": {
                    "status": "operator_review_draft_prepared",
                    "source_skeleton_report": str(skeleton),
                    "source_skeleton_fingerprint": snapshot_fingerprint,
                    "source_skeleton_fingerprint_algorithm": "sha256-json-v1",
                    "source_skeleton_fingerprint_required": True,
                    "source_skeleton_snapshot": snapshot_payload,
                    "source_skeleton_snapshot_fingerprint": snapshot_fingerprint,
                    "source_skeleton_snapshot_fingerprint_algorithm": "sha256-json-v1",
                    "output_report": str(review),
                    "generated_at": "2026-01-01T12:01:00+00:00",
                    "operator_must_choose_accept_or_reject": True,
                    "auto_accept_allowed": False,
                    "min_rationale_chars": 30,
                    "min_evidence_anchors": 1,
                    "order_submission_allowed": False,
                    "no_live_order_sent": True,
                },
                "candidate_recipe_id": "conditional_refill_formal",
                "review_packet_fingerprint": "abcdef1234567890abcdef1234567890",
                "source_promotion_gate_report": "reports/gate.json",
                "source_promotion_gate_generated_at": "2026-01-01T12:00:00+00:00",
                "order_submission_allowed": False,
                "no_live_order_sent": True,
            }
        ),
        encoding="utf-8",
    )

    summary = complete_operator_review_decision(
        review_report=review,
        output_report=output,
        decision="accept",
        reviewer="op",
        rationale="conditional_refill_formal is accepted for paper-only review after checking the proxy packet.",
        reviewed_at="2026-01-01T12:05:00+00:00",
        generated_at=datetime(2026, 1, 1, 12, 10, tzinfo=UTC),
    )

    assert summary["status"] == "operator_review_decision_completed"
    completed = json.loads(output.read_text(encoding="utf-8"))
    source_quality = completed["decision_metadata"]["draft_metadata_quality"]["source_skeleton_quality"]
    assert source_quality["status"] == "pass"
    assert source_quality["source_skeleton_validation_source"] == "embedded_snapshot"
    assert source_quality["actual_source_skeleton_fingerprint"] == snapshot_fingerprint
    assert source_quality["actual_source_skeleton_snapshot_fingerprint"] == snapshot_fingerprint
    assert source_quality["current_source_skeleton_fingerprint_matches_snapshot"] is False
    assert source_quality["current_identity_mismatch_keys"] == []
    assert source_quality["blockers"] == []
    assert completed["order_submission_allowed"] is False
    assert completed["no_live_order_sent"] is True


def test_complete_operator_review_decision_blocks_regenerated_current_skeleton_material_change(tmp_path) -> None:
    review = tmp_path / "draft.json"
    output = tmp_path / "completed.json"
    skeleton = tmp_path / "draft_skeleton.json"
    snapshot_payload = {
        "status": "conditional_overfit_review_accepted_or_rejected",
        "candidate_recipe_id": "conditional_refill_formal",
        "review_packet_fingerprint": "abcdef1234567890abcdef1234567890",
        "source_promotion_gate_report": "reports/gate.json",
        "source_promotion_gate_generated_at": "2026-01-01T12:00:00+00:00",
        "order_submission_allowed": False,
        "no_live_order_sent": True,
    }
    snapshot_fingerprint = _fingerprint_payload(snapshot_payload)
    current_skeleton_payload = dict(snapshot_payload)
    current_skeleton_payload["candidate_recipe_id"] = "different_candidate"
    current_skeleton_payload["source_promotion_gate_generated_at"] = "2026-01-01T12:08:00+00:00"
    skeleton.write_text(json.dumps(current_skeleton_payload), encoding="utf-8")
    review.write_text(
        json.dumps(
            {
                "status": "conditional_overfit_review_accepted_or_rejected",
                "draft_metadata": {
                    "status": "operator_review_draft_prepared",
                    "source_skeleton_report": str(skeleton),
                    "source_skeleton_fingerprint": snapshot_fingerprint,
                    "source_skeleton_fingerprint_algorithm": "sha256-json-v1",
                    "source_skeleton_fingerprint_required": True,
                    "source_skeleton_snapshot": snapshot_payload,
                    "source_skeleton_snapshot_fingerprint": snapshot_fingerprint,
                    "source_skeleton_snapshot_fingerprint_algorithm": "sha256-json-v1",
                    "output_report": str(review),
                    "generated_at": "2026-01-01T12:01:00+00:00",
                    "operator_must_choose_accept_or_reject": True,
                    "auto_accept_allowed": False,
                    "min_rationale_chars": 30,
                    "min_evidence_anchors": 1,
                    "order_submission_allowed": False,
                    "no_live_order_sent": True,
                },
                "candidate_recipe_id": "conditional_refill_formal",
                "review_packet_fingerprint": "abcdef1234567890abcdef1234567890",
                "source_promotion_gate_report": "reports/gate.json",
                "source_promotion_gate_generated_at": "2026-01-01T12:00:00+00:00",
                "order_submission_allowed": False,
                "no_live_order_sent": True,
            }
        ),
        encoding="utf-8",
    )

    summary = complete_operator_review_decision(
        review_report=review,
        output_report=output,
        decision="accept",
        reviewer="op",
        rationale="conditional_refill_formal is accepted for paper-only review after checking the proxy packet.",
        reviewed_at="2026-01-01T12:05:00+00:00",
        generated_at=datetime(2026, 1, 1, 12, 10, tzinfo=UTC),
    )

    assert summary["status"] == "blocked_invalid_operator_decision"
    assert "current_source_skeleton_material_identity_mismatch" in summary["blockers"]
    source_quality = summary["draft_metadata_quality"]["source_skeleton_quality"]
    assert source_quality["identity_mismatch_keys"] == []
    assert source_quality["current_identity_mismatch_keys"] == ["candidate_recipe_id"]
    assert not output.exists()
    assert summary["order_submission_allowed"] is False
    assert summary["no_live_order_sent"] is True


def test_complete_operator_review_decision_rejects_without_enabling_orders(tmp_path) -> None:
    review = tmp_path / "draft.json"
    output = tmp_path / "completed.json"
    review.write_text(
        json.dumps(
            {
                "status": "operator_lineage_review_accepted_or_rejected",
                "draft_metadata": _draft_metadata(review, status="operator_lineage_review_accepted_or_rejected"),
                "order_submission_allowed": False,
                "no_live_order_sent": True,
            }
        ),
        encoding="utf-8",
    )

    summary = complete_operator_review_decision(
        review_report=review,
        output_report=output,
        decision="reject",
        reviewer="op",
        rationale="Reject defensive route activation until additional paper parity rows exist.",
        generated_at=datetime(2026, 1, 1, 12, 10, tzinfo=UTC),
    )

    completed = json.loads(output.read_text(encoding="utf-8"))
    assert summary["status"] == "operator_review_decision_completed"
    assert summary["new_status"] == "operator_lineage_review_rejected"
    assert completed["status"] == "operator_lineage_review_rejected"
    assert completed["reviewed_at"] == "2026-01-01T12:10:00+00:00"
    assert completed["order_submission_allowed"] is False
    assert completed["no_live_order_sent"] is True


def test_complete_operator_review_decision_dry_run_does_not_write_files(tmp_path) -> None:
    review = tmp_path / "draft.json"
    output = tmp_path / "completed.json"
    review.write_text(
        json.dumps(
            {
                "status": "operator_review_accepted_or_rejected",
                "draft_metadata": _draft_metadata(review),
                "order_submission_allowed": False,
                "no_live_order_sent": True,
            }
        ),
        encoding="utf-8",
    )

    summary = complete_operator_review_decision(
        review_report=review,
        output_report=output,
        decision="accept",
        reviewer="op",
        rationale="Preview the decision without writing the completed review.",
        dry_run=True,
        generated_at=datetime(2026, 1, 1, 12, 10, tzinfo=UTC),
    )

    assert summary == {
        "status": "operator_review_decision_dry_run",
        "created": False,
        "would_create": True,
        "review_report": str(review),
        "output_report": str(output),
        "backup_report": None,
        "backup_would_be_created": False,
        "decision": "accept",
        "new_status": "operator_review_accepted",
        "blockers": [],
        "rationale_quality": {
            "status": "pass",
            "min_evidence_anchors": 1,
            "available_evidence_anchor_count": 0,
            "matched_evidence_anchor_count": 0,
            "matched_evidence_anchors": [],
            "evidence_anchor_check_applied": False,
        },
        "rationale_decision_alignment": {
            "status": "pass",
            "decision": "accept",
            "conflict_patterns": [],
            "blockers": [],
        },
        "reviewed_at_quality": {
            "status": "pass",
            "source_check_applied": False,
            "source_promotion_gate_generated_at": None,
            "reviewed_at": "2026-01-01T12:10:00+00:00",
            "generated_at": "2026-01-01T12:10:00+00:00",
            "max_future_minutes": 5.0,
            "blockers": [],
        },
        "next_action": "rerun_without_dry_run_to_write_completed_operator_review",
        "order_submission_allowed": False,
        "no_live_order_sent": True,
    }
    assert not output.exists()
    assert json.loads(review.read_text(encoding="utf-8"))["status"] == "operator_review_accepted_or_rejected"


def test_complete_operator_review_decision_in_place_requires_and_creates_backup(tmp_path) -> None:
    review = tmp_path / "draft.json"
    backup_dir = tmp_path / "backups"
    review.write_text(
        json.dumps(
            {
                "status": "operator_review_accepted_or_rejected",
                "draft_metadata": _draft_metadata(review),
                "order_submission_allowed": False,
                "no_live_order_sent": True,
            }
        ),
        encoding="utf-8",
    )

    blocked = complete_operator_review_decision(
        review_report=review,
        output_report=review,
        decision="accept",
        reviewer="op",
        rationale="Accept for paper-only operator review.",
        generated_at=datetime(2026, 1, 1, 12, 10, tzinfo=UTC),
    )

    assert blocked["status"] == "blocked_invalid_operator_decision"
    assert blocked["blockers"] == ["in_place_decision_requires_backup_dir"]
    assert json.loads(review.read_text(encoding="utf-8"))["status"] == "operator_review_accepted_or_rejected"

    summary = complete_operator_review_decision(
        review_report=review,
        output_report=review,
        decision="accept",
        reviewer="op",
        rationale="Accept for paper-only operator review.",
        backup_dir=backup_dir,
        generated_at=datetime(2026, 1, 1, 12, 10, tzinfo=UTC),
    )

    backup = backup_dir / "draft.json.20260101T121000Z.bak"
    assert summary["status"] == "operator_review_decision_completed"
    assert summary["backup_report"] == str(backup)
    assert summary["backup_created"] is True
    assert json.loads(backup.read_text(encoding="utf-8"))["status"] == "operator_review_accepted_or_rejected"
    assert json.loads(review.read_text(encoding="utf-8"))["status"] == "operator_review_accepted"


def test_complete_operator_review_decision_in_place_dry_run_does_not_create_backup(tmp_path) -> None:
    review = tmp_path / "draft.json"
    backup_dir = tmp_path / "backups"
    review.write_text(
        json.dumps(
            {
                "status": "operator_review_accepted_or_rejected",
                "draft_metadata": _draft_metadata(review),
                "order_submission_allowed": False,
                "no_live_order_sent": True,
            }
        ),
        encoding="utf-8",
    )

    summary = complete_operator_review_decision(
        review_report=review,
        output_report=review,
        decision="reject",
        reviewer="op",
        rationale="Preview rejection without mutating the draft.",
        backup_dir=backup_dir,
        dry_run=True,
        generated_at=datetime(2026, 1, 1, 12, 10, tzinfo=UTC),
    )

    backup = backup_dir / "draft.json.20260101T121000Z.bak"
    assert summary["status"] == "operator_review_decision_dry_run"
    assert summary["backup_report"] == str(backup)
    assert summary["backup_would_be_created"] is True
    assert not backup.exists()
    assert json.loads(review.read_text(encoding="utf-8"))["status"] == "operator_review_accepted_or_rejected"


def test_complete_operator_review_decision_blocks_placeholders_and_unsafe_report(tmp_path) -> None:
    review = tmp_path / "draft.json"
    output = tmp_path / "completed.json"
    review.write_text(
        json.dumps(
            {
                "status": "operator_review_accepted_or_rejected",
                "draft_metadata": _draft_metadata(review),
                "reviewer": "operator_name_or_initials",
                "rationale": "why_placeholder",
                "order_submission_allowed": True,
                "no_live_order_sent": False,
            }
        ),
        encoding="utf-8",
    )

    summary = complete_operator_review_decision(
        review_report=review,
        output_report=output,
        decision="accept",
        reviewer="operator_name_or_initials",
        rationale="why_placeholder",
        generated_at=datetime(2026, 1, 1, 12, 10, tzinfo=UTC),
    )

    assert summary["status"] == "blocked_invalid_operator_decision"
    assert summary["created"] is False
    assert summary["blockers"] == [
        "review_report_no_live_order_sent_not_true",
        "review_report_order_submission_allowed_not_false",
        "reviewer_required",
        "rationale_required",
    ]
    assert not output.exists()
    assert summary["order_submission_allowed"] is False
    assert summary["no_live_order_sent"] is True


def test_complete_operator_review_decision_blocks_missing_draft_metadata(tmp_path) -> None:
    review = tmp_path / "draft.json"
    output = tmp_path / "completed.json"
    review.write_text(
        json.dumps(
            {
                "status": "operator_review_accepted_or_rejected",
                "order_submission_allowed": False,
                "no_live_order_sent": True,
            }
        ),
        encoding="utf-8",
    )

    summary = complete_operator_review_decision(
        review_report=review,
        output_report=output,
        decision="accept",
        reviewer="op",
        rationale="Prepared review must come from the draft preparation tool before completion.",
        generated_at=datetime(2026, 1, 1, 12, 10, tzinfo=UTC),
    )

    assert summary["status"] == "blocked_invalid_operator_decision"
    assert summary["blockers"] == ["review_report_draft_metadata_missing_or_invalid"]
    assert not output.exists()
    assert summary["order_submission_allowed"] is False
    assert summary["no_live_order_sent"] is True


def test_complete_operator_review_decision_blocks_invalid_draft_metadata_contract(tmp_path) -> None:
    review = tmp_path / "draft.json"
    output = tmp_path / "completed.json"
    draft_metadata = _draft_metadata(review)
    draft_metadata.update(
        {
            "operator_must_choose_accept_or_reject": False,
            "auto_accept_allowed": True,
            "order_submission_allowed": True,
            "no_live_order_sent": False,
            "min_rationale_chars": 10,
            "min_evidence_anchors": 0,
            "source_skeleton_report": "",
            "output_report": "other.json",
            "generated_at": "2026-01-01T12:20:00+00:00",
        }
    )
    review.write_text(
        json.dumps(
            {
                "status": "operator_review_accepted_or_rejected",
                "draft_metadata": draft_metadata,
                "order_submission_allowed": False,
                "no_live_order_sent": True,
            }
        ),
        encoding="utf-8",
    )

    summary = complete_operator_review_decision(
        review_report=review,
        output_report=output,
        decision="accept",
        reviewer="op",
        rationale="Prepared review metadata safety contract must remain intact before completion.",
        generated_at=datetime(2026, 1, 1, 12, 10, tzinfo=UTC),
    )

    assert summary["status"] == "blocked_invalid_operator_decision"
    assert summary["blockers"] == [
        "draft_metadata_operator_must_choose_accept_or_reject_not_true",
        "draft_metadata_auto_accept_allowed_not_false",
        "draft_metadata_order_submission_allowed_not_false",
        "draft_metadata_no_live_order_sent_not_true",
        "draft_metadata_min_rationale_chars_missing_or_too_low",
        "draft_metadata_min_evidence_anchors_missing_or_too_low",
        "draft_metadata_source_skeleton_report_missing",
        "draft_metadata_output_report_mismatch",
        "draft_metadata_generated_at_in_future",
    ]
    assert summary["draft_metadata_quality"]["status"] == "fail"
    assert not output.exists()
    assert summary["order_submission_allowed"] is False
    assert summary["no_live_order_sent"] is True


def test_complete_operator_review_decision_blocks_invalid_source_skeleton(tmp_path) -> None:
    review = tmp_path / "draft.json"
    output = tmp_path / "completed.json"
    draft_metadata = _draft_metadata(
        review,
        identity={"candidate_recipe_id": "draft_candidate"},
    )
    skeleton = draft_metadata["source_skeleton_report"]
    expected_skeleton_fingerprint = str(draft_metadata["source_skeleton_fingerprint"])
    review.write_text(
        json.dumps(
            {
                "status": "operator_review_accepted_or_rejected",
                "draft_metadata": draft_metadata,
                "candidate_recipe_id": "draft_candidate",
                "order_submission_allowed": False,
                "no_live_order_sent": True,
            }
        ),
        encoding="utf-8",
    )
    mutated_skeleton_payload = {
        "status": "operator_review_accepted",
        "candidate_recipe_id": "other_candidate",
        "order_submission_allowed": True,
        "no_live_order_sent": False,
    }
    tmp_path.joinpath("draft_skeleton.json").write_text(
        json.dumps(mutated_skeleton_payload),
        encoding="utf-8",
    )

    summary = complete_operator_review_decision(
        review_report=review,
        output_report=output,
        decision="accept",
        reviewer="op",
        rationale="draft_candidate source skeleton validation must pass before completion.",
        generated_at=datetime(2026, 1, 1, 12, 10, tzinfo=UTC),
    )

    assert summary["status"] == "blocked_invalid_operator_decision"
    assert summary["blockers"] == [
        "source_skeleton_fingerprint_mismatch",
        "source_skeleton_no_live_order_sent_not_true",
        "source_skeleton_order_submission_allowed_not_false",
        "source_skeleton_status_is_not_operator_decision_placeholder",
        "source_skeleton_status_mismatch",
        "source_skeleton_identity_mismatch",
    ]
    assert summary["draft_metadata_quality"]["source_skeleton_quality"] == {
        "status": "fail",
        "source_skeleton_report": str(skeleton),
        "resolved_source_skeleton_report": str(skeleton),
        "source_status": "operator_review_accepted",
        "draft_status": "operator_review_accepted_or_rejected",
        "identity_checked_keys": ["candidate_recipe_id"],
        "identity_mismatch_keys": ["candidate_recipe_id"],
        "source_skeleton_fingerprint_required": True,
        "source_skeleton_fingerprint_algorithm": "sha256-json-v1",
        "expected_source_skeleton_fingerprint": expected_skeleton_fingerprint,
        "actual_source_skeleton_fingerprint": _fingerprint_payload(mutated_skeleton_payload),
        "source_skeleton_fingerprint_checked": True,
        "blockers": [
            "source_skeleton_fingerprint_mismatch",
            "source_skeleton_no_live_order_sent_not_true",
            "source_skeleton_order_submission_allowed_not_false",
            "source_skeleton_status_is_not_operator_decision_placeholder",
            "source_skeleton_status_mismatch",
            "source_skeleton_identity_mismatch",
        ],
    }
    assert not output.exists()
    assert summary["order_submission_allowed"] is False
    assert summary["no_live_order_sent"] is True


def test_complete_operator_review_decision_blocks_short_rationale(tmp_path) -> None:
    review = tmp_path / "draft.json"
    output = tmp_path / "completed.json"
    review.write_text(
        json.dumps(
            {
                "status": "operator_review_accepted_or_rejected",
                "draft_metadata": _draft_metadata(
                    review,
                    status="conditional_overfit_review_accepted_or_rejected",
                    identity={
                        "candidate_recipe_id": "conditional_refill_formal",
                        "source_promotion_gate_generated_at": "2026-01-01T12:00:00+00:00",
                    },
                ),
                "order_submission_allowed": False,
                "no_live_order_sent": True,
            }
        ),
        encoding="utf-8",
    )

    summary = complete_operator_review_decision(
        review_report=review,
        output_report=output,
        decision="accept",
        reviewer="op",
        rationale="looks okay",
        min_rationale_chars=30,
        generated_at=datetime(2026, 1, 1, 12, 10, tzinfo=UTC),
    )

    assert summary["status"] == "blocked_invalid_operator_decision"
    assert "rationale_too_short" in summary["blockers"]
    assert not output.exists()
    assert summary["order_submission_allowed"] is False
    assert summary["no_live_order_sent"] is True


def test_complete_operator_review_decision_blocks_generic_rationale_without_evidence_anchor(tmp_path) -> None:
    review = tmp_path / "draft.json"
    output = tmp_path / "completed.json"
    review.write_text(
        json.dumps(
            {
                "status": "conditional_overfit_review_accepted_or_rejected",
                "draft_metadata": _draft_metadata(
                    review,
                    status="conditional_overfit_review_accepted_or_rejected",
                    identity={
                        "candidate_recipe_id": "conditional_refill_formal",
                        "source_promotion_gate_generated_at": "2026-01-01T12:16:00+00:00",
                    },
                ),
                "candidate_recipe_id": "conditional_refill_formal",
                "review_packet_fingerprint": "abcdef1234567890abcdef1234567890",
                "order_submission_allowed": False,
                "no_live_order_sent": True,
            }
        ),
        encoding="utf-8",
    )

    summary = complete_operator_review_decision(
        review_report=review,
        output_report=output,
        decision="accept",
        reviewer="op",
        rationale="The evidence looks acceptable for paper-only review while live gates remain closed.",
        generated_at=datetime(2026, 1, 1, 12, 10, tzinfo=UTC),
    )

    assert summary["status"] == "blocked_invalid_operator_decision"
    assert "rationale_missing_evidence_anchor" in summary["blockers"]
    assert summary["rationale_quality"]["available_evidence_anchor_count"] >= 2
    assert summary["rationale_quality"]["matched_evidence_anchor_count"] == 0
    assert not output.exists()
    assert summary["order_submission_allowed"] is False
    assert summary["no_live_order_sent"] is True


def test_complete_operator_review_decision_blocks_accept_with_reject_rationale(tmp_path) -> None:
    review = tmp_path / "draft.json"
    output = tmp_path / "completed.json"
    review.write_text(
        json.dumps(
            {
                "status": "conditional_overfit_review_accepted_or_rejected",
                "draft_metadata": _draft_metadata(
                    review,
                    status="conditional_overfit_review_accepted_or_rejected",
                    identity={"candidate_recipe_id": "conditional_refill_formal"},
                ),
                "candidate_recipe_id": "conditional_refill_formal",
                "order_submission_allowed": False,
                "no_live_order_sent": True,
            }
        ),
        encoding="utf-8",
    )

    summary = complete_operator_review_decision(
        review_report=review,
        output_report=output,
        decision="accept",
        reviewer="op",
        rationale="conditional_refill_formal should be rejected for paper-only routing at this stage.",
        generated_at=datetime(2026, 1, 1, 12, 10, tzinfo=UTC),
    )

    assert summary["status"] == "blocked_invalid_operator_decision"
    assert "rationale_conflicts_with_decision" in summary["blockers"]
    assert summary["rationale_decision_alignment"]["status"] == "fail"
    assert not output.exists()
    assert summary["order_submission_allowed"] is False
    assert summary["no_live_order_sent"] is True


def test_complete_operator_review_decision_blocks_reject_with_accept_rationale(tmp_path) -> None:
    review = tmp_path / "draft.json"
    output = tmp_path / "completed.json"
    review.write_text(
        json.dumps(
            {
                "status": "conditional_overfit_review_accepted_or_rejected",
                "draft_metadata": _draft_metadata(
                    review,
                    status="conditional_overfit_review_accepted_or_rejected",
                    identity={"candidate_recipe_id": "conditional_refill_formal"},
                ),
                "candidate_recipe_id": "conditional_refill_formal",
                "order_submission_allowed": False,
                "no_live_order_sent": True,
            }
        ),
        encoding="utf-8",
    )

    summary = complete_operator_review_decision(
        review_report=review,
        output_report=output,
        decision="reject",
        reviewer="op",
        rationale="conditional_refill_formal is accepted for paper-only routing after the proxy packet review.",
        generated_at=datetime(2026, 1, 1, 12, 10, tzinfo=UTC),
    )

    assert summary["status"] == "blocked_invalid_operator_decision"
    assert "rationale_conflicts_with_decision" in summary["blockers"]
    assert summary["rationale_decision_alignment"]["status"] == "fail"
    assert not output.exists()
    assert summary["order_submission_allowed"] is False
    assert summary["no_live_order_sent"] is True


def test_complete_operator_review_decision_blocks_reviewed_at_before_source_gate(tmp_path) -> None:
    review = tmp_path / "draft.json"
    output = tmp_path / "completed.json"
    review.write_text(
        json.dumps(
            {
                "status": "conditional_overfit_review_accepted_or_rejected",
                "draft_metadata": _draft_metadata(
                    review,
                    status="conditional_overfit_review_accepted_or_rejected",
                    identity={
                        "candidate_recipe_id": "conditional_refill_formal",
                        "source_promotion_gate_generated_at": "2026-01-01T12:00:00+00:00",
                    },
                ),
                "candidate_recipe_id": "conditional_refill_formal",
                "source_promotion_gate_generated_at": "2026-01-01T12:00:00+00:00",
                "order_submission_allowed": False,
                "no_live_order_sent": True,
            }
        ),
        encoding="utf-8",
    )

    summary = complete_operator_review_decision(
        review_report=review,
        output_report=output,
        decision="accept",
        reviewer="op",
        rationale=(
            "conditional_refill_formal is accepted for paper-only routing, with live gates still closed."
        ),
        reviewed_at="2026-01-01T11:59:00+00:00",
        generated_at=datetime(2026, 1, 1, 12, 10, tzinfo=UTC),
    )

    assert summary["status"] == "blocked_invalid_operator_decision"
    assert "reviewed_at_before_source_promotion_gate_generated_at" in summary["blockers"]
    assert summary["reviewed_at_quality"] == {
        "status": "fail",
        "source_check_applied": True,
        "source_promotion_gate_generated_at": "2026-01-01T12:00:00+00:00",
        "reviewed_at": "2026-01-01T11:59:00+00:00",
        "generated_at": "2026-01-01T12:10:00+00:00",
        "max_future_minutes": 5.0,
        "blockers": ["reviewed_at_before_source_promotion_gate_generated_at"],
    }
    assert not output.exists()
    assert summary["order_submission_allowed"] is False
    assert summary["no_live_order_sent"] is True


def test_complete_operator_review_decision_blocks_reviewed_at_too_far_in_future(tmp_path) -> None:
    review = tmp_path / "draft.json"
    output = tmp_path / "completed.json"
    review.write_text(
        json.dumps(
            {
                "status": "conditional_overfit_review_accepted_or_rejected",
                "draft_metadata": _draft_metadata(
                    review,
                    status="conditional_overfit_review_accepted_or_rejected",
                    identity={
                        "candidate_recipe_id": "conditional_refill_formal",
                        "source_promotion_gate_generated_at": "2026-01-01T12:00:00+00:00",
                    },
                ),
                "candidate_recipe_id": "conditional_refill_formal",
                "source_promotion_gate_generated_at": "2026-01-01T12:00:00+00:00",
                "order_submission_allowed": False,
                "no_live_order_sent": True,
            }
        ),
        encoding="utf-8",
    )

    summary = complete_operator_review_decision(
        review_report=review,
        output_report=output,
        decision="accept",
        reviewer="op",
        rationale="conditional_refill_formal is accepted for paper-only review after checking the proxy packet.",
        reviewed_at="2026-01-01T12:16:00+00:00",
        generated_at=datetime(2026, 1, 1, 12, 10, tzinfo=UTC),
    )

    assert summary["status"] == "blocked_invalid_operator_decision"
    assert "reviewed_at_in_future" in summary["blockers"]
    assert summary["reviewed_at_quality"]["blockers"] == ["reviewed_at_in_future"]
    assert not output.exists()
    assert summary["order_submission_allowed"] is False
    assert summary["no_live_order_sent"] is True


def test_complete_operator_review_decision_blocks_source_gate_timestamp_in_future(tmp_path) -> None:
    review = tmp_path / "draft.json"
    output = tmp_path / "completed.json"
    review.write_text(
        json.dumps(
            {
                "status": "conditional_overfit_review_accepted_or_rejected",
                "draft_metadata": _draft_metadata(
                    review,
                    status="conditional_overfit_review_accepted_or_rejected",
                    identity={
                        "candidate_recipe_id": "conditional_refill_formal",
                        "source_promotion_gate_generated_at": "2026-01-01T12:16:00+00:00",
                    },
                ),
                "candidate_recipe_id": "conditional_refill_formal",
                "source_promotion_gate_generated_at": "2026-01-01T12:16:00+00:00",
                "order_submission_allowed": False,
                "no_live_order_sent": True,
            }
        ),
        encoding="utf-8",
    )

    summary = complete_operator_review_decision(
        review_report=review,
        output_report=output,
        decision="accept",
        reviewer="op",
        rationale="conditional_refill_formal is accepted for paper-only review after checking the proxy packet.",
        reviewed_at="2026-01-01T12:16:00+00:00",
        generated_at=datetime(2026, 1, 1, 12, 10, tzinfo=UTC),
    )

    assert summary["status"] == "blocked_invalid_operator_decision"
    assert "source_promotion_gate_generated_at_in_future" in summary["blockers"]
    assert "reviewed_at_in_future" in summary["blockers"]
    assert not output.exists()
    assert summary["order_submission_allowed"] is False
    assert summary["no_live_order_sent"] is True


def test_complete_operator_review_decision_blocks_already_accepted_report(tmp_path) -> None:
    review = tmp_path / "accepted.json"
    output = tmp_path / "completed.json"
    review.write_text(
        json.dumps(
            {
                "status": "operator_review_accepted",
                "draft_metadata": _draft_metadata(review),
                "order_submission_allowed": False,
                "no_live_order_sent": True,
            }
        ),
        encoding="utf-8",
    )

    summary = complete_operator_review_decision(
        review_report=review,
        output_report=output,
        decision="reject",
        reviewer="op",
        rationale="Do not overwrite a finalized decision.",
    )

    assert summary["status"] == "blocked_invalid_operator_decision"
    assert "review_report_already_accepted" in summary["blockers"]
    assert not output.exists()


def test_complete_operator_review_decision_blocks_non_placeholder_status(tmp_path) -> None:
    review = tmp_path / "pending.json"
    output = tmp_path / "completed.json"
    review.write_text(
        json.dumps(
            {
                "status": "operator_review_pending_manual_followup",
                "draft_metadata": _draft_metadata(review),
                "order_submission_allowed": False,
                "no_live_order_sent": True,
            }
        ),
        encoding="utf-8",
    )

    summary = complete_operator_review_decision(
        review_report=review,
        output_report=output,
        decision="accept",
        reviewer="op",
        rationale="Do not turn a non-placeholder review state into an accepted decision.",
    )

    assert summary["status"] == "blocked_invalid_operator_decision"
    assert "review_report_status_is_not_operator_decision_placeholder" in summary["blockers"]
    assert not output.exists()
    assert summary["order_submission_allowed"] is False
    assert summary["no_live_order_sent"] is True
