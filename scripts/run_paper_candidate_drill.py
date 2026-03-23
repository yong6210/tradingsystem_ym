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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a PAPER candidate drill for eligible strategy families against the local API."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--symbol", default=None, help="Optional symbol pin. If omitted, pick the best eligible candidate.")
    parser.add_argument("--universe", default="usdc_perp_top30")
    parser.add_argument("--families", default="trend_continuation,sweep_reversal")
    parser.add_argument("--candidate-limit", type=int, default=100)
    parser.add_argument("--include-manual-review", action="store_true")
    parser.add_argument("--skip-sync", action="store_true")
    parser.add_argument("--limit-symbols", type=int, default=30)
    parser.add_argument("--symbol-concurrency", type=int, default=4)
    parser.add_argument("--limit-1m", type=int, default=900)
    parser.add_argument("--limit-5m", type=int, default=500)
    parser.add_argument("--limit-15m", type=int, default=500)
    parser.add_argument("--submit-paper", action="store_true")
    parser.add_argument("--paper-scenario", default="fill", choices=["fill", "partial_fill", "cancel", "timeout", "reject", "attach_failure"])
    parser.add_argument(
        "--paper-lineage-override",
        action="store_true",
        help="Allow PAPER-only lineage override for eligible family candidates blocked by active-plan thesis duplication.",
    )
    parser.add_argument("--report-dir", default="reports/operations/paper_candidate_drill")
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
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method.upper()} {path} failed with HTTP {exc.code}: {payload}") from exc
    except URLError as exc:
        raise RuntimeError(f"{method.upper()} {path} failed: {exc.reason}") from exc


def _status(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


def _family_set(raw: str) -> set[str]:
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


def _is_allowed_runtime_state(row: dict[str, Any], include_manual: bool) -> bool:
    state = str(row.get("deployment_go_no_go") or "").upper()
    if state == "GO":
        return True
    return include_manual and state == "MANUAL_REVIEW"


def _choose_candidate(rows: list[dict[str, Any]], *, symbol: str | None, families: set[str], include_manual: bool) -> dict[str, Any] | None:
    filtered: list[dict[str, Any]] = []
    for row in rows:
        family = str(row.get("strategy_family") or "").lower()
        if family not in families:
            continue
        if symbol and str(row.get("symbol") or "").upper() != symbol.upper():
            continue
        if not _is_allowed_runtime_state(row, include_manual):
            continue
        if float(row.get("recommended_risk_r") or 0.0) <= 0.0:
            continue
        filtered.append(row)
    if not filtered:
        return None
    filtered.sort(
        key=lambda row: (
            float(row.get("expected_ev_at_recommended_size_r") or 0.0),
            float(row.get("expected_ev_r") or 0.0),
            float(row.get("recommended_risk_r") or 0.0),
        ),
        reverse=True,
    )
    return filtered[0]


def _portfolio_candidates(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in ("accepted_candidates", "blocked_candidates"):
        value = payload.get(key)
        if isinstance(value, list):
            rows.extend(item for item in value if isinstance(item, dict))
    return rows


def _choose_override_candidate(
    rows: list[dict[str, Any]],
    *,
    symbol: str | None,
    families: set[str],
    include_manual: bool,
) -> dict[str, Any] | None:
    eligible_blocks = {"thesis_duplicate_blocked", "thesis_active_cap_reached"}
    filtered: list[dict[str, Any]] = []
    for row in rows:
        family = str(row.get("strategy_family") or "").lower()
        if family not in families:
            continue
        if symbol and str(row.get("symbol") or "").upper() != symbol.upper():
            continue
        if not _is_allowed_runtime_state(row, include_manual):
            continue
        if float(row.get("recommended_risk_r") or 0.0) <= 0.0:
            continue
        if str(row.get("strategy_grade") or "").upper() != "A":
            continue
        if str(row.get("block_reason") or "") not in eligible_blocks:
            continue
        filtered.append(row)
    if not filtered:
        return None
    filtered.sort(
        key=lambda row: (
            float(row.get("expected_ev_at_recommended_size_r") or 0.0),
            float(row.get("expected_ev_r") or 0.0),
            float(row.get("recommended_risk_r") or 0.0),
        ),
        reverse=True,
    )
    return filtered[0]


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    lines.append("# PAPER Candidate Drill")
    lines.append("")
    lines.append(f"- generated_at: {payload['generated_at']}")
    lines.append(f"- overall_status: {payload['overall_status']}")
    lines.append(f"- summary: {payload['summary_line']}")
    lines.append("")
    lines.append("## Checks")
    lines.append("")
    for row in payload["checks"]:
        lines.append(f"- [{row['status']}] {row['name']}: {row['message']}")
    lines.append("")
    lines.append("## Candidate")
    lines.append("")
    candidate = payload.get("candidate") or {}
    if candidate:
        lines.append(f"- symbol: {candidate.get('symbol', '')}")
        lines.append(f"- plan_id: {candidate.get('plan_id', '')}")
        lines.append(f"- family: {candidate.get('strategy_family', '')}")
        lines.append(f"- deployment: {candidate.get('deployment_go_no_go', '')}")
        lines.append(f"- expected_summary: {candidate.get('expected_summary', '')}")
    else:
        lines.append("- no eligible candidate found")
    lines.append("")
    lines.append("## Next Steps")
    lines.append("")
    for step in payload.get("next_steps", []):
        lines.append(f"- {step}")
    lines.append("")
    lines.append("## Raw Payload")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    lines.append("```")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    generated_at = _now()
    families = _family_set(args.families)

    sync_payload: dict[str, Any] | None = None
    if not args.skip_sync:
        sync_payload = _request_json(
            args.base_url,
            "POST",
            "/internal/binance/sync-universe",
            query={
                "limit_symbols": args.limit_symbols,
                "symbol_concurrency": args.symbol_concurrency,
                "limit_1m": args.limit_1m,
                "limit_5m": args.limit_5m,
                "limit_15m": args.limit_15m,
            },
        )

    scanner = _request_json(
        args.base_url,
        "GET",
        "/scanner/top",
        query={"universe": args.universe, "limit": args.candidate_limit},
    )
    scanner_rows = scanner if isinstance(scanner, list) else []
    candidate = _choose_candidate(
        scanner_rows,
        symbol=args.symbol,
        families=families,
        include_manual=args.include_manual_review,
    )
    portfolio_payload: dict[str, Any] | None = None
    if candidate is None and args.paper_lineage_override:
        portfolio_raw = _request_json(
            args.base_url,
            "GET",
            "/portfolio/budget",
            query={"universe": args.universe, "limit": args.candidate_limit, "write_report": "false"},
        )
        portfolio_payload = portfolio_raw if isinstance(portfolio_raw, dict) else {}
        candidate = _choose_override_candidate(
            _portfolio_candidates(portfolio_payload),
            symbol=args.symbol,
            families=families,
            include_manual=args.include_manual_review,
        )

    preview: dict[str, Any] | None = None
    approval: dict[str, Any] | None = None
    intent: dict[str, Any] | None = None
    submission: dict[str, Any] | None = None
    if candidate is not None:
        preview_body = {
            "plan_id": candidate["plan_id"],
            "paper_lineage_override": bool(args.paper_lineage_override),
        }
        preview = _request_json(
            args.base_url,
            "POST",
            "/execution/plans/preview",
            body=preview_body,
        )
        approval = _request_json(
            args.base_url,
            "POST",
            "/execution/approve-plan",
            body=preview_body,
        )
        intent = _request_json(
            args.base_url,
            "POST",
            "/execution/order-intents",
            body={
                "plan_id": candidate["plan_id"],
                "execution_mode": "PAPER",
                "paper_lineage_override": bool(args.paper_lineage_override),
            },
        )
        if args.submit_paper and str(intent.get("submit_decision") or "") == "SUBMIT":
            submission = _request_json(
                args.base_url,
                "POST",
                "/execution/submit",
                body={
                    "intent_id": intent["intent_id"],
                    "live": False,
                    "paper_scenario": args.paper_scenario,
                },
            )

    checks: list[dict[str, str]] = []
    if sync_payload is not None:
        checks.append(
            {
                "name": "universe_sync",
                "status": _status(int(sync_payload.get("success", 0) or 0) > 0 or int(sync_payload.get("processed_symbols", 0) or 0) > 0),
                "message": f"success={sync_payload.get('success', 0)} failed={sync_payload.get('failed', 0)} processed={sync_payload.get('processed_symbols', 0)}",
            }
        )
    checks.append(
        {
            "name": "eligible_candidate_found",
            "status": _status(candidate is not None),
            "message": (
                "No eligible trend_continuation/sweep_reversal candidate found in scanner output."
                if candidate is None
                else (
                    f"{candidate.get('symbol')} {candidate.get('strategy_family')} {candidate.get('deployment_go_no_go')}"
                    + (
                        " via paper lineage override"
                        if bool(args.paper_lineage_override)
                        and str(candidate.get("block_reason") or "") in {"thesis_duplicate_blocked", "thesis_active_cap_reached"}
                        else ""
                    )
                )
            ),
        }
    )
    if candidate is not None:
        checks.append(
            {
                "name": "preview_ready",
                "status": _status(preview is not None),
                "message": f"entry_type={preview.get('entry_type', '')} semantics={preview.get('entry_semantics', '')}" if preview else "preview unavailable",
            }
        )
        approval_state = str((approval or {}).get("approval_state") or "")
        allowed_execution_mode = str((approval or {}).get("allowed_execution_mode") or "")
        checks.append(
            {
                "name": "approval_for_paper",
                "status": _status(approval_state in {"APPROVED_AUTO", "APPROVED_MANUAL"} and allowed_execution_mode in {"PAPER", "MICRO_LIVE", "LIVE"}),
                "message": (
                    f"approval_state={approval_state} allowed_execution_mode={allowed_execution_mode}"
                    + (
                        f" override={approval.get('paper_lineage_override_reason', '')}"
                        if approval and approval.get("paper_lineage_override_applied")
                        else ""
                    )
                ),
            }
        )
        submit_decision = str((intent or {}).get("submit_decision") or "")
        checks.append(
            {
                "name": "intent_submit_ready",
                "status": _status(submit_decision == "SUBMIT"),
                "message": f"submit_decision={submit_decision or 'unknown'} reason={(intent or {}).get('decision_reason_code', '')}",
            }
        )
        if args.submit_paper:
            checks.append(
                {
                    "name": "paper_submit",
                    "status": _status(submission is not None and str(submission.get('submit_status') or "") in {"FILLED", "ACKNOWLEDGED", "PARTIALLY_FILLED"}),
                    "message": (
                        "paper submit not attempted"
                        if submission is None
                        else f"submit_status={submission.get('submit_status', '')} state={submission.get('state', '')}"
                    ),
                }
            )

    fail_count = sum(1 for row in checks if row["status"] == "FAIL")
    overall_status = "READY_FOR_PAPER_SAMPLE" if fail_count == 0 else "NOT_READY"

    next_steps: list[str] = []
    if candidate is None:
        next_steps.append("Wait for London/New York session and rerun this helper until an eligible family candidate appears.")
        next_steps.append("Keep focus on trend_continuation or sweep_reversal families; legacy_zone_plan does not advance MICRO_LIVE lineage.")
    else:
        if intent is not None and str(intent.get("submit_decision") or "") != "SUBMIT":
            next_steps.append(f"Candidate found but PAPER intent is not submit-ready: {(intent or {}).get('decision_reason_message', '')}")
        elif not args.submit_paper:
            next_steps.append("Rerun with --submit-paper to create a PAPER submission once the candidate looks acceptable.")
        elif submission is not None:
            next_steps.append("Monitor execution/operator-dashboard and validation/report after the PAPER submission closes.")
            next_steps.append("Repeat this drill until enough closed v2 trades exist to resolve threshold lineage winner.")
    if submission is None and args.submit_paper:
        next_steps.append("No PAPER submission occurred in this run.")

    payload = {
        "generated_at": generated_at.isoformat(),
        "symbol": (args.symbol or "").upper() or None,
        "universe": args.universe,
        "families": sorted(families),
        "paper_lineage_override": bool(args.paper_lineage_override),
        "overall_status": overall_status,
        "summary_line": (
            "Eligible PAPER candidate is ready."
            if overall_status == "READY_FOR_PAPER_SAMPLE"
            else f"{fail_count} blocking drill check(s) remain."
        ),
        "checks": checks,
        "sync": sync_payload,
        "portfolio": portfolio_payload,
        "candidate": candidate,
        "preview": preview,
        "approval": approval,
        "intent": intent,
        "submission": submission,
        "next_steps": next_steps,
    }

    if not args.no_write_report:
        ts = generated_at.strftime("%Y%m%dT%H%M%SZ")
        symbol_tag = (candidate or {}).get("symbol") or (args.symbol or "UNIVERSE").upper()
        report_path = ROOT_DIR / args.report_dir / f"paper_candidate_drill_{symbol_tag}_{ts}.md"
        _write_report(report_path, payload)
        payload["report_path"] = str(report_path.relative_to(ROOT_DIR))

    print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    return 0 if overall_status == "READY_FOR_PAPER_SAMPLE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
