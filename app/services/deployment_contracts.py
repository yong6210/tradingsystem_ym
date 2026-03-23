from __future__ import annotations

from typing import Any, Mapping


def _text(value: Any) -> str:
    return str(value or "")


def approval_summary_passthrough(summary: Mapping[str, Any] | None) -> dict[str, str]:
    summary_dict = dict(summary or {})
    return {
        "deployment_go_no_go": _text(summary_dict.get("playbook_go_no_go")),
        "deployment_code": _text(summary_dict.get("playbook_code")),
        "deployment_message": _text(summary_dict.get("playbook_message")),
        "approval_topline_status": _text(summary_dict.get("topline_status")),
        "approval_topline_code": _text(summary_dict.get("topline_code")),
        "approval_topline_message": _text(summary_dict.get("topline_message")),
        "approval_topline_summary_line": _text(summary_dict.get("topline_summary_line")),
        "playbook_go_no_go": _text(summary_dict.get("playbook_go_no_go")),
        "playbook_code": _text(summary_dict.get("playbook_code")),
        "playbook_action": _text(summary_dict.get("playbook_action")),
        "playbook_message": _text(summary_dict.get("playbook_message")),
    }


def validation_report_contract(payload: Mapping[str, Any] | None) -> dict[str, str]:
    payload_dict = dict(payload or {})
    report = dict(payload_dict.get("validation_report") or {})
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
    payload_dict = dict(payload or {})
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
        "deployment_message": _text(
            payload_dict.get("deployment_message")
            or payload_dict.get("approval_playbook_message")
            or payload_dict.get("playbook_message")
        ),
        "approval_topline_summary_line": _text(
            payload_dict.get("approval_topline_summary_line") or payload_dict.get("topline_summary_line")
        ),
        "approval_playbook_go_no_go": _text(
            payload_dict.get("approval_playbook_go_no_go") or payload_dict.get("playbook_go_no_go")
        ),
        "approval_playbook_code": _text(payload_dict.get("approval_playbook_code") or payload_dict.get("playbook_code")),
        "approval_playbook_action": _text(
            payload_dict.get("approval_playbook_action") or payload_dict.get("playbook_action")
        ),
        "approval_playbook_message": _text(
            payload_dict.get("approval_playbook_message") or payload_dict.get("playbook_message")
        ),
    }


def alert_contract_defaults(payload: Mapping[str, Any] | None) -> dict[str, str]:
    contract = validation_alert_contract(payload)
    contract["deployment_go_no_go"] = contract["deployment_go_no_go"] or "MANUAL_REVIEW"
    contract["deployment_code"] = contract["deployment_code"] or "manual_review_approval_template_missing"
    contract["deployment_message"] = contract["deployment_message"] or (
        "MANUAL REVIEW: approval template deployment language is unavailable."
    )
    return contract
