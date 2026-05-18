#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.report_io import atomic_write_text
from scripts.run_micro_main_exit_policy_search import summarize_rows


DEFAULT_ACTIVE_EXIT_POLICY = "structure_buffered_swing6_stop0.12_tpbuf0.08_pm_stop0.00r_advvol_any"


@dataclass(frozen=True, slots=True)
class FilterSpec:
    direction: str
    hours: tuple[int, ...]
    min_volume_factor: float
    min_reclaim_body_atr: float
    min_risk_atr: float
    max_risk_atr: float | None
    max_retest_wait_minutes: int | None
    max_entry_distance_atr: float | None

    @property
    def name(self) -> str:
        hour_name = "all" if len(self.hours) == 24 else "_".join(f"{hour:02d}" for hour in self.hours)
        risk_high = "inf" if self.max_risk_atr is None else f"{self.max_risk_atr:g}"
        retest = "inf" if self.max_retest_wait_minutes is None else str(self.max_retest_wait_minutes)
        entry_distance = "inf" if self.max_entry_distance_atr is None else f"{self.max_entry_distance_atr:g}"
        return (
            f"{self.direction}_h{hour_name}"
            f"_vol{self.min_volume_factor:g}"
            f"_body{self.min_reclaim_body_atr:g}"
            f"_risk{self.min_risk_atr:g}-{risk_high}"
            f"_retest{retest}"
            f"_entrydist{entry_distance}"
        )

    def contract(self) -> dict[str, Any]:
        return {
            "direction": self.direction,
            "setup_hour_utc": list(self.hours),
            "min_volume_factor": self.min_volume_factor,
            "min_reclaim_body_atr": self.min_reclaim_body_atr,
            "min_risk_atr": self.min_risk_atr,
            "max_risk_atr": self.max_risk_atr,
            "max_retest_wait_minutes": self.max_retest_wait_minutes,
            "max_entry_distance_atr": self.max_entry_distance_atr,
        }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Search no-lookahead intrabar SIR filter grids from included trade reports."
    )
    parser.add_argument("--report-path", action="append", required=True)
    parser.add_argument("--policy", default=DEFAULT_ACTIVE_EXIT_POLICY)
    parser.add_argument("--min-trades", type=int, default=60)
    parser.add_argument("--max-results", type=int, default=50)
    parser.add_argument("--report-dir", default="reports/validation/micro_intrabar_filter_grid_search")
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


def _resolve_path(raw: str) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = ROOT_DIR / path
    return path


def _expand_report_paths(raw_paths: list[str]) -> list[Path]:
    paths: list[Path] = []
    seen: set[Path] = set()
    for item in raw_paths:
        for raw in str(item or "").split(","):
            if not raw.strip():
                continue
            path = _resolve_path(raw.strip())
            if path.exists() and path not in seen:
                paths.append(path)
                seen.add(path)
    return paths


def _load_rows(paths: list[Path], policy_names: set[str]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    scopes: list[dict[str, Any]] = []
    load_errors: list[dict[str, str]] = []
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            load_errors.append({"path": str(path), "error": str(exc)})
            continue
        scope = payload.get("scope") if isinstance(payload.get("scope"), dict) else {}
        scopes.append(
            {
                "path": str(path.relative_to(ROOT_DIR) if path.is_relative_to(ROOT_DIR) else path),
                "generated_at": payload.get("generated_at"),
                "days": scope.get("days"),
                "symbols": scope.get("symbols") or [],
                "entry_timing_model": scope.get("entry_timing_model"),
                "policy_names": scope.get("policy_names") or [],
            }
        )
        for item in list(payload.get("results") or []):
            if not isinstance(item, dict):
                continue
            for row in list(item.get("trades") or []):
                if not isinstance(row, dict):
                    continue
                if policy_names and str(row.get("policy") or "") not in policy_names:
                    continue
                rows.append(row)
    return {"scopes": scopes, "load_errors": load_errors}, rows


def _diagnostics(row: dict[str, Any]) -> dict[str, Any]:
    return dict(row.get("diagnostics") or {})


def _mask_from_predicate(rows: list[dict[str, Any]], predicate: Any) -> int:
    mask = 0
    for idx, row in enumerate(rows):
        if predicate(row):
            mask |= 1 << idx
    return mask


def _mask_from_numeric_threshold(
    values: list[float],
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> int:
    mask = 0
    for idx, value in enumerate(values):
        if minimum is not None and value < minimum:
            continue
        if maximum is not None and value > maximum:
            continue
        mask |= 1 << idx
    return mask


def _mask_from_allowed_ints(values: list[int], allowed_values: set[int]) -> int:
    mask = 0
    for idx, value in enumerate(values):
        if value in allowed_values:
            mask |= 1 << idx
    return mask


def _iter_mask_indices(mask: int) -> list[int]:
    indices: list[int] = []
    while mask:
        bit = mask & -mask
        indices.append(bit.bit_length() - 1)
        mask ^= bit
    return indices


def _hour_windows() -> list[tuple[int, ...]]:
    windows: list[tuple[int, ...]] = [tuple(range(24))]
    seen: set[tuple[int, ...]] = {tuple(range(24))}
    for length in (1, 2, 3, 4):
        for start in range(24):
            hours = tuple((start + offset) % 24 for offset in range(length))
            if hours not in seen:
                windows.append(hours)
                seen.add(hours)
    return windows


def _filter_specs() -> list[FilterSpec]:
    volume_body_profiles = [
        (0.0, 0.0),
        (0.0, 0.25),
        (1.0, 0.0),
        (1.0, 0.20),
        (1.0, 0.35),
        (1.2, 0.0),
        (1.2, 0.25),
        (1.5, 0.0),
        (1.5, 0.25),
        (2.0, 0.0),
    ]
    risk_profiles = [
        (0.0, None),
        (0.3, None),
        (0.5, None),
        (0.7, None),
        (0.0, 2.0),
        (0.3, 2.0),
        (0.5, 2.0),
    ]
    timing_profiles = [
        (None, None),
        (2, None),
        (3, None),
        (None, 0.50),
        (2, 0.50),
        (3, 0.75),
    ]
    specs: list[FilterSpec] = []
    for direction in ("long", "short", "both"):
        for hours in _hour_windows():
            for min_volume, min_body in volume_body_profiles:
                for min_risk, max_risk in risk_profiles:
                    for max_retest, max_entry_distance in timing_profiles:
                        specs.append(
                            FilterSpec(
                                direction=direction,
                                hours=hours,
                                min_volume_factor=min_volume,
                                min_reclaim_body_atr=min_body,
                                min_risk_atr=min_risk,
                                max_risk_atr=max_risk,
                                max_retest_wait_minutes=max_retest,
                                max_entry_distance_atr=max_entry_distance,
                            )
                        )
    return specs


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
    return {name: summarize_rows(_adjusted_rows(rows, **params)) for name, params in scenarios.items()}


def _decision(summary: dict[str, Any], stress: dict[str, dict[str, Any]], *, days: float) -> tuple[str, list[str]]:
    closed = _safe_int(summary.get("closed"))
    total_r = _safe_float(summary.get("total_r"))
    ev_r = _safe_float(summary.get("ev_r"))
    profit_to_dd = _safe_float(summary.get("profit_to_dd"))
    positive_symbol_fraction = _safe_float(summary.get("positive_symbol_fraction"))
    positive_year_fraction = _safe_float(summary.get("positive_year_fraction"))
    signals_per_day = closed / max(days, 1.0)
    estimated_days_to_30 = 30.0 / max(signals_per_day, 0.000001)
    extra_005_total_r = _safe_float(dict(stress.get("extra_0_05r_per_trade") or {}).get("total_r"))
    extra_005_positive_symbol_fraction = _safe_float(
        dict(stress.get("extra_0_05r_per_trade") or {}).get("positive_symbol_fraction")
    )
    extra_005_positive_year_fraction = _safe_float(
        dict(stress.get("extra_0_05r_per_trade") or {}).get("positive_year_fraction")
    )
    cost_x2_total_r = _safe_float(dict(stress.get("cost_x2_0") or {}).get("total_r"))
    blockers: list[str] = []
    warnings: list[str] = []

    if total_r <= 0.0:
        blockers.append("non_positive_total_r")
    if ev_r <= 0.0:
        blockers.append("non_positive_ev")
    if extra_005_total_r <= 0.0:
        blockers.append("extra_0_05r_stress_non_positive")
    if extra_005_positive_year_fraction < 0.67:
        blockers.append("extra_0_05r_weak_year_consistency")
    if extra_005_positive_symbol_fraction < 0.50:
        blockers.append("extra_0_05r_weak_symbol_consistency")
    if positive_year_fraction < 0.67:
        blockers.append("weak_year_consistency")
    if positive_symbol_fraction < 0.50:
        blockers.append("weak_symbol_consistency")
    if profit_to_dd < 0.50:
        blockers.append("weak_profit_to_drawdown")
    if cost_x2_total_r <= 0.0:
        warnings.append("cost_x2_stress_non_positive")
    if blockers:
        return "REJECT", blockers + warnings
    if estimated_days_to_30 <= 200.0 and ev_r >= 0.03:
        return "FASTER_PAPER_CANDIDATE", ["passes_frequency_and_cost_review"] + warnings
    return "PAPER_CANDIDATE", ["passes_cost_review_but_still_slow"] + warnings


def _score(summary: dict[str, Any], stress: dict[str, dict[str, Any]], *, days: float) -> float:
    closed = _safe_int(summary.get("closed"))
    signals_per_day = closed / max(days, 1.0)
    extra_005_total_r = _safe_float(dict(stress.get("extra_0_05r_per_trade") or {}).get("total_r"))
    cost_x2_total_r = _safe_float(dict(stress.get("cost_x2_0") or {}).get("total_r"))
    profit_to_dd = _safe_float(summary.get("profit_to_dd"))
    ev_r = _safe_float(summary.get("ev_r"))
    return round(extra_005_total_r + max(cost_x2_total_r, -10.0) * 0.25 + profit_to_dd * 1.5 + ev_r * 20.0 + min(signals_per_day, 0.5) * 12.0, 6)


def build_payload(
    paths: list[Path],
    *,
    policy_names: set[str],
    min_trades: int,
    max_results: int,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC)
    load_summary, rows = _load_rows(paths, policy_names)
    if not rows:
        raise ValueError("no matching rows found")

    diagnostics = [_diagnostics(row) for row in rows]
    r_values = [_safe_float(row.get("r_value")) for row in rows]
    directions = [str(row.get("direction") or "") for row in rows]
    setup_hours = [_safe_int(diag.get("setup_hour_utc"), -1) for diag in diagnostics]
    volume_values = [_safe_float(diag.get("volume_factor")) for diag in diagnostics]
    body_values = [_safe_float(diag.get("reclaim_body_atr")) for diag in diagnostics]
    risk_values = [_safe_float(diag.get("risk_atr")) for diag in diagnostics]
    retest_values = [_safe_float(diag.get("retest_wait_minutes"), 999.0) for diag in diagnostics]
    entry_distance_values = [_safe_float(diag.get("entry_distance_atr"), 999.0) for diag in diagnostics]
    all_mask = (1 << len(rows)) - 1
    specs = _filter_specs()

    direction_masks = {
        "long": _mask_from_predicate(rows, lambda row: str(row.get("direction") or "") == "long"),
        "short": _mask_from_predicate(rows, lambda row: str(row.get("direction") or "") == "short"),
        "both": all_mask,
    }
    hour_masks = {
        hours: _mask_from_allowed_ints(setup_hours, set(hours))
        for hours in _hour_windows()
    }
    volume_masks = {
        threshold: _mask_from_numeric_threshold(volume_values, minimum=threshold)
        for threshold in sorted({spec.min_volume_factor for spec in specs})
    }
    body_masks = {
        threshold: _mask_from_numeric_threshold(body_values, minimum=threshold)
        for threshold in sorted({spec.min_reclaim_body_atr for spec in specs})
    }
    risk_masks = {
        (spec.min_risk_atr, spec.max_risk_atr): _mask_from_numeric_threshold(
            risk_values,
            minimum=spec.min_risk_atr,
            maximum=spec.max_risk_atr,
        )
        for spec in specs
    }
    retest_masks = {
        spec.max_retest_wait_minutes: all_mask
        if spec.max_retest_wait_minutes is None
        else _mask_from_numeric_threshold(retest_values, maximum=float(spec.max_retest_wait_minutes))
        for spec in specs
    }
    entry_distance_masks = {
        spec.max_entry_distance_atr: all_mask
        if spec.max_entry_distance_atr is None
        else _mask_from_numeric_threshold(entry_distance_values, maximum=spec.max_entry_distance_atr)
        for spec in specs
    }

    days_values = [
        _safe_float(scope.get("days"))
        for scope in list(load_summary.get("scopes") or [])
        if _safe_float(scope.get("days")) > 0.0
    ]
    days = max(days_values) if days_values else 365.0
    candidates: list[dict[str, Any]] = []
    seen_masks: set[int] = set()
    for spec in specs:
        mask = (
            direction_masks[spec.direction]
            & hour_masks[spec.hours]
            & volume_masks[spec.min_volume_factor]
            & body_masks[spec.min_reclaim_body_atr]
            & risk_masks[(spec.min_risk_atr, spec.max_risk_atr)]
            & retest_masks[spec.max_retest_wait_minutes]
            & entry_distance_masks[spec.max_entry_distance_atr]
        )
        if mask in seen_masks:
            continue
        seen_masks.add(mask)
        closed = mask.bit_count()
        if closed < min_trades:
            continue
        indices = _iter_mask_indices(mask)
        total_r = sum(r_values[idx] for idx in indices)
        if total_r <= 0.0 or total_r - 0.05 * closed <= 0.0:
            continue
        kept = [rows[idx] for idx in indices]
        summary = summarize_rows(kept)
        stress = _cost_stress(kept)
        decision, reasons = _decision(summary, stress, days=days)
        if decision == "REJECT":
            continue
        signals_per_day = closed / max(days, 1.0)
        item = {
            "decision": decision,
            "reasons": reasons,
            "filter_name": spec.name,
            "filter_contract": spec.contract(),
            "summary": summary,
            "cost_stress": stress,
            "signals_per_day": round(signals_per_day, 6),
            "estimated_days_to_30_signals": round(30.0 / max(signals_per_day, 0.000001), 2),
            "score": _score(summary, stress, days=days),
        }
        candidates.append(item)

    decision_rank = {"FASTER_PAPER_CANDIDATE": 0, "PAPER_CANDIDATE": 1}
    candidates.sort(
        key=lambda item: (
            decision_rank.get(str(item.get("decision")), 9),
            -_safe_float(item.get("score")),
            -_safe_float(dict(item.get("summary") or {}).get("total_r")),
        )
    )
    candidates = candidates[:max_results]
    return {
        "schema_version": "micro_intrabar_filter_grid_search_v1",
        "generated_at": generated_at.isoformat(),
        "authority": "research_only_no_live_authority_change",
        "source": load_summary,
        "policy_names": sorted(policy_names),
        "row_count": len(rows),
        "min_trades": min_trades,
        "max_results": max_results,
        "candidate_count": len(candidates),
        "decision_counts": {
            decision: sum(1 for item in candidates if item.get("decision") == decision)
            for decision in ("FASTER_PAPER_CANDIDATE", "PAPER_CANDIDATE")
        },
        "candidates": candidates,
    }


def _report_stamp(value: datetime) -> str:
    return value.strftime("%Y%m%dT%H%M%S%fZ")


def _render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Micro Intrabar Filter Grid Search",
        "",
        f"- generated_at: {payload.get('generated_at')}",
        f"- authority: {payload.get('authority')}",
        f"- row_count: {payload.get('row_count')}",
        f"- candidate_count: {payload.get('candidate_count')}",
        f"- decision_counts: {payload.get('decision_counts')}",
        "",
        "## Top Candidates",
    ]
    for item in list(payload.get("candidates") or [])[:20]:
        summary = dict(item.get("summary") or {})
        extra = dict(dict(item.get("cost_stress") or {}).get("extra_0_05r_per_trade") or {})
        cost_x2 = dict(dict(item.get("cost_stress") or {}).get("cost_x2_0") or {})
        lines.append(
            "- "
            f"{item.get('decision')} {item.get('filter_name')} "
            f"trades={summary.get('closed')} total_r={summary.get('total_r')} ev={summary.get('ev_r')} "
            f"win={summary.get('win_rate')} max_dd={summary.get('max_dd_r')} "
            f"p_year={summary.get('positive_year_fraction')} p_symbol={summary.get('positive_symbol_fraction')} "
            f"signals_per_day={item.get('signals_per_day')} days_to_30={item.get('estimated_days_to_30_signals')} "
            f"extra_0_05r={extra.get('total_r')} cost_x2={cost_x2.get('total_r')} "
            f"reasons={item.get('reasons')}"
        )
    lines.append("")
    lines.append("Research only. This report does not enable live routing.")
    return "\n".join(lines) + "\n"


def main() -> int:
    args = _parse_args()
    paths = _expand_report_paths(args.report_path)
    policy_names = {item.strip() for item in str(args.policy or "").split(",") if item.strip()}
    generated_at = datetime.now(UTC)
    payload = build_payload(
        paths,
        policy_names=policy_names,
        min_trades=max(args.min_trades, 1),
        max_results=max(args.max_results, 1),
        generated_at=generated_at,
    )
    if args.write_report:
        report_dir = _resolve_path(args.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        stamp = _report_stamp(generated_at)
        json_path = report_dir / f"micro_intrabar_filter_grid_search_{stamp}.json"
        md_path = report_dir / f"micro_intrabar_filter_grid_search_{stamp}.md"
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
