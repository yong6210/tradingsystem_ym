#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT_DIR = Path(__file__).resolve().parents[1]

_SPLIT_ACTIONS: dict[str, dict[str, str]] = {
    "run_entry_timing_split_review": {
        "axis": "entry_timing",
        "target_key": "entry_timing_target",
        "preferred_key": "entry_timing_preferred_variant",
    },
    "run_execution_style_split_review": {
        "axis": "execution_style",
        "target_key": "execution_style_target",
        "preferred_key": "execution_style_preferred_variant",
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a concrete follow-up packet for split-review actions from the latest operator priority."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--symbol", default="BTCUSDC")
    parser.add_argument("--universe", default="usdc_perp_top30")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument(
        "--action",
        default="auto",
        choices=["auto", *sorted(_SPLIT_ACTIONS)],
        help="Pick a specific split-review action or let the script choose the highest-priority split action.",
    )
    parser.add_argument("--report-dir", default="reports/operations/split_review_followups")
    parser.add_argument("--no-write-report", action="store_true")
    return parser.parse_args()


def _now() -> datetime:
    return datetime.now(UTC)


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _request_json(
    base_url: str,
    method: str,
    path: str,
    *,
    query: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
) -> dict[str, Any] | list[Any]:
    url = f"{base_url.rstrip('/')}{path}"
    if query:
        url += f"?{urlencode(query, doseq=True)}"
    data: bytes | None = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url=url, data=data, headers=headers, method=method.upper())
    try:
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method.upper()} {path} failed with HTTP {exc.code}: {payload}") from exc
    except URLError as exc:
        raise RuntimeError(f"{method.upper()} {path} failed: {exc.reason}") from exc


def _dict(payload: dict[str, Any] | None) -> dict[str, Any]:
    return dict(payload or {})


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _operator_action_priority(
    *,
    dashboard_payload: dict[str, Any] | None,
    validation_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    dashboard_source = _dict(
        (((dashboard_payload or {}).get("signal_funnel") or {}).get("operator_action_priority"))
    )
    validation_source = _dict(
        (((validation_payload or {}).get("validation_report") or validation_payload or {}).get("operator_action_priority_summary"))
    )
    return dashboard_source or validation_source


def _edge_experiment_review(
    *,
    dashboard_payload: dict[str, Any] | None,
    validation_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    dashboard_source = _dict(
        (((dashboard_payload or {}).get("signal_funnel") or {}).get("edge_experiment_review"))
    )
    validation_source = _dict(
        (((validation_payload or {}).get("validation_report") or validation_payload or {}).get("edge_experiment_review_summary"))
    )
    source = dashboard_source or validation_source
    source_summary = _dict(source.get("source_summary"))
    return {
        "edge_state": str(source.get("edge_state") or "insufficient_edge_measurement"),
        "true_edge_ratio": round(_float(source.get("true_edge_ratio")), 4),
        "edge_decay_rate": round(_float(source.get("edge_decay_rate")), 4),
        "entry_timing_preferred_variant": str(
            source.get("entry_timing_preferred_variant") or source_summary.get("entry_timing_preferred_variant") or "none"
        ),
        "execution_style_preferred_variant": str(
            source.get("execution_style_preferred_variant")
            or source_summary.get("execution_style_preferred_variant")
            or "none"
        ),
        "summary": str(source.get("summary") or ""),
    }


def _approval_strip(
    *,
    dashboard_payload: dict[str, Any] | None,
    validation_payload: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    dashboard_strip = _dict((dashboard_payload or {}).get("approval_strip_summary"))
    validation_strip = _dict(
        (((validation_payload or {}).get("validation_report") or {}).get("approval_strip_summary"))
    )
    return {
        "dashboard": dashboard_strip,
        "validation": validation_strip,
    }


def _select_action(priority: dict[str, Any], requested_action: str) -> tuple[str, str]:
    if requested_action != "auto":
        return requested_action, "explicit_request"

    top_action = str(priority.get("top_action") or "")
    if top_action in _SPLIT_ACTIONS:
        return top_action, "top_action"

    for row in list(priority.get("next_actions") or []):
        action = str(_dict(row).get("action") or "")
        if action in _SPLIT_ACTIONS:
            return action, "next_actions"
    return "", "no_split_action_available"


def _target_from_priority(priority: dict[str, Any], action: str) -> dict[str, Any] | None:
    spec = _SPLIT_ACTIONS.get(action)
    if not spec:
        return None
    context = _dict(priority.get("experiment_context"))
    target = _dict(context.get(spec["target_key"]))
    if not target:
        matching_row = next(
            (
                _dict(row)
                for row in list(priority.get("next_actions") or [])
                if str(_dict(row).get("action") or "") == action
            ),
            {},
        )
        if matching_row.get("target_symbol"):
            target = {
                "symbol": str(matching_row.get("target_symbol") or ""),
                "status": str(matching_row.get("target_status") or ""),
                "strategy_family": str(matching_row.get("target_family") or ""),
                "block_reason": str(matching_row.get("target_block_reason") or ""),
                "focus_source": str(matching_row.get("target_focus_source") or ""),
            }
    if not target:
        return None
    return {
        "action": action,
        "axis": spec["axis"],
        "preferred_variant": str(context.get(spec["preferred_key"]) or "none"),
        "symbol": str(target.get("symbol") or ""),
        "status": str(target.get("status") or ""),
        "strategy_family": str(target.get("strategy_family") or ""),
        "block_reason": str(target.get("block_reason") or ""),
        "focus_source": str(target.get("focus_source") or ""),
    }


def _review_steps(action: str, target: dict[str, Any] | None) -> list[str]:
    target_contract = _dict(target)
    symbol = str(target_contract.get("symbol") or "target_symbol")
    family = str(target_contract.get("strategy_family") or "unknown_family")
    preferred_variant = str(target_contract.get("preferred_variant") or "none")
    if action == "run_entry_timing_split_review":
        return [
            f"Compare the preferred entry timing branch `{preferred_variant}` against the current target row `{symbol}` / `{family}`.",
            "Keep approval, sizing, and rollout authority unchanged; this packet is advisory research context only.",
            "After new closes arrive, re-read score_to_outcome_funnel and outcome_attribution before changing entry design.",
        ]
    if action == "run_execution_style_split_review":
        return [
            f"Compare the preferred execution style `{preferred_variant}` against the current target row `{symbol}` / `{family}`.",
            "Keep approval, sizing, and rollout authority unchanged; this packet is advisory research context only.",
            "After new fills and closes arrive, re-read fill-capture and post-cost drag before changing execution mode.",
        ]
    return ["No split review action is currently available from operator_action_priority."]


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Split Review Followup",
        "",
        f"- generated_at: {payload['generated_at']}",
        f"- symbol: {payload['symbol']}",
        f"- universe: {payload['universe']}",
        f"- days: {payload['days']}",
        f"- status: {payload['status']}",
        f"- selected_action: {payload['selected_action']}",
        f"- selection_reason: {payload['selection_reason']}",
        "",
        "## Target Contract",
        "",
    ]
    target = _dict(payload.get("target_contract"))
    if target:
        lines.extend(
            [
                f"- action: {target.get('action')}",
                f"- axis: {target.get('axis')}",
                f"- preferred_variant: {target.get('preferred_variant')}",
                f"- symbol: {target.get('symbol')}",
                f"- status: {target.get('status')}",
                f"- strategy_family: {target.get('strategy_family')}",
                f"- block_reason: {target.get('block_reason')}",
                f"- focus_source: {target.get('focus_source')}",
            ]
        )
    else:
        lines.append("- target contract unavailable")
    lines.extend(
        [
            "",
            "## Operator Context",
            "",
            (
                f"- operator_action_priority: top_action={payload['operator_action_priority'].get('top_action')} "
                f"| priority={payload['operator_action_priority'].get('priority_level')} "
                f"| source={payload['operator_action_priority'].get('priority_source')}"
            ),
            f"- top_reason: {payload['operator_action_priority'].get('top_reason')}",
            (
                f"- edge_experiment: state={payload['edge_experiment_review'].get('edge_state')} "
                f"| true_edge={payload['edge_experiment_review'].get('true_edge_ratio')} "
                f"| decay={payload['edge_experiment_review'].get('edge_decay_rate')}"
            ),
            "",
            "## Review Steps",
            "",
        ]
    )
    for step in payload.get("review_steps") or []:
        lines.append(f"- {step}")
    lines.extend(
        [
            "",
            "## Raw Payload",
            "",
            "```json",
            json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default),
            "```",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    generated_at = _now()
    dashboard = _request_json(
        args.base_url,
        "GET",
        "/execution/operator-dashboard",
        query={"symbol": args.symbol, "universe": args.universe, "days": args.days},
    )
    validation = _request_json(
        args.base_url,
        "POST",
        "/validation/report",
        body={"symbol": args.symbol, "universe": args.universe},
    )
    priority = _operator_action_priority(dashboard_payload=dashboard, validation_payload=validation)
    selected_action, selection_reason = _select_action(priority, args.action)
    target_contract = _target_from_priority(priority, selected_action)
    status = "READY"
    if not selected_action:
        status = "NO_SPLIT_ACTION_AVAILABLE"
    elif not target_contract:
        status = "NO_TARGET"

    payload: dict[str, Any] = {
        "generated_at": generated_at.isoformat(),
        "symbol": args.symbol.upper(),
        "universe": args.universe,
        "days": args.days,
        "status": status,
        "selected_action": selected_action or "none",
        "selection_reason": selection_reason,
        "operator_action_priority": {
            "top_action": str(priority.get("top_action") or "continue_runtime_monitoring"),
            "top_reason": str(priority.get("top_reason") or ""),
            "priority_level": str(priority.get("priority_level") or "monitor"),
            "priority_source": str(priority.get("priority_source") or "monitor"),
        },
        "edge_experiment_review": _edge_experiment_review(
            dashboard_payload=dashboard,
            validation_payload=validation,
        ),
        "approval_strips": _approval_strip(
            dashboard_payload=dashboard,
            validation_payload=validation,
        ),
        "target_contract": target_contract,
        "review_steps": _review_steps(selected_action, target_contract),
    }

    if not args.no_write_report:
        ts = generated_at.strftime("%Y%m%dT%H%M%SZ")
        report_path = ROOT_DIR / args.report_dir / f"split_review_followup_{args.symbol.upper()}_{ts}.md"
        _write_report(report_path, payload)
        payload["report_path"] = str(report_path.relative_to(ROOT_DIR))

    print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
