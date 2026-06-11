import json
import hashlib
from datetime import UTC, datetime

from scripts.prepare_market_state_rotation_v6_operator_review_draft import prepare_operator_review_draft


def _fingerprint_payload(payload: dict[str, object]) -> str:
    normalized = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def test_prepare_operator_review_draft_copies_skeleton_without_accepting(tmp_path) -> None:
    skeleton = tmp_path / "skeleton.json"
    output = tmp_path / "reviews" / "review.json"
    skeleton_payload = {
        "status": "conditional_overfit_review_accepted_or_rejected",
        "candidate_recipe_id": "candidate",
        "reviewer": "operator_name_or_initials",
        "reviewed_at": "iso8601_timestamp_after_source_promotion_gate_generated_at",
        "rationale": "why_the_conditional_overlay_proxy_evidence_is_accepted_or_rejected_for_paper_only",
        "order_submission_allowed": False,
        "no_live_order_sent": True,
    }
    skeleton.write_text(json.dumps(skeleton_payload), encoding="utf-8")

    summary = prepare_operator_review_draft(
        skeleton_report=skeleton,
        output_report=output,
        generated_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
    )

    assert summary == {
        "status": "draft_prepared",
        "created": True,
        "source_skeleton_report": str(skeleton),
        "output_report": str(output),
        "blockers": [],
        "next_action": "operator_fill_reviewer_reviewed_at_rationale_and_accept_or_reject_then_run_validation",
        "order_submission_allowed": False,
        "no_live_order_sent": True,
    }
    draft = json.loads(output.read_text(encoding="utf-8"))
    assert draft["status"] == "conditional_overfit_review_accepted_or_rejected"
    assert draft["draft_metadata"]["operator_must_choose_accept_or_reject"] is True
    assert draft["draft_metadata"]["auto_accept_allowed"] is False
    assert draft["draft_metadata"]["source_skeleton_fingerprint"] == _fingerprint_payload(skeleton_payload)
    assert draft["draft_metadata"]["source_skeleton_fingerprint_algorithm"] == "sha256-json-v1"
    assert draft["draft_metadata"]["source_skeleton_fingerprint_required"] is True
    assert draft["draft_metadata"]["source_skeleton_snapshot"] == skeleton_payload
    assert draft["draft_metadata"]["source_skeleton_snapshot_fingerprint"] == _fingerprint_payload(skeleton_payload)
    assert draft["draft_metadata"]["source_skeleton_snapshot_fingerprint_algorithm"] == "sha256-json-v1"
    assert draft["draft_metadata"]["min_rationale_chars"] == 30
    assert draft["draft_metadata"]["min_evidence_anchors"] == 1
    assert draft["draft_metadata"]["generated_at"] == "2026-01-01T12:00:00+00:00"
    assert draft["order_submission_allowed"] is False
    assert draft["no_live_order_sent"] is True


def test_prepare_operator_review_draft_does_not_overwrite_without_force(tmp_path) -> None:
    skeleton = tmp_path / "skeleton.json"
    output = tmp_path / "review.json"
    skeleton.write_text(
        json.dumps(
            {
                "status": "operator_lineage_review_accepted_or_rejected",
                "order_submission_allowed": False,
                "no_live_order_sent": True,
            }
        ),
        encoding="utf-8",
    )
    output.write_text('{"status":"operator_filled"}\n', encoding="utf-8")

    summary = prepare_operator_review_draft(skeleton_report=skeleton, output_report=output)

    assert summary["status"] == "draft_exists"
    assert summary["created"] is False
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "operator_filled"
    assert summary["order_submission_allowed"] is False
    assert summary["no_live_order_sent"] is True


def test_prepare_operator_review_draft_blocks_invalid_skeleton(tmp_path) -> None:
    skeleton = tmp_path / "skeleton.json"
    output = tmp_path / "review.json"
    skeleton.write_text(
        json.dumps(
            {
                "status": "operator_review_accepted",
                "order_submission_allowed": True,
                "no_live_order_sent": False,
            }
        ),
        encoding="utf-8",
    )

    summary = prepare_operator_review_draft(skeleton_report=skeleton, output_report=output)

    assert summary["status"] == "blocked_invalid_skeleton"
    assert summary["created"] is False
    assert summary["blockers"] == [
        "skeleton_no_live_order_sent_not_true",
        "skeleton_order_submission_allowed_not_false",
        "skeleton_status_already_accepted",
        "skeleton_status_is_not_operator_decision_placeholder",
    ]
    assert not output.exists()
    assert summary["order_submission_allowed"] is False
    assert summary["no_live_order_sent"] is True
