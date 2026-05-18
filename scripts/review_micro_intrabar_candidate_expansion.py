#!/usr/bin/env python3
from __future__ import annotations

import argparse
import glob
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.report_io import atomic_write_text
from scripts.review_micro_intrabar_candidate_replay import _load_trade_rows, _passes_contract
from scripts.run_micro_main_exit_policy_search import summarize_rows
from scripts.run_micro_main_intrabar_subset_report import _cost_stress


DEFAULT_CONTRACT_PATH = ROOT_DIR / "reports/operations/micro_intrabar_paper_candidate_contract/latest.json"
DEFAULT_REPORT_GLOB = ROOT_DIR / "reports/validation/micro_main_intrabar_research/micro_main_intrabar_research_*.json"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Review whether the micro intrabar paper candidate can expand beyond its narrow symbol set.")
    parser.add_argument("--contract-path", default=str(DEFAULT_CONTRACT_PATH))
    parser.add_argument("--report-path", action="append", default=[])
    parser.add_argument("--report-glob", default=str(DEFAULT_REPORT_GLOB))
    parser.add_argument("--report-dir", default="reports/operations/micro_intrabar_candidate_expansion_review")
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def _resolve_path(raw: str) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = ROOT_DIR / path
    return path


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed == parsed else default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _report_stamp(value: datetime) -> str:
    return value.strftime("%Y%m%dT%H%M%S%fZ")


def _expand_paths(report_paths: list[str], report_glob: str) -> list[Path]:
    explicit: list[str] = []
    for item in report_paths:
        explicit.extend(part.strip() for part in str(item or "").split(",") if part.strip())
    raw_paths = explicit or sorted(glob.glob(str(_resolve_path(report_glob))))
    paths: list[Path] = []
    seen: set[Path] = set()
    for raw in raw_paths:
        path = _resolve_path(raw)
        if path.exists() and path not in seen:
            paths.append(path)
            seen.add(path)
    return paths


def _grouped_rows(rows: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if key == "symbol":
            value = str(row.get("symbol") or "UNKNOWN").upper()
        elif key == "year":
            value = str(row.get("entry_year") or str(row.get("entry_ts") or "")[:4] or "unknown")
        else:
            value = str(row.get(key) or "unknown")
        grouped.setdefault(value, []).append(row)
    return dict(sorted(grouped.items()))


def _grouped_summaries(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    return {name: summarize_rows(items) for name, items in _grouped_rows(rows, key).items()}


def _report_scope(payload: dict[str, Any]) -> dict[str, Any]:
    scope = dict(payload.get("scope") or {})
    symbols = [str(symbol).strip().upper() for symbol in list(scope.get("symbols") or []) if str(symbol).strip()]
    return {
        "symbols": symbols,
        "symbol_count": len(symbols),
        "days": _safe_int(scope.get("days")),
        "entry_timing_model": scope.get("entry_timing_model"),
        "policy_names": scope.get("policy_names") or [],
    }


def _report_review(path: Path, contract: dict[str, Any]) -> dict[str, Any]:
    payload, rows = _load_trade_rows(path)
    scope = _report_scope(payload)
    paper_contract = dict(contract.get("paper_contract") or {})
    paper_contract["symbols"] = scope.get("symbols") or []
    matched = [row for row in rows if _passes_contract(row, paper_contract)]
    summary = summarize_rows(matched)
    stress = _cost_stress(matched)
    by_symbol = _grouped_summaries(matched, "symbol")
    return {
        "path": str(path.relative_to(ROOT_DIR) if path.is_relative_to(ROOT_DIR) else path),
        "generated_at": payload.get("generated_at"),
        "scope": scope,
        "matched_summary": summary,
        "cost_stress": stress,
        "by_symbol": by_symbol,
        "expansion_gate": _expansion_gate(scope=scope, summary=summary, cost_stress=stress),
    }


def _expansion_gate(*, scope: dict[str, Any], summary: dict[str, Any], cost_stress: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    warnings: list[str] = []
    if _safe_int(scope.get("symbol_count")) < 8:
        reasons.append("scope_below_8_symbols")
    if _safe_int(scope.get("days")) < 365:
        reasons.append("scope_below_365_days")
    if _safe_int(summary.get("closed")) < 30:
        reasons.append("trade_count_below_30")
    if _safe_float(summary.get("total_r")) <= 0.0 or _safe_float(summary.get("ev_r")) <= 0.0:
        reasons.append("non_positive_base_result")
    if _safe_float(summary.get("positive_symbol_fraction")) < 0.60:
        reasons.append("positive_symbol_fraction_below_0_60")
    if _safe_float(summary.get("positive_year_fraction")) < 0.67:
        reasons.append("positive_year_fraction_below_0_67")
    extra_005 = dict(cost_stress.get("extra_0_05r_per_trade") or {})
    cost_x2 = dict(cost_stress.get("cost_x2_0") or {})
    if _safe_float(extra_005.get("total_r")) <= 0.0:
        reasons.append("extra_0_05r_stress_non_positive")
    if _safe_float(cost_x2.get("total_r")) <= 0.0:
        warnings.append("cost_x2_stress_non_positive")
    return {
        "state": "EXPANSION_CANDIDATE" if not reasons else "EXPANSION_NOT_READY",
        "reasons": reasons,
        "warnings": warnings,
    }


def _symbol_rollup(report_reviews: list[dict[str, Any]], contract: dict[str, Any]) -> list[dict[str, Any]]:
    current_symbols = {
        str(symbol).strip().upper()
        for symbol in list(dict(contract.get("paper_contract") or {}).get("symbols") or [])
        if str(symbol).strip()
    }
    rows: dict[str, dict[str, Any]] = {}
    for report in report_reviews:
        scope = dict(report.get("scope") or {})
        days = _safe_int(scope.get("days"))
        for symbol, summary in dict(report.get("by_symbol") or {}).items():
            item = rows.setdefault(
                str(symbol).upper(),
                {
                    "symbol": str(symbol).upper(),
                    "in_current_contract": str(symbol).upper() in current_symbols,
                    "reports": [],
                    "best_days": 0,
                    "best_total_r": 0.0,
                    "best_ev_r": 0.0,
                    "all_positive_report_count": 0,
                    "all_report_count": 0,
                },
            )
            total_r = _safe_float(dict(summary).get("total_r"))
            ev_r = _safe_float(dict(summary).get("ev_r"))
            item["reports"].append(
                {
                    "days": days,
                    "closed": _safe_int(dict(summary).get("closed")),
                    "total_r": round(total_r, 4),
                    "ev_r": round(ev_r, 4),
                    "source": report.get("path"),
                }
            )
            item["all_report_count"] += 1
            if total_r > 0.0 and ev_r > 0.0:
                item["all_positive_report_count"] += 1
            if days > _safe_int(item.get("best_days")) or (
                days == _safe_int(item.get("best_days")) and total_r > _safe_float(item.get("best_total_r"))
            ):
                item["best_days"] = days
                item["best_total_r"] = round(total_r, 4)
                item["best_ev_r"] = round(ev_r, 4)
    out = list(rows.values())
    for item in out:
        item["positive_report_fraction"] = round(
            _safe_int(item.get("all_positive_report_count")) / max(_safe_int(item.get("all_report_count")), 1),
            4,
        )
    return sorted(
        out,
        key=lambda item: (
            item["in_current_contract"],
            _safe_float(item.get("positive_report_fraction")),
            _safe_int(item.get("best_days")),
            _safe_float(item.get("best_total_r")),
        ),
        reverse=True,
    )


def _decision(report_reviews: list[dict[str, Any]], symbol_rows: list[dict[str, Any]]) -> tuple[str, list[str]]:
    expansion_ready = [row for row in report_reviews if dict(row.get("expansion_gate") or {}).get("state") == "EXPANSION_CANDIDATE"]
    candidate_symbols = [
        row
        for row in symbol_rows
        if not row.get("in_current_contract")
        and _safe_float(row.get("positive_report_fraction")) >= 0.50
        and _safe_float(row.get("best_total_r")) > 0.0
    ]
    if expansion_ready:
        return "EXPANSION_REVIEW_READY", ["at_least_one_broad_scope_passed_expansion_gate"]
    if len(candidate_symbols) >= 4:
        return "EXPANSION_SHADOW_WATCHLIST_ONLY", ["some_symbols_are_positive_but_no_broad_scope_passed"]
    return "EXPANSION_NOT_READY", ["no_broad_scope_passed_and_not_enough_positive_new_symbols"]


def build_payload(
    contract_path: Path,
    report_paths: list[Path],
    *,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC)
    contract = _load_json(contract_path)
    reviews: list[dict[str, Any]] = []
    load_errors: list[dict[str, str]] = []
    for path in report_paths:
        try:
            review = _report_review(path, contract)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            load_errors.append({"path": str(path), "error": str(exc)})
            continue
        if _safe_int(dict(review.get("matched_summary") or {}).get("closed")) > 0:
            reviews.append(review)
    reviews.sort(
        key=lambda item: (
            _safe_int(dict(item.get("scope") or {}).get("symbol_count")),
            _safe_int(dict(item.get("scope") or {}).get("days")),
        ),
        reverse=True,
    )
    symbols = _symbol_rollup(reviews, contract)
    state, reasons = _decision(reviews, symbols)
    return {
        "schema_version": "micro_intrabar_candidate_expansion_review_v1",
        "generated_at": generated_at.isoformat(),
        "authority": "expansion_review_only_no_order_submission",
        "contract_path": str(contract_path.relative_to(ROOT_DIR) if contract_path.is_relative_to(ROOT_DIR) else contract_path),
        "report_count": len(report_paths),
        "loaded_review_count": len(reviews),
        "load_errors": load_errors,
        "recommended_state": state,
        "reasons": reasons,
        "live_action": "KEEP_CLOSE_ONLY",
        "live_ready": False,
        "report_reviews": reviews,
        "symbol_rollup": symbols,
        "shadow_watchlist_symbols": [
            row["symbol"]
            for row in symbols
            if not row.get("in_current_contract")
            and _safe_float(row.get("positive_report_fraction")) >= 0.50
            and _safe_float(row.get("best_total_r")) > 0.0
        ],
    }


def _render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Micro Intrabar Candidate Expansion Review",
        "",
        f"- generated_at: {payload.get('generated_at')}",
        f"- authority: {payload.get('authority')}",
        f"- recommended_state: {payload.get('recommended_state')}",
        f"- reasons: {payload.get('reasons')}",
        f"- live_action: {payload.get('live_action')}",
        f"- shadow_watchlist_symbols: {','.join(list(payload.get('shadow_watchlist_symbols') or []))}",
        "",
        "## Broad Reports",
    ]
    for item in list(payload.get("report_reviews") or []):
        scope = dict(item.get("scope") or {})
        summary = dict(item.get("matched_summary") or {})
        gate = dict(item.get("expansion_gate") or {})
        lines.append(
            "- "
            f"symbols={scope.get('symbol_count')} days={scope.get('days')} "
            f"trades={summary.get('closed')} total_r={summary.get('total_r')} ev={summary.get('ev_r')} "
            f"p_symbol={summary.get('positive_symbol_fraction')} p_year={summary.get('positive_year_fraction')} "
            f"gate={gate.get('state')} reasons={gate.get('reasons')} source={item.get('path')}"
        )
    lines.append("")
    lines.append("This expansion review does not submit orders or enable live routing.")
    return "\n".join(lines) + "\n"


def main() -> int:
    args = _parse_args()
    generated_at = datetime.now(UTC)
    contract_path = _resolve_path(args.contract_path)
    paths = _expand_paths(args.report_path, args.report_glob)
    payload = build_payload(contract_path, paths, generated_at=generated_at)
    if args.write_report:
        report_dir = _resolve_path(args.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        stamp = _report_stamp(generated_at)
        json_path = report_dir / f"micro_intrabar_candidate_expansion_review_{stamp}.json"
        md_path = report_dir / f"micro_intrabar_candidate_expansion_review_{stamp}.md"
        latest_json = report_dir / "latest.json"
        latest_md = report_dir / "latest.md"
        payload["report_path"] = str(json_path.relative_to(ROOT_DIR) if json_path.is_relative_to(ROOT_DIR) else json_path)
        payload["latest_report_path"] = str(latest_json.relative_to(ROOT_DIR) if latest_json.is_relative_to(ROOT_DIR) else latest_json)
        atomic_write_text(json_path, json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        atomic_write_text(md_path, _render_markdown(payload))
        atomic_write_text(latest_json, json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        atomic_write_text(latest_md, _render_markdown(payload))
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
