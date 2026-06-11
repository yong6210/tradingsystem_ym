#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


DEFAULT_OPERATOR_REVIEW_MIN_RATIONALE_CHARS = 30
DEFAULT_OPERATOR_REVIEW_MIN_EVIDENCE_ANCHORS = 1
DEFAULT_OPERATOR_REVIEW_MAX_FUTURE_MINUTES = 5.0
GENERIC_EVIDENCE_ANCHOR_VALUES = {
    "accepted",
    "candidate",
    "live",
    "operator",
    "paper",
    "proxy",
    "rejected",
    "report",
    "review",
}
EVIDENCE_ANCHOR_KEYS = (
    "candidate_recipe_id",
    "recipe_id",
    "review_packet_fingerprint",
    "overfit_review_packet_fingerprint",
    "lineage_review_fingerprint",
    "review_packet_summary",
    "candidate_report",
    "proxy_audit_report",
    "conditional_overfit_holdout_audit_report",
    "source_promotion_gate_report",
)
SKELETON_IDENTITY_KEYS = (
    "candidate_recipe_id",
    "recipe_id",
    "review_packet_fingerprint",
    "overfit_review_packet_fingerprint",
    "lineage_review_fingerprint",
    "source_promotion_gate_report",
    "source_promotion_gate_generated_at",
)
CURRENT_SKELETON_VOLATILE_IDENTITY_KEYS = {"source_promotion_gate_generated_at"}


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


def _backup_path(*, review_report: Path, backup_dir: Path, generated_at: datetime) -> Path:
    stem = review_report.name
    timestamp = generated_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    return backup_dir / f"{stem}.{timestamp}.bak"


def _review_family(status: str) -> str:
    if status.startswith("conditional_overfit_review_"):
        return "conditional_overfit_review"
    if status.startswith("operator_lineage_review_"):
        return "operator_lineage_review"
    return "operator_review"


def _accepted_status(payload: dict[str, Any], *, current_status: str) -> str:
    family = _review_family(current_status)
    required = [str(item) for item in list(payload.get("required_decision_values") or []) if str(item).strip()]
    preferred = {
        "conditional_overfit_review": "conditional_overfit_review_accepted",
        "operator_lineage_review": "operator_lineage_review_accepted",
        "operator_review": "operator_review_accepted",
    }[family]
    if preferred in required or not required:
        return preferred
    return required[0]


def _rejected_status(*, current_status: str) -> str:
    family = _review_family(current_status)
    return {
        "conditional_overfit_review": "conditional_overfit_review_rejected",
        "operator_lineage_review": "operator_lineage_review_rejected",
        "operator_review": "operator_review_rejected",
    }[family]


def _parse_reviewed_at(value: str | None, *, generated_at: datetime) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.lower() == "now":
        return generated_at.isoformat()
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return parsed.astimezone(UTC).isoformat()


def _parse_dt(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)


def _parse_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _same_report_path(left: Path, right: Any) -> bool:
    right_text = str(right or "").strip()
    if not right_text:
        return False
    if right_text == str(left):
        return True
    try:
        return Path(right_text).expanduser().resolve() == left.expanduser().resolve()
    except OSError:
        return False


def _first_existing_path(path_text: str, *, base_path: Path) -> Path | None:
    if not path_text.strip():
        return None
    path = Path(path_text).expanduser()
    candidates = [path]
    if not path.is_absolute():
        candidates.append(base_path.parent / path)
    for candidate in candidates:
        try:
            if candidate.exists():
                return candidate
        except OSError:
            continue
    return None


def _source_promotion_gate_generated_at(payload: dict[str, Any]) -> str | None:
    acceptance = dict(payload.get("acceptance_contract") or {})
    text = str(
        payload.get("source_promotion_gate_generated_at")
        or payload.get("source_generated_at")
        or acceptance.get("reviewed_at_must_be_at_or_after_promotion_gate_generated_at")
        or ""
    ).strip()
    return text or None


def _reviewed_at_quality(
    payload: dict[str, Any],
    *,
    reviewed_at_text: str | None,
    generated_at: datetime,
    max_future_minutes: float = DEFAULT_OPERATOR_REVIEW_MAX_FUTURE_MINUTES,
) -> dict[str, Any]:
    source_text = _source_promotion_gate_generated_at(payload)
    generated = generated_at.astimezone(UTC)
    max_future = max(0.0, float(max_future_minutes or 0.0))
    future_cutoff = generated + timedelta(minutes=max_future)
    result: dict[str, Any] = {
        "status": "pass",
        "source_check_applied": bool(source_text),
        "source_promotion_gate_generated_at": source_text,
        "reviewed_at": reviewed_at_text,
        "generated_at": generated.isoformat(),
        "max_future_minutes": max_future,
        "blockers": [],
    }
    blockers: list[str] = []
    source_dt: datetime | None = None
    reviewed_dt: datetime | None = None
    if source_text:
        try:
            source_dt = _parse_dt(source_text)
        except ValueError:
            source_dt = None
            blockers.append("source_promotion_gate_generated_at_invalid_iso8601")
    try:
        reviewed_dt = _parse_dt(reviewed_at_text)
    except ValueError:
        reviewed_dt = None
        blockers.append("reviewed_at_invalid_iso8601")
    if source_dt is not None and reviewed_dt is not None and reviewed_dt < source_dt:
        blockers.append("reviewed_at_before_source_promotion_gate_generated_at")
    if source_dt is not None and source_dt > future_cutoff:
        blockers.append("source_promotion_gate_generated_at_in_future")
    if reviewed_dt is not None and reviewed_dt > future_cutoff:
        blockers.append("reviewed_at_in_future")
    result["blockers"] = blockers
    result["status"] = "pass" if not blockers else "fail"
    result["source_promotion_gate_generated_at"] = source_dt.isoformat() if source_dt is not None else source_text
    result["reviewed_at"] = reviewed_dt.isoformat() if reviewed_dt is not None else reviewed_at_text
    return result


def _draft_metadata_quality(
    payload: dict[str, Any],
    *,
    review_report: Path,
    generated_at: datetime,
    min_rationale_chars: int,
    min_evidence_anchors: int,
    max_future_minutes: float = DEFAULT_OPERATOR_REVIEW_MAX_FUTURE_MINUTES,
) -> dict[str, Any]:
    raw_draft_metadata = payload.get("draft_metadata")
    draft_metadata = raw_draft_metadata if isinstance(raw_draft_metadata, dict) else {}
    draft_status = str(draft_metadata.get("status") or "").strip()
    draft_generated_at_text = str(draft_metadata.get("generated_at") or "").strip()
    min_rationale = _parse_int(draft_metadata.get("min_rationale_chars"))
    min_evidence = _parse_int(draft_metadata.get("min_evidence_anchors"))
    source_skeleton_report = str(draft_metadata.get("source_skeleton_report") or "").strip()
    expected_skeleton_fingerprint = str(draft_metadata.get("source_skeleton_fingerprint") or "").strip()
    skeleton_fingerprint_algorithm = str(
        draft_metadata.get("source_skeleton_fingerprint_algorithm") or ""
    ).strip()
    skeleton_fingerprint_required = (
        draft_metadata.get("source_skeleton_fingerprint_required") is True
        or bool(expected_skeleton_fingerprint)
        or bool(skeleton_fingerprint_algorithm)
    )
    raw_source_skeleton_snapshot = draft_metadata.get("source_skeleton_snapshot")
    source_skeleton_snapshot = raw_source_skeleton_snapshot if isinstance(raw_source_skeleton_snapshot, dict) else None
    expected_snapshot_fingerprint = str(
        draft_metadata.get("source_skeleton_snapshot_fingerprint") or ""
    ).strip()
    snapshot_fingerprint_algorithm = str(
        draft_metadata.get("source_skeleton_snapshot_fingerprint_algorithm") or ""
    ).strip()
    snapshot_fingerprint_required = (
        source_skeleton_snapshot is not None
        or bool(expected_snapshot_fingerprint)
        or bool(snapshot_fingerprint_algorithm)
    )
    generated = generated_at.astimezone(UTC)
    max_future = max(0.0, float(max_future_minutes or 0.0))
    future_cutoff = generated + timedelta(minutes=max_future)
    blockers: list[str] = []
    draft_generated_at: datetime | None = None
    source_skeleton_quality: dict[str, Any] = {
        "status": "not_checked",
        "source_skeleton_report": source_skeleton_report or None,
        "resolved_source_skeleton_report": None,
        "source_status": None,
        "draft_status": str(payload.get("status") or payload.get("decision") or "").strip() or None,
        "identity_checked_keys": [],
        "identity_mismatch_keys": [],
        "source_skeleton_fingerprint_required": skeleton_fingerprint_required,
        "source_skeleton_fingerprint_algorithm": skeleton_fingerprint_algorithm or None,
        "expected_source_skeleton_fingerprint": expected_skeleton_fingerprint or None,
        "actual_source_skeleton_fingerprint": None,
        "source_skeleton_fingerprint_checked": False,
        "blockers": [],
    }
    if draft_status != "operator_review_draft_prepared":
        blockers.append("review_report_draft_metadata_missing_or_invalid")
    else:
        if draft_metadata.get("operator_must_choose_accept_or_reject") is not True:
            blockers.append("draft_metadata_operator_must_choose_accept_or_reject_not_true")
        if draft_metadata.get("auto_accept_allowed") is not False:
            blockers.append("draft_metadata_auto_accept_allowed_not_false")
        if draft_metadata.get("order_submission_allowed") is not False:
            blockers.append("draft_metadata_order_submission_allowed_not_false")
        if draft_metadata.get("no_live_order_sent") is not True:
            blockers.append("draft_metadata_no_live_order_sent_not_true")
        if skeleton_fingerprint_required and skeleton_fingerprint_algorithm != "sha256-json-v1":
            blockers.append("draft_metadata_source_skeleton_fingerprint_algorithm_invalid")
        if skeleton_fingerprint_required and not expected_skeleton_fingerprint:
            blockers.append("draft_metadata_source_skeleton_fingerprint_missing")
        if raw_source_skeleton_snapshot is not None and source_skeleton_snapshot is None:
            source_skeleton_quality["blockers"].append("draft_metadata_source_skeleton_snapshot_invalid")
        if snapshot_fingerprint_required and snapshot_fingerprint_algorithm != "sha256-json-v1":
            source_skeleton_quality["blockers"].append(
                "draft_metadata_source_skeleton_snapshot_fingerprint_algorithm_invalid"
            )
        if snapshot_fingerprint_required and not expected_snapshot_fingerprint:
            source_skeleton_quality["blockers"].append("draft_metadata_source_skeleton_snapshot_fingerprint_missing")
        if min_rationale is None or min_rationale < max(0, int(min_rationale_chars or 0)):
            blockers.append("draft_metadata_min_rationale_chars_missing_or_too_low")
        if min_evidence is None or min_evidence < max(0, int(min_evidence_anchors or 0)):
            blockers.append("draft_metadata_min_evidence_anchors_missing_or_too_low")
        if not source_skeleton_report:
            blockers.append("draft_metadata_source_skeleton_report_missing")
        if not _same_report_path(review_report, draft_metadata.get("output_report")):
            blockers.append("draft_metadata_output_report_mismatch")
        if not draft_generated_at_text:
            blockers.append("draft_metadata_generated_at_missing")
        else:
            try:
                draft_generated_at = _parse_dt(draft_generated_at_text)
            except ValueError:
                draft_generated_at = None
                blockers.append("draft_metadata_generated_at_invalid_iso8601")
        if draft_generated_at is not None and draft_generated_at > future_cutoff:
            blockers.append("draft_metadata_generated_at_in_future")
        if source_skeleton_report:
            skeleton_path = _first_existing_path(source_skeleton_report, base_path=review_report)
            source_skeleton_quality["resolved_source_skeleton_report"] = (
                str(skeleton_path) if skeleton_path is not None else None
            )
            current_skeleton: dict[str, Any] = {}
            current_skeleton_fingerprint: str | None = None
            current_source_blockers: list[str] = []
            if skeleton_path is None:
                if source_skeleton_snapshot is None:
                    source_skeleton_quality["blockers"].append("draft_metadata_source_skeleton_report_not_found")
                else:
                    current_source_blockers.append("draft_metadata_source_skeleton_report_not_found")
            else:
                try:
                    current_skeleton = _read_json(skeleton_path)
                except (OSError, ValueError, json.JSONDecodeError):
                    current_skeleton = {}
                    if source_skeleton_snapshot is None:
                        source_skeleton_quality["blockers"].append("draft_metadata_source_skeleton_report_unreadable")
                    else:
                        current_source_blockers.append("draft_metadata_source_skeleton_report_unreadable")

            if source_skeleton_snapshot is not None:
                source_skeleton_quality.update(
                    {
                        "source_skeleton_validation_source": "embedded_snapshot",
                        "source_skeleton_snapshot_present": True,
                        "source_skeleton_snapshot_fingerprint_algorithm": snapshot_fingerprint_algorithm or None,
                        "expected_source_skeleton_snapshot_fingerprint": expected_snapshot_fingerprint or None,
                        "actual_source_skeleton_snapshot_fingerprint": None,
                        "source_skeleton_snapshot_fingerprint_checked": snapshot_fingerprint_required,
                        "current_source_skeleton_fingerprint": None,
                        "current_source_skeleton_fingerprint_matches_snapshot": None,
                        "current_source_skeleton_report_blockers": current_source_blockers,
                        "current_identity_checked_keys": [],
                        "current_identity_mismatch_keys": [],
                    }
                )
                if current_skeleton:
                    current_skeleton_fingerprint = _fingerprint_payload(current_skeleton)
                    source_skeleton_quality["current_source_skeleton_fingerprint"] = current_skeleton_fingerprint
                    current_identity_checked: list[str] = []
                    current_identity_mismatch: list[str] = []
                    for key in SKELETON_IDENTITY_KEYS:
                        if key in CURRENT_SKELETON_VOLATILE_IDENTITY_KEYS:
                            continue
                        current_value = str(current_skeleton.get(key) or "").strip()
                        draft_value = str(payload.get(key) or "").strip()
                        if not current_value:
                            continue
                        current_identity_checked.append(key)
                        if current_value != draft_value:
                            current_identity_mismatch.append(key)
                    source_skeleton_quality["current_identity_checked_keys"] = current_identity_checked
                    source_skeleton_quality["current_identity_mismatch_keys"] = current_identity_mismatch
                    if current_identity_mismatch:
                        source_skeleton_quality["blockers"].append("current_source_skeleton_material_identity_mismatch")
                skeleton = source_skeleton_snapshot
            else:
                skeleton = current_skeleton

            if skeleton:
                actual_skeleton_fingerprint = _fingerprint_payload(skeleton)
                if source_skeleton_snapshot is not None:
                    source_skeleton_quality["actual_source_skeleton_snapshot_fingerprint"] = (
                        actual_skeleton_fingerprint
                    )
                    if current_skeleton_fingerprint is not None:
                        source_skeleton_quality["current_source_skeleton_fingerprint_matches_snapshot"] = (
                            current_skeleton_fingerprint == actual_skeleton_fingerprint
                        )
                    if snapshot_fingerprint_required and expected_snapshot_fingerprint:
                        if actual_skeleton_fingerprint != expected_snapshot_fingerprint:
                            source_skeleton_quality["blockers"].append(
                                "source_skeleton_snapshot_fingerprint_mismatch"
                            )
                source_skeleton_quality["actual_source_skeleton_fingerprint"] = actual_skeleton_fingerprint
                if skeleton_fingerprint_required:
                    source_skeleton_quality["source_skeleton_fingerprint_checked"] = True
                    if actual_skeleton_fingerprint != expected_skeleton_fingerprint:
                        source_skeleton_quality["blockers"].append("source_skeleton_fingerprint_mismatch")
                skeleton_status = str(skeleton.get("status") or skeleton.get("decision") or "").strip()
                draft_review_status = str(payload.get("status") or payload.get("decision") or "").strip()
                source_skeleton_quality["source_status"] = skeleton_status or None
                if skeleton.get("no_live_order_sent") is not True:
                    source_skeleton_quality["blockers"].append("source_skeleton_no_live_order_sent_not_true")
                if skeleton.get("order_submission_allowed") is not False:
                    source_skeleton_quality["blockers"].append("source_skeleton_order_submission_allowed_not_false")
                if not skeleton_status.endswith("_accepted_or_rejected"):
                    source_skeleton_quality["blockers"].append(
                        "source_skeleton_status_is_not_operator_decision_placeholder"
                    )
                if skeleton_status and draft_review_status and skeleton_status != draft_review_status:
                    source_skeleton_quality["blockers"].append("source_skeleton_status_mismatch")
                identity_checked: list[str] = []
                identity_mismatch: list[str] = []
                for key in SKELETON_IDENTITY_KEYS:
                    skeleton_value = str(skeleton.get(key) or "").strip()
                    draft_value = str(payload.get(key) or "").strip()
                    if not skeleton_value:
                        continue
                    identity_checked.append(key)
                    if skeleton_value != draft_value:
                        identity_mismatch.append(key)
                source_skeleton_quality["identity_checked_keys"] = identity_checked
                source_skeleton_quality["identity_mismatch_keys"] = identity_mismatch
                if identity_mismatch:
                    source_skeleton_quality["blockers"].append("source_skeleton_identity_mismatch")
            source_skeleton_quality["status"] = (
                "pass" if not source_skeleton_quality["blockers"] else "fail"
            )
            blockers.extend(str(item) for item in source_skeleton_quality["blockers"])
    return {
        "status": "pass" if not blockers else "fail",
        "draft_status": draft_status or None,
        "source_skeleton_report": source_skeleton_report or None,
        "output_report": draft_metadata.get("output_report"),
        "generated_at": draft_generated_at.isoformat() if draft_generated_at is not None else draft_generated_at_text or None,
        "min_rationale_chars": min_rationale,
        "min_evidence_anchors": min_evidence,
        "max_future_minutes": max_future,
        "source_skeleton_quality": source_skeleton_quality,
        "blockers": blockers,
    }


def _compact_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _add_anchor(anchors: list[dict[str, str]], *, label: str, value: Any) -> None:
    text = str(value or "").strip()
    if not text:
        return
    candidates = [text]
    if "/" in text:
        path = Path(text)
        candidates.extend([path.name, path.stem])
    compact_full = _compact_text(text)
    if len(compact_full) >= 12 and re.fullmatch(r"[0-9a-f]+", compact_full):
        candidates.append(compact_full[:12])

    seen = {item["compact"] for item in anchors}
    for candidate in candidates:
        compact = _compact_text(candidate)
        if len(compact) < 8 or compact in GENERIC_EVIDENCE_ANCHOR_VALUES or compact in seen:
            continue
        anchors.append(
            {
                "label": label,
                "value": str(candidate).strip(),
                "compact": compact,
            }
        )
        seen.add(compact)


def _evidence_anchors(payload: dict[str, Any]) -> list[dict[str, str]]:
    anchors: list[dict[str, str]] = []
    for key in EVIDENCE_ANCHOR_KEYS:
        _add_anchor(anchors, label=key, value=payload.get(key))
    reviewed_folds = payload.get("reviewed_folds")
    if isinstance(reviewed_folds, list):
        for fold in reviewed_folds:
            _add_anchor(anchors, label="reviewed_folds", value=f"fold_{fold}")
    return anchors


def _rationale_quality(
    payload: dict[str, Any],
    *,
    rationale: str,
    min_evidence_anchors: int,
) -> dict[str, Any]:
    anchors = _evidence_anchors(payload)
    rationale_lower = str(rationale or "").lower()
    rationale_compact = _compact_text(rationale)
    matched: list[dict[str, str]] = []
    seen: set[str] = set()
    for anchor in anchors:
        value = anchor["value"].lower()
        compact = anchor["compact"]
        if value in rationale_lower or compact in rationale_compact:
            key = f"{anchor['label']}:{anchor['compact']}"
            if key not in seen:
                matched.append({"label": anchor["label"], "value": anchor["value"]})
                seen.add(key)
    required = max(0, int(min_evidence_anchors or 0))
    return {
        "status": "pass" if len(matched) >= min(required, len(anchors)) else "fail",
        "min_evidence_anchors": required,
        "available_evidence_anchor_count": len(anchors),
        "matched_evidence_anchor_count": len(matched),
        "matched_evidence_anchors": matched[:5],
        "evidence_anchor_check_applied": bool(anchors and required > 0),
    }


def _rationale_decision_alignment(*, decision: str, rationale: str) -> dict[str, Any]:
    decision_text = str(decision or "").strip().lower()
    rationale_text = str(rationale or "").strip().lower()
    conflict_patterns = {
        "accept": [
            r"\breject(?:ed|ion|s)?\b",
            r"\bdeclin(?:e|ed|es|ing)\b",
            r"\bdo\s+not\s+accept\b",
            r"\bnot\s+accept(?:ed)?\b",
        ],
        "reject": [
            r"\baccept(?:ed|s)?\s+for\b",
            r"\bapprove(?:d|s)?\b",
            r"\bshould\s+accept\b",
            r"\bdecision\s+is\s+accept\b",
        ],
    }
    matches: list[str] = []
    for pattern in conflict_patterns.get(decision_text, []):
        if re.search(pattern, rationale_text):
            matches.append(pattern)
    return {
        "status": "pass" if not matches else "fail",
        "decision": decision_text or None,
        "conflict_patterns": matches,
        "blockers": ["rationale_conflicts_with_decision"] if matches else [],
    }


def complete_operator_review_decision(
    *,
    review_report: Path,
    output_report: Path,
    decision: str,
    reviewer: str,
    rationale: str,
    reviewed_at: str | None = None,
    backup_dir: Path | None = None,
    min_rationale_chars: int = DEFAULT_OPERATOR_REVIEW_MIN_RATIONALE_CHARS,
    min_evidence_anchors: int = DEFAULT_OPERATOR_REVIEW_MIN_EVIDENCE_ANCHORS,
    force: bool = False,
    dry_run: bool = False,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    generated = (generated_at or datetime.now(UTC)).astimezone(UTC)
    payload = _read_json(review_report)
    decision_text = str(decision or "").strip().lower()
    reviewer_text = str(reviewer or "").strip()
    rationale_text = str(rationale or "").strip()
    current_status = str(payload.get("status") or payload.get("decision") or "").strip()
    raw_draft_metadata = payload.get("draft_metadata")
    draft_metadata = raw_draft_metadata if isinstance(raw_draft_metadata, dict) else {}
    min_rationale = max(0, int(min_rationale_chars or 0))
    min_evidence = max(0, int(min_evidence_anchors or 0))
    draft_metadata_quality = _draft_metadata_quality(
        payload,
        review_report=review_report,
        generated_at=generated,
        min_rationale_chars=min_rationale,
        min_evidence_anchors=min_evidence,
    )
    draft_status = str(draft_metadata_quality.get("draft_status") or "").strip()
    rationale_quality = _rationale_quality(
        payload,
        rationale=rationale_text,
        min_evidence_anchors=min_evidence,
    )
    rationale_decision_alignment = _rationale_decision_alignment(
        decision=decision_text,
        rationale=rationale_text,
    )
    blockers: list[str] = []
    if decision_text not in {"accept", "reject"}:
        blockers.append("decision_must_be_accept_or_reject")
    if payload.get("no_live_order_sent") is not True:
        blockers.append("review_report_no_live_order_sent_not_true")
    if payload.get("order_submission_allowed") is not False:
        blockers.append("review_report_order_submission_allowed_not_false")
    if not current_status:
        blockers.append("review_report_status_missing")
    placeholder_status = current_status.endswith("_accepted_or_rejected")
    if current_status and not placeholder_status:
        blockers.append("review_report_status_is_not_operator_decision_placeholder")
    blockers.extend(str(item) for item in draft_metadata_quality.get("blockers") or [])
    if current_status.endswith("_accepted") and not placeholder_status:
        blockers.append("review_report_already_accepted")
    if current_status.endswith("_rejected") and not placeholder_status:
        blockers.append("review_report_already_rejected")
    if not reviewer_text or reviewer_text == "operator_name_or_initials":
        blockers.append("reviewer_required")
    if not rationale_text or rationale_text.startswith("why_"):
        blockers.append("rationale_required")
    elif len(rationale_text) < min_rationale:
        blockers.append("rationale_too_short")
    elif rationale_quality.get("evidence_anchor_check_applied") is True and rationale_quality.get("status") != "pass":
        blockers.append("rationale_missing_evidence_anchor")
    blockers.extend(str(item) for item in rationale_decision_alignment.get("blockers") or [])
    try:
        reviewed_at_text = _parse_reviewed_at(reviewed_at or "now", generated_at=generated)
    except ValueError:
        reviewed_at_text = None
        blockers.append("reviewed_at_invalid_iso8601")
    reviewed_at_quality = _reviewed_at_quality(payload, reviewed_at_text=reviewed_at_text, generated_at=generated)
    blockers.extend(str(item) for item in reviewed_at_quality.get("blockers") or [])
    in_place = output_report == review_report
    backup_report = _backup_path(review_report=review_report, backup_dir=backup_dir, generated_at=generated) if backup_dir and in_place else None
    if in_place and backup_dir is None:
        blockers.append("in_place_decision_requires_backup_dir")
    if backup_report is not None and backup_report.exists() and not force:
        blockers.append("backup_report_exists_without_force")
    if output_report.exists() and output_report != review_report and not force:
        blockers.append("output_report_exists_without_force")
    if blockers:
        return {
            "status": "blocked_invalid_operator_decision",
            "created": False,
            "review_report": str(review_report),
            "output_report": str(output_report),
            "backup_report": str(backup_report) if backup_report is not None else None,
            "decision": decision_text or None,
            "blockers": blockers,
            "rationale_quality": rationale_quality,
            "rationale_decision_alignment": rationale_decision_alignment,
            "draft_metadata_quality": draft_metadata_quality,
            "reviewed_at_quality": reviewed_at_quality,
            "next_action": "provide_explicit_decision_reviewer_rationale_and_valid_output_path",
            "order_submission_allowed": False,
            "no_live_order_sent": True,
        }

    new_status = (
        _accepted_status(payload, current_status=current_status)
        if decision_text == "accept"
        else _rejected_status(current_status=current_status)
    )
    completed = dict(payload)
    completed["status"] = new_status
    completed["reviewer"] = reviewer_text
    completed["reviewed_at"] = reviewed_at_text
    completed["rationale"] = rationale_text
    completed["order_submission_allowed"] = False
    completed["no_live_order_sent"] = True
    completed["decision_metadata"] = {
        "status": "operator_review_decision_completed",
        "decision": decision_text,
        "previous_status": current_status,
        "new_status": new_status,
        "draft_status": draft_status or None,
        "draft_source_skeleton_report": draft_metadata.get("source_skeleton_report"),
        "draft_metadata_required": True,
        "draft_metadata_quality": draft_metadata_quality,
        "review_report": str(review_report),
        "output_report": str(output_report),
        "generated_at": generated.isoformat(),
        "explicit_operator_decision_required": True,
        "auto_accept_allowed": False,
        "min_rationale_chars": min_rationale,
        "min_evidence_anchors": min_evidence,
        "rationale_quality": rationale_quality,
        "rationale_decision_alignment": rationale_decision_alignment,
        "reviewed_at_quality": reviewed_at_quality,
        "order_submission_allowed": False,
        "no_live_order_sent": True,
    }
    if dry_run:
        return {
            "status": "operator_review_decision_dry_run",
            "created": False,
            "would_create": True,
            "review_report": str(review_report),
            "output_report": str(output_report),
            "backup_report": str(backup_report) if backup_report is not None else None,
            "backup_would_be_created": backup_report is not None,
            "decision": decision_text,
            "new_status": new_status,
            "blockers": [],
            "rationale_quality": rationale_quality,
            "rationale_decision_alignment": rationale_decision_alignment,
            "reviewed_at_quality": reviewed_at_quality,
            "next_action": "rerun_without_dry_run_to_write_completed_operator_review",
            "order_submission_allowed": False,
            "no_live_order_sent": True,
        }
    if backup_report is not None:
        _write_json(backup_report, payload)
    _write_json(output_report, completed)
    return {
        "status": "operator_review_decision_completed",
        "created": True,
        "review_report": str(review_report),
        "output_report": str(output_report),
        "backup_report": str(backup_report) if backup_report is not None else None,
        "backup_created": backup_report is not None,
        "decision": decision_text,
        "new_status": new_status,
        "blockers": [],
        "next_action": "run_validation_command_for_completed_operator_review",
        "order_submission_allowed": False,
        "no_live_order_sent": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Complete a market_state_rotation_v6 operator review decision without enabling live orders."
    )
    parser.add_argument("--review-report", required=True)
    output_group = parser.add_mutually_exclusive_group(required=True)
    output_group.add_argument("--output-report")
    output_group.add_argument("--in-place", action="store_true")
    parser.add_argument("--decision", required=True, choices=["accept", "reject"])
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--rationale", required=True)
    parser.add_argument("--reviewed-at", default="now")
    parser.add_argument("--backup-dir")
    parser.add_argument("--min-rationale-chars", type=int, default=DEFAULT_OPERATOR_REVIEW_MIN_RATIONALE_CHARS)
    parser.add_argument("--min-evidence-anchors", type=int, default=DEFAULT_OPERATOR_REVIEW_MIN_EVIDENCE_ANCHORS)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--write-summary", action="store_true")
    args = parser.parse_args()

    review_report = Path(args.review_report)
    output_report = review_report if args.in_place else Path(str(args.output_report))
    summary = complete_operator_review_decision(
        review_report=review_report,
        output_report=output_report,
        decision=args.decision,
        reviewer=args.reviewer,
        rationale=args.rationale,
        reviewed_at=args.reviewed_at,
        backup_dir=Path(args.backup_dir) if args.backup_dir else None,
        min_rationale_chars=int(args.min_rationale_chars),
        min_evidence_anchors=int(args.min_evidence_anchors),
        force=bool(args.force),
        dry_run=bool(args.dry_run),
    )
    if args.write_summary:
        summary_path = output_report.with_suffix(".decision_summary.json")
        _write_json(summary_path, summary)
    print(json.dumps(summary, ensure_ascii=True, sort_keys=True))
    return 0 if not summary.get("blockers") else 1


if __name__ == "__main__":
    raise SystemExit(main())
