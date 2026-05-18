#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.report_io import atomic_write_text
from scripts.run_micro_main_exit_policy_search import summarize_rows


RowFilter = Callable[[dict[str, Any]], bool]

CORE_12_USDT = {
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "ADAUSDT",
    "AVAXUSDT",
    "LINKUSDT",
    "DOGEUSDT",
    "BCHUSDT",
    "LTCUSDT",
    "NEARUSDT",
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize compare-only subsets from an intrabar trade report.")
    parser.add_argument("--report-path", required=True)
    parser.add_argument("--filters", default="")
    parser.add_argument("--report-dir", default="reports/validation/micro_main_intrabar_subset_reports")
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


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


def _diagnostics(row: dict[str, Any]) -> dict[str, Any]:
    return dict(row.get("diagnostics") or {})


def _built_in_filters() -> dict[str, RowFilter]:
    return {
        "volume12_hour13_14_long": lambda row: (
            _safe_float(_diagnostics(row).get("volume_factor")) >= 1.20
            and _safe_int(_diagnostics(row).get("setup_hour_utc")) in (13, 14)
            and str(row.get("direction") or "") == "long"
        ),
        "volume12_body025_hour13_14_long": lambda row: (
            _safe_float(_diagnostics(row).get("volume_factor")) >= 1.20
            and _safe_float(_diagnostics(row).get("reclaim_body_atr")) >= 0.25
            and _safe_int(_diagnostics(row).get("setup_hour_utc")) in (13, 14)
            and str(row.get("direction") or "") == "long"
        ),
        "volume12_risk05_hour13_14_long": lambda row: (
            _safe_float(_diagnostics(row).get("volume_factor")) >= 1.20
            and _safe_float(_diagnostics(row).get("risk_atr")) >= 0.50
            and _safe_int(_diagnostics(row).get("setup_hour_utc")) in (13, 14)
            and str(row.get("direction") or "") == "long"
        ),
        "volume12_risk05_hour13_15_long": lambda row: (
            _safe_float(_diagnostics(row).get("volume_factor")) >= 1.20
            and _safe_float(_diagnostics(row).get("risk_atr")) >= 0.50
            and _safe_int(_diagnostics(row).get("setup_hour_utc")) in (13, 14, 15)
            and str(row.get("direction") or "") == "long"
        ),
        "body025_hour13_14_long": lambda row: (
            _safe_float(_diagnostics(row).get("reclaim_body_atr")) >= 0.25
            and _safe_int(_diagnostics(row).get("setup_hour_utc")) in (13, 14)
            and str(row.get("direction") or "") == "long"
        ),
        "core12_volume12_hour13_14_long": lambda row: (
            str(row.get("symbol") or "").upper() in CORE_12_USDT
            and _safe_float(_diagnostics(row).get("volume_factor")) >= 1.20
            and _safe_int(_diagnostics(row).get("setup_hour_utc")) in (13, 14)
            and str(row.get("direction") or "") == "long"
        ),
    }


def _selected_filters(raw: str) -> dict[str, RowFilter]:
    filters = _built_in_filters()
    names = [name.strip() for name in str(raw or "").split(",") if name.strip()]
    if not names:
        return filters
    missing = [name for name in names if name not in filters]
    if missing:
        raise SystemExit(f"unknown filters: {','.join(missing)}")
    return {name: filters[name] for name in names}


def _load_report(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for item in list(payload.get("results") or []):
        if not isinstance(item, dict):
            continue
        for row in list(item.get("trades") or []):
            if isinstance(row, dict):
                rows.append(row)
    if not rows:
        raise ValueError(f"report has no included trade rows: {path}")
    return payload, rows


def _grouped_total(rows: list[dict[str, Any]], key: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in rows:
        if key == "year":
            group = str(row.get("entry_year") or str(row.get("entry_ts") or "")[:4])
        else:
            group = str(row.get(key) or "unknown")
        out[group] = out.get(group, 0.0) + _safe_float(row.get("r_value"))
    return {item_key: round(value, 4) for item_key, value in sorted(out.items())}


def _grouped_rows(rows: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        group = str(row.get(key) or "unknown")
        grouped.setdefault(group, []).append(row)
    return grouped


def _adjusted_rows(
    rows: list[dict[str, Any]],
    *,
    cost_multiplier: float = 1.0,
    extra_cost_r_per_trade: float = 0.0,
) -> list[dict[str, Any]]:
    adjusted: list[dict[str, Any]] = []
    for row in rows:
        cost_r = _safe_float(row.get("cost_r"))
        extra_cost_r = max(cost_multiplier - 1.0, 0.0) * cost_r + max(extra_cost_r_per_trade, 0.0)
        item = dict(row)
        item["r_value"] = _safe_float(row.get("r_value")) - extra_cost_r
        item["cost_r"] = cost_r + extra_cost_r
        adjusted.append(item)
    return adjusted


def _cost_stress(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    scenarios = {
        "cost_x1_5": {"cost_multiplier": 1.5, "extra_cost_r_per_trade": 0.0},
        "cost_x2_0": {"cost_multiplier": 2.0, "extra_cost_r_per_trade": 0.0},
        "extra_0_03r_per_trade": {"cost_multiplier": 1.0, "extra_cost_r_per_trade": 0.03},
        "extra_0_05r_per_trade": {"cost_multiplier": 1.0, "extra_cost_r_per_trade": 0.05},
        "cost_x2_0_extra_0_03r_per_trade": {"cost_multiplier": 2.0, "extra_cost_r_per_trade": 0.03},
    }
    return {
        name: summarize_rows(_adjusted_rows(rows, **params))
        for name, params in scenarios.items()
    }


def _policy_breakdowns(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    policies: list[dict[str, Any]] = []
    for policy_name, policy_rows in _grouped_rows(rows, "policy").items():
        summary = summarize_rows(policy_rows)
        policies.append(
            {
                "policy": policy_name,
                "summary": summary,
                "by_year_total_r": _grouped_total(policy_rows, "year"),
                "by_symbol_total_r": _grouped_total(policy_rows, "symbol"),
                "cost_stress": _cost_stress(policy_rows),
            }
        )
    return sorted(
        policies,
        key=lambda item: (
            _safe_float(dict(dict(item.get("cost_stress") or {}).get("extra_0_05r_per_trade") or {}).get("total_r")),
            _safe_float(dict(item.get("summary") or {}).get("total_r")),
            _safe_float(dict(item.get("summary") or {}).get("ev_r")),
        ),
        reverse=True,
    )


def _report_stamp(value: datetime) -> str:
    return value.strftime("%Y%m%dT%H%M%S%fZ")


def build_payload(path: Path, filters: dict[str, RowFilter], *, generated_at: datetime | None = None) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC)
    source_payload, rows = _load_report(path)
    baseline = summarize_rows(rows)
    results: list[dict[str, Any]] = []
    for name, predicate in filters.items():
        kept = [row for row in rows if predicate(row)]
        summary = summarize_rows(kept)
        results.append(
            {
                "name": name,
                "summary": summary,
                "source_policy_count": len(_grouped_rows(kept, "policy")),
                "by_policy": _policy_breakdowns(kept),
                "removed": len(rows) - len(kept),
                "removed_pct": round((len(rows) - len(kept)) / max(len(rows), 1), 4),
                "delta_total_r": round(_safe_float(summary.get("total_r")) - _safe_float(baseline.get("total_r")), 4),
                "delta_ev_r": round(_safe_float(summary.get("ev_r")) - _safe_float(baseline.get("ev_r")), 4),
                "by_year_total_r": _grouped_total(kept, "year"),
                "by_symbol_total_r": _grouped_total(kept, "symbol"),
                "cost_stress": _cost_stress(kept),
            }
        )
    results.sort(key=lambda item: (_safe_float(dict(item.get("summary") or {}).get("total_r")), _safe_float(dict(item.get("summary") or {}).get("ev_r"))), reverse=True)
    return {
        "schema_version": "micro_main_intrabar_subset_report_v1",
        "generated_at": generated_at.isoformat(),
        "authority": "compare_only_no_live_authority_change",
        "source_report": str(path.relative_to(ROOT_DIR) if path.is_relative_to(ROOT_DIR) else path),
        "source_generated_at": source_payload.get("generated_at"),
        "source_scope": source_payload.get("scope") or {},
        "baseline": baseline,
        "results": results,
    }


def _render_markdown(payload: dict[str, Any]) -> str:
    baseline = dict(payload.get("baseline") or {})
    lines = [
        "# Micro Main Intrabar Subset Report",
        "",
        f"- generated_at: {payload.get('generated_at')}",
        f"- authority: {payload.get('authority')}",
        f"- source_report: {payload.get('source_report')}",
        f"- baseline: trades={baseline.get('closed')} total_r={baseline.get('total_r')} ev={baseline.get('ev_r')} win={baseline.get('win_rate')} max_dd={baseline.get('max_dd_r')}",
        "",
        "## Subsets",
    ]
    for item in list(payload.get("results") or []):
        summary = dict(item.get("summary") or {})
        lines.append(
            "- "
            f"{item.get('name')}: trades={summary.get('closed')} total_r={summary.get('total_r')} "
            f"ev={summary.get('ev_r')} win={summary.get('win_rate')} max_dd={summary.get('max_dd_r')} "
            f"removed={item.get('removed_pct')} years={item.get('by_year_total_r')}"
        )
        stress = dict(item.get("cost_stress") or {})
        if stress:
            cost_x2 = dict(stress.get("cost_x2_0") or {})
            extra_005 = dict(stress.get("extra_0_05r_per_trade") or {})
            lines.append(
                f"  - stress: cost_x2_total_r={cost_x2.get('total_r')} "
                f"extra_0_05r_total_r={extra_005.get('total_r')}"
            )
        for policy_item in list(item.get("by_policy") or [])[:5]:
            policy_summary = dict(policy_item.get("summary") or {})
            policy_stress = dict(policy_item.get("cost_stress") or {})
            policy_extra = dict(policy_stress.get("extra_0_05r_per_trade") or {})
            lines.append(
                "  - policy "
                f"{policy_item.get('policy')}: trades={policy_summary.get('closed')} "
                f"total_r={policy_summary.get('total_r')} ev={policy_summary.get('ev_r')} "
                f"extra_0_05r_total_r={policy_extra.get('total_r')}"
            )
    lines.append("")
    lines.append("Compare-only report. It does not change live routing.")
    return "\n".join(lines) + "\n"


def main() -> int:
    args = _parse_args()
    path = Path(args.report_path).expanduser()
    if not path.is_absolute():
        path = ROOT_DIR / path
    generated_at = datetime.now(UTC)
    payload = build_payload(path, _selected_filters(args.filters), generated_at=generated_at)
    if args.write_report:
        report_dir = Path(args.report_dir).expanduser()
        if not report_dir.is_absolute():
            report_dir = ROOT_DIR / report_dir
        report_dir.mkdir(parents=True, exist_ok=True)
        stamp = _report_stamp(generated_at)
        json_path = report_dir / f"micro_main_intrabar_subset_report_{stamp}.json"
        md_path = report_dir / f"micro_main_intrabar_subset_report_{stamp}.md"
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
