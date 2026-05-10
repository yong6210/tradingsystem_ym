#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

def _reexec_runtime_python_if_available() -> None:
    if os.environ.get("TRADING_PROMOTION_READINESS_BOOTSTRAPPED"):
        return
    runtime_python = Path.home() / "Library/Application Support/trading/runtime_venv/bin/python"
    if not runtime_python.exists():
        return
    try:
        if runtime_python.resolve() == Path(sys.executable).resolve():
            return
    except OSError:
        return
    env = dict(os.environ)
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = f"{ROOT}{os.pathsep}{existing_pythonpath}" if existing_pythonpath else str(ROOT)
    env["TRADING_PROMOTION_READINESS_BOOTSTRAPPED"] = "1"
    os.execve(str(runtime_python), [str(runtime_python), str(Path(__file__).resolve()), *sys.argv[1:]], env)


try:
    from app.db.session import SessionLocal, init_db
    from app.services.live_candidate_promotion_readiness_runtime import (
        build_live_candidate_promotion_readiness_payload,
    )
except ModuleNotFoundError:
    _reexec_runtime_python_if_available()
    raise
from scripts.operation_report_io import atomic_write_text, display_path, parse_report_generated_at, write_latest_aliases


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize live candidate promotion readiness without changing live authority.")
    parser.add_argument("--symbol", default="", help="Optional symbol filter, for example ADAUSDC.")
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--report-dir", default="reports/operations/live_candidate_promotion_readiness")
    parser.add_argument("--no-write-report", action="store_true")
    parser.add_argument("--compact", action="store_true", help="Print a compact operator summary instead of JSON.")
    return parser.parse_args()


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _display_path(path: Path) -> str:
    return display_path(path, ROOT)


def build_payload(*, hours: int, limit: int, symbol: str | None = None) -> dict[str, Any]:
    init_db()
    with SessionLocal() as db:
        return build_live_candidate_promotion_readiness_payload(
            db,
            hours=max(1, int(hours)),
            limit=max(1, int(limit)),
            symbol=symbol,
        )


def _write_report(path: Path, payload: dict[str, Any], *, atomic: bool = False) -> None:
    readiness = dict(payload.get("readiness") or {})
    lines = [
        "# Live Candidate Promotion Readiness",
        "",
        f"- generated_at: {payload.get('generated_at')}",
        f"- symbol: {payload.get('symbol') or 'ALL'}",
        f"- authority: {readiness.get('authority')}",
        f"- headline_state: {readiness.get('headline_state')}",
        f"- headline_reason: {readiness.get('headline_reason')}",
        f"- headline_action: {readiness.get('headline_action')}",
        f"- promotion_decision: {readiness.get('promotion_decision')}",
        f"- latest_evidence_at: {readiness.get('latest_evidence_at') or 'n/a'}",
        f"- latest_evidence_age_seconds: {readiness.get('latest_evidence_age_seconds')}",
        f"- latest_evidence_freshness: {readiness.get('latest_evidence_freshness')}",
        f"- headline_evidence_at: {readiness.get('headline_evidence_at') or 'n/a'}",
        f"- headline_evidence_age_seconds: {readiness.get('headline_evidence_age_seconds')}",
        f"- headline_evidence_freshness: {readiness.get('headline_evidence_freshness')}",
        f"- headline_candidate_symbols: {readiness.get('headline_candidate_symbols')}",
        f"- candidate_count: {readiness.get('candidate_count')}",
        f"- state_counts: {readiness.get('state_counts')}",
        f"- evidence_freshness_counts: {readiness.get('evidence_freshness_counts')}",
        f"- attention_flags: {readiness.get('attention_flags')}",
        f"- top_blockers: {readiness.get('top_blockers')}",
        f"- top_intent_reasons: {readiness.get('top_intent_reasons')}",
        f"- top_audit_statuses: {readiness.get('top_audit_statuses')}",
        "",
        "## Operator Review Items",
        "",
    ]
    for item in list(readiness.get("operator_review_items") or [])[:10]:
        lines.append(
            "- "
            f"{item.get('symbol')}/{item.get('strategy_family')}: "
            f"attention={item.get('attention')} state={item.get('promotion_state')} "
            f"blocker={item.get('primary_blocker')} latest={item.get('latest_evidence_at') or 'n/a'} "
            f"freshness={item.get('evidence_freshness')} action={item.get('next_action')}"
        )
    if not readiness.get("operator_review_items"):
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Candidate Rows",
            "",
        ]
    )
    for row in list(readiness.get("candidates") or [])[:20]:
        lines.append(
            "- "
            f"{row.get('symbol')}/{row.get('strategy_family')}: "
            f"state={row.get('promotion_state')} severity={row.get('severity')} "
            f"blocker={row.get('primary_blocker')} secondary={row.get('secondary_blockers')} "
            f"latest={row.get('latest_evidence_at') or 'n/a'} freshness={row.get('evidence_freshness')} "
            f"action={row.get('next_action')}"
        )
    if not readiness.get("candidates"):
        lines.append("- none")
    lines.extend(["", "```json", json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default), "```"])
    content = "\n".join(lines)
    if atomic:
        atomic_write_text(path, content)
    else:
        atomic_write_text(path, content)


def _compact_text(payload: dict[str, Any]) -> str:
    readiness = dict(payload.get("readiness") or {})
    lines = [
        "live_candidate_promotion_readiness:",
        f"- symbol={payload.get('symbol') or 'ALL'}",
        f"- state={readiness.get('headline_state')} reason={readiness.get('headline_reason')}",
        f"- promotion_decision={readiness.get('promotion_decision')}",
        f"- action={readiness.get('headline_action')}",
        f"- latest_evidence_at={readiness.get('latest_evidence_at') or 'n/a'} "
        f"age_seconds={readiness.get('latest_evidence_age_seconds')} "
        f"freshness={readiness.get('latest_evidence_freshness')}",
        f"- headline_evidence_at={readiness.get('headline_evidence_at') or 'n/a'} "
        f"age_seconds={readiness.get('headline_evidence_age_seconds')} "
        f"freshness={readiness.get('headline_evidence_freshness')} "
        f"symbols={readiness.get('headline_candidate_symbols')}",
        f"- candidate_count={readiness.get('candidate_count')} state_counts={readiness.get('state_counts')}",
        f"- evidence_freshness_counts={readiness.get('evidence_freshness_counts')}",
        f"- attention_flags={readiness.get('attention_flags')}",
        f"- top_blockers={readiness.get('top_blockers')}",
        f"- top_intent_reasons={readiness.get('top_intent_reasons')}",
    ]
    for item in list(readiness.get("operator_review_items") or [])[:5]:
        lines.append(
            "- review "
            f"{item.get('symbol')}/{item.get('strategy_family')} "
            f"attention={item.get('attention')} state={item.get('promotion_state')} "
            f"blocker={item.get('primary_blocker')} freshness={item.get('evidence_freshness')}"
        )
    for row in list(readiness.get("candidates") or [])[:8]:
        secondary = dict(row.get("secondary_blockers") or {})
        secondary_text = f" secondary={secondary}" if secondary else ""
        lines.append(
            "- "
            f"{row.get('symbol')}/{row.get('strategy_family')} "
            f"state={row.get('promotion_state')} blocker={row.get('primary_blocker')} "
            f"latest={row.get('latest_evidence_at') or 'n/a'} "
            f"freshness={row.get('evidence_freshness')}{secondary_text}"
        )
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    payload = build_payload(
        hours=max(1, int(args.hours)),
        limit=max(1, int(args.limit)),
        symbol=str(args.symbol or ""),
    )
    if not args.no_write_report:
        report_dir = ROOT / str(args.report_dir)
        generated = parse_report_generated_at(payload.get("generated_at"))
        report_path = report_dir / f"live_candidate_promotion_readiness_{generated.strftime('%Y%m%dT%H%M%SZ')}.md"
        payload["report_path"] = _display_path(report_path)
        payload["latest_report_path"] = _display_path(report_dir / "latest.md")
        payload["latest_json_path"] = _display_path(report_dir / "latest.json")
        _write_report(report_path, payload, atomic=True)
        payload.update(
            write_latest_aliases(
                report_dir=report_dir,
                payload=payload,
                write_markdown_report=_write_report,
                root_dir=ROOT,
                json_default=_json_default,
            )
        )
    if args.compact:
        print(_compact_text(payload))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))


if __name__ == "__main__":
    main()
