from __future__ import annotations

from typing import Any, Mapping

_LEGACY_APPROVAL_GO_TEXT = (
    "GO: approval template is aligned with replay-backed downside and the current threshold-lineage winner."
)
_CURRENT_APPROVAL_GO_TEXT = "GO: approval template is aligned with the configured replay-backed validation evidence."


def _text(value: Any) -> str:
    return str(value or "")


def _normalize_validation_alert_text(value: Any) -> str:
    text = _text(value)
    if not text:
        return ""
    return (
        text.replace(_LEGACY_APPROVAL_GO_TEXT, _CURRENT_APPROVAL_GO_TEXT)
        .replace("winner=", "validation_lineage=")
        .replace("; promotion=", "; recommended_action=")
    )


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _approval_strip_summary(summary: Mapping[str, Any] | None) -> dict[str, str]:
    summary_dict = _mapping(summary)
    return {
        "primary_reason": _normalize_validation_alert_text(summary_dict.get("primary_reason")),
        "approve_value": _text(summary_dict.get("approve_value")),
        "approve_reason": _normalize_validation_alert_text(summary_dict.get("approve_reason")),
        "align_value": _text(summary_dict.get("align_value")),
        "align_reason": _normalize_validation_alert_text(summary_dict.get("align_reason")),
        "act_value": _text(summary_dict.get("act_value")),
        "act_reason": _normalize_validation_alert_text(summary_dict.get("act_reason")),
        "act_priority_level": _text(summary_dict.get("act_priority_level")),
    }


def approval_summary_passthrough(summary: Mapping[str, Any] | None) -> dict[str, str]:
    summary_dict = _mapping(summary)
    return {
        "deployment_go_no_go": _text(summary_dict.get("playbook_go_no_go")),
        "deployment_code": _text(summary_dict.get("playbook_code")),
        "deployment_message": _normalize_validation_alert_text(summary_dict.get("playbook_message")),
        "approval_topline_status": _text(summary_dict.get("topline_status")),
        "approval_topline_code": _text(summary_dict.get("topline_code")),
        "approval_topline_message": _normalize_validation_alert_text(summary_dict.get("topline_message")),
        "approval_topline_summary_line": _normalize_validation_alert_text(summary_dict.get("topline_summary_line")),
        "playbook_go_no_go": _text(summary_dict.get("playbook_go_no_go")),
        "playbook_code": _text(summary_dict.get("playbook_code")),
        "playbook_action": _text(summary_dict.get("playbook_action")),
        "playbook_message": _normalize_validation_alert_text(summary_dict.get("playbook_message")),
    }


def validation_report_contract(payload: Mapping[str, Any] | None) -> dict[str, str]:
    payload_dict = _mapping(payload)
    report = _mapping(payload_dict.get("validation_report"))
    summary_contract = approval_summary_passthrough(report.get("deployment_approval_summary"))
    return {
        key: _text(payload_dict.get(key) or summary_contract.get(key))
        for key in (
            "deployment_go_no_go",
            "deployment_code",
            "deployment_message",
            "approval_topline_status",
            "approval_topline_code",
            "approval_topline_message",
            "approval_topline_summary_line",
            "playbook_go_no_go",
            "playbook_code",
            "playbook_action",
            "playbook_message",
        )
    }


def validation_alert_contract(payload: Mapping[str, Any] | None) -> dict[str, str]:
    payload_dict = _mapping(payload)
    return {
        "deployment_go_no_go": _text(
            payload_dict.get("deployment_go_no_go")
            or payload_dict.get("approval_playbook_go_no_go")
            or payload_dict.get("playbook_go_no_go")
        ),
        "deployment_code": _text(
            payload_dict.get("deployment_code")
            or payload_dict.get("approval_playbook_code")
            or payload_dict.get("playbook_code")
        ),
        "deployment_message": _normalize_validation_alert_text(
            payload_dict.get("deployment_message")
            or payload_dict.get("approval_playbook_message")
            or payload_dict.get("playbook_message")
        ),
        "approval_topline_summary_line": _normalize_validation_alert_text(
            payload_dict.get("approval_topline_summary_line") or payload_dict.get("topline_summary_line")
        ),
        "approval_playbook_go_no_go": _text(
            payload_dict.get("approval_playbook_go_no_go") or payload_dict.get("playbook_go_no_go")
        ),
        "approval_playbook_code": _text(payload_dict.get("approval_playbook_code") or payload_dict.get("playbook_code")),
        "approval_playbook_action": _text(
            payload_dict.get("approval_playbook_action") or payload_dict.get("playbook_action")
        ),
        "approval_playbook_message": _normalize_validation_alert_text(
            payload_dict.get("approval_playbook_message") or payload_dict.get("playbook_message")
        ),
    }


def validation_alert_strip_summary(payload: Mapping[str, Any] | None) -> dict[str, str]:
    payload_dict = _mapping(payload)
    existing = _approval_strip_summary(payload_dict.get("approval_strip_summary"))
    if any(existing.values()):
        return {
            "primary_reason": _normalize_validation_alert_text(existing.get("primary_reason", "")),
            "approve_value": existing.get("approve_value") or "n/a",
            "approve_reason": _normalize_validation_alert_text(existing.get("approve_reason", "")),
            "align_value": existing.get("align_value") or "n/a",
            "align_reason": _normalize_validation_alert_text(existing.get("align_reason", "")),
            "act_value": existing.get("act_value") or "review_validation_alert_contract",
            "act_reason": _normalize_validation_alert_text(existing.get("act_reason", "")),
            "act_priority_level": existing.get("act_priority_level") or "monitor",
        }

    contract = validation_alert_contract(payload_dict)
    deployment_go_no_go = _text(contract.get("deployment_go_no_go")).upper()
    playbook_go_no_go = _text(contract.get("approval_playbook_go_no_go")).upper() or deployment_go_no_go
    approval_summary_line = _text(contract.get("approval_topline_summary_line"))
    deployment_message = _text(contract.get("deployment_message"))
    playbook_message = _text(contract.get("approval_playbook_message"))
    approve_map = {
        "GO": "approval usable",
        "MANUAL_REVIEW": "manual review first",
        "NO_GO": "validation no_go",
    }
    priority_map = {"GO": "monitor", "MANUAL_REVIEW": "watch", "NO_GO": "urgent"}
    return {
        "primary_reason": _normalize_validation_alert_text(approval_summary_line or playbook_message or deployment_message),
        "approve_value": approve_map.get(deployment_go_no_go, deployment_go_no_go.lower() or "n/a"),
        "approve_reason": _normalize_validation_alert_text(approval_summary_line or deployment_message or playbook_message),
        "align_value": "aligned" if not playbook_go_no_go or playbook_go_no_go == deployment_go_no_go else "playbook_drift",
        "align_reason": _normalize_validation_alert_text(playbook_message or approval_summary_line or deployment_message),
        "act_value": _text(contract.get("approval_playbook_action")) or "review_validation_alert_contract",
        "act_reason": _normalize_validation_alert_text(playbook_message or deployment_message or approval_summary_line),
        "act_priority_level": priority_map.get(deployment_go_no_go, "monitor"),
    }


def alert_contract_defaults(payload: Mapping[str, Any] | None) -> dict[str, str]:
    contract = validation_alert_contract(payload)
    contract["deployment_go_no_go"] = contract["deployment_go_no_go"] or "MANUAL_REVIEW"
    contract["deployment_code"] = contract["deployment_code"] or "manual_review_approval_template_missing"
    contract["deployment_message"] = contract["deployment_message"] or (
        "MANUAL REVIEW: approval template deployment language is unavailable."
    )
    return contract
