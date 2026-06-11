#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


DEFAULT_OPERATOR_REVIEW_MIN_RATIONALE_CHARS = 30
DEFAULT_OPERATOR_REVIEW_MIN_EVIDENCE_ANCHORS = 1


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object in {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _fingerprint_payload(payload: dict[str, Any]) -> str:
    normalized = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def prepare_operator_review_draft(
    *,
    skeleton_report: Path,
    output_report: Path,
    min_rationale_chars: int = DEFAULT_OPERATOR_REVIEW_MIN_RATIONALE_CHARS,
    min_evidence_anchors: int = DEFAULT_OPERATOR_REVIEW_MIN_EVIDENCE_ANCHORS,
    force: bool = False,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    generated = (generated_at or datetime.now(UTC)).astimezone(UTC)
    skeleton = _read_json(skeleton_report)
    min_rationale = max(1, int(min_rationale_chars or DEFAULT_OPERATOR_REVIEW_MIN_RATIONALE_CHARS))
    min_evidence = max(0, int(min_evidence_anchors or 0))
    blockers: list[str] = []
    if skeleton.get("no_live_order_sent") is not True:
        blockers.append("skeleton_no_live_order_sent_not_true")
    if skeleton.get("order_submission_allowed") is not False:
        blockers.append("skeleton_order_submission_allowed_not_false")
    if str(skeleton.get("status") or "").endswith("_accepted"):
        blockers.append("skeleton_status_already_accepted")
    if not str(skeleton.get("status") or "").endswith("_accepted_or_rejected"):
        blockers.append("skeleton_status_is_not_operator_decision_placeholder")
    if output_report.exists() and not force:
        return {
            "status": "draft_exists",
            "created": False,
            "source_skeleton_report": str(skeleton_report),
            "output_report": str(output_report),
            "blockers": [],
            "next_action": "edit_existing_draft_then_run_validation_command",
            "order_submission_allowed": False,
            "no_live_order_sent": True,
        }
    if blockers:
        return {
            "status": "blocked_invalid_skeleton",
            "created": False,
            "source_skeleton_report": str(skeleton_report),
            "output_report": str(output_report),
            "blockers": blockers,
            "next_action": "repair_skeleton_before_preparing_operator_review_draft",
            "order_submission_allowed": False,
            "no_live_order_sent": True,
        }

    source_skeleton_fingerprint = _fingerprint_payload(skeleton)
    draft = dict(skeleton)
    draft["draft_metadata"] = {
        "status": "operator_review_draft_prepared",
        "source_skeleton_report": str(skeleton_report),
        "source_skeleton_fingerprint": source_skeleton_fingerprint,
        "source_skeleton_fingerprint_algorithm": "sha256-json-v1",
        "source_skeleton_fingerprint_required": True,
        "source_skeleton_snapshot": skeleton,
        "source_skeleton_snapshot_fingerprint": source_skeleton_fingerprint,
        "source_skeleton_snapshot_fingerprint_algorithm": "sha256-json-v1",
        "output_report": str(output_report),
        "generated_at": generated.isoformat(),
        "operator_must_choose_accept_or_reject": True,
        "auto_accept_allowed": False,
        "min_rationale_chars": min_rationale,
        "min_evidence_anchors": min_evidence,
        "order_submission_allowed": False,
        "no_live_order_sent": True,
    }
    draft["order_submission_allowed"] = False
    draft["no_live_order_sent"] = True
    _write_json(output_report, draft)
    return {
        "status": "draft_prepared",
        "created": True,
        "source_skeleton_report": str(skeleton_report),
        "output_report": str(output_report),
        "blockers": [],
        "next_action": "operator_fill_reviewer_reviewed_at_rationale_and_accept_or_reject_then_run_validation",
        "order_submission_allowed": False,
        "no_live_order_sent": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prepare a safe market_state_rotation_v6 operator review draft from a skeleton."
    )
    parser.add_argument("--skeleton-report", required=True)
    parser.add_argument("--output-report", required=True)
    parser.add_argument("--min-rationale-chars", type=int, default=DEFAULT_OPERATOR_REVIEW_MIN_RATIONALE_CHARS)
    parser.add_argument("--min-evidence-anchors", type=int, default=DEFAULT_OPERATOR_REVIEW_MIN_EVIDENCE_ANCHORS)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--write-summary", action="store_true")
    args = parser.parse_args()

    summary = prepare_operator_review_draft(
        skeleton_report=Path(args.skeleton_report),
        output_report=Path(args.output_report),
        min_rationale_chars=int(args.min_rationale_chars),
        min_evidence_anchors=int(args.min_evidence_anchors),
        force=bool(args.force),
    )
    if args.write_summary:
        summary_path = Path(args.output_report).with_suffix(".prepare_summary.json")
        _write_json(summary_path, summary)
    print(json.dumps(summary, ensure_ascii=True, sort_keys=True))
    return 0 if not summary.get("blockers") else 1


if __name__ == "__main__":
    raise SystemExit(main())
