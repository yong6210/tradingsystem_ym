#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.report_io import atomic_write_text
from scripts.run_micro_main_exit_policy_search import summarize_rows


DEFAULT_POLICY = "structure_buffered_swing6_stop0.12_tpbuf0.08_pm_stop0.00r_advvol_any"


@dataclass(frozen=True, slots=True)
class FilterSpec:
    direction: str
    hours: tuple[int, ...]
    min_volume_factor: float
    min_reclaim_body_atr: float
    min_risk_atr: float
    max_risk_atr: float | None
    max_entry_distance_atr: float | None

    @property
    def name(self) -> str:
        hour_name = "all" if len(self.hours) == 24 else "_".join(f"{hour:02d}" for hour in self.hours)
        max_risk = "inf" if self.max_risk_atr is None else f"{self.max_risk_atr:g}"
        max_dist = "inf" if self.max_entry_distance_atr is None else f"{self.max_entry_distance_atr:g}"
        return (
            f"{self.direction}_h{hour_name}"
            f"_vol{self.min_volume_factor:g}"
            f"_body{self.min_reclaim_body_atr:g}"
            f"_risk{self.min_risk_atr:g}-{max_risk}"
            f"_entrydist{max_dist}"
        )

    def contract(self) -> dict[str, Any]:
        return {
            "direction": self.direction,
            "setup_hour_utc": list(self.hours),
            "min_volume_factor": self.min_volume_factor,
            "min_reclaim_body_atr": self.min_reclaim_body_atr,
            "min_risk_atr": self.min_risk_atr,
            "max_risk_atr": self.max_risk_atr,
            "max_entry_distance_atr": self.max_entry_distance_atr,
        }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Walk-forward search for no-lookahead intrabar SIR filters plus symbol subsets."
    )
    parser.add_argument("--report-path", action="append", required=True)
    parser.add_argument("--policy", default=DEFAULT_POLICY, help="Comma-separated policy names to load.")
    parser.add_argument("--oos-days", type=int, default=365)
    parser.add_argument("--train-ratio", type=float, default=0.70)
    parser.add_argument("--min-train-trades", type=int, default=80)
    parser.add_argument("--min-oos-trades", type=int, default=20)
    parser.add_argument("--min-symbol-train-trades", type=int, default=8)
    parser.add_argument("--min-symbols", type=int, default=3)
    parser.add_argument("--top-symbol-counts", default="4,6,8,12,16,24,31")
    parser.add_argument("--search-preset", choices=("compact", "wide"), default="compact")
    parser.add_argument("--max-results", type=int, default=80)
    parser.add_argument("--report-dir", default="reports/validation/micro_intrabar_walkforward_symbol_filters")
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


def _parse_ts(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _resolve_path(raw: str) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = ROOT_DIR / path
    return path


def _expand_report_paths(raw_paths: list[str]) -> list[Path]:
    out: list[Path] = []
    seen: set[Path] = set()
    for item in raw_paths:
        for raw in str(item or "").split(","):
            if not raw.strip():
                continue
            path = _resolve_path(raw.strip())
            if path.exists() and path not in seen:
                out.append(path)
                seen.add(path)
    return out


def _diagnostics(row: dict[str, Any]) -> dict[str, Any]:
    return dict(row.get("diagnostics") or {})


def _load_rows(paths: list[Path], policy_names: set[str]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append({"path": str(path), "error": str(exc)})
            continue
        scope = payload.get("scope") if isinstance(payload.get("scope"), dict) else {}
        source_rows = 0
        for item in list(payload.get("results") or []):
            if not isinstance(item, dict):
                continue
            for row in list(item.get("trades") or []):
                if not isinstance(row, dict):
                    continue
                if policy_names and str(row.get("policy") or "") not in policy_names:
                    continue
                if _parse_ts(row.get("entry_ts")) is None:
                    continue
                rows.append(row)
                source_rows += 1
        sources.append(
            {
                "path": str(path.relative_to(ROOT_DIR) if path.is_relative_to(ROOT_DIR) else path),
                "schema_version": payload.get("schema_version"),
                "generated_at": payload.get("generated_at"),
                "days": scope.get("days"),
                "symbols": scope.get("symbols") or [],
                "entry_timing_model": scope.get("entry_timing_model"),
                "policy_names": scope.get("policy_names") or [],
                "loaded_rows": source_rows,
            }
        )
    rows.sort(key=lambda row: (_parse_ts(row.get("entry_ts")) or datetime.min.replace(tzinfo=UTC), str(row.get("symbol") or "")))
    return {"sources": sources, "load_errors": errors}, rows


def _mask_from_predicate(rows: list[dict[str, Any]], predicate: Any) -> int:
    mask = 0
    for idx, row in enumerate(rows):
        if predicate(row):
            mask |= 1 << idx
    return mask


def _mask_from_numeric(values: list[float], *, minimum: float | None = None, maximum: float | None = None) -> int:
    mask = 0
    for idx, value in enumerate(values):
        if minimum is not None and value < minimum:
            continue
        if maximum is not None and value > maximum:
            continue
        mask |= 1 << idx
    return mask


def _mask_from_allowed_ints(values: list[int], allowed: set[int]) -> int:
    mask = 0
    for idx, value in enumerate(values):
        if value in allowed:
            mask |= 1 << idx
    return mask


def _iter_mask_indices(mask: int) -> list[int]:
    out: list[int] = []
    while mask:
        bit = mask & -mask
        out.append(bit.bit_length() - 1)
        mask ^= bit
    return out


def _rows_from_mask(rows: list[dict[str, Any]], mask: int) -> list[dict[str, Any]]:
    return [rows[idx] for idx in _iter_mask_indices(mask)]


def _hour_windows(*, max_length: int) -> list[tuple[int, ...]]:
    windows: list[tuple[int, ...]] = [tuple(range(24))]
    seen: set[tuple[int, ...]] = {tuple(range(24))}
    for length in range(1, max(int(max_length), 1) + 1):
        for start in range(24):
            hours = tuple((start + offset) % 24 for offset in range(length))
            if hours not in seen:
                windows.append(hours)
                seen.add(hours)
    return windows


def _filter_specs(*, preset: str) -> list[FilterSpec]:
    if preset == "wide":
        volume_thresholds = (0.0, 0.8, 1.0, 1.1, 1.2, 1.35, 1.5, 1.75, 2.0)
        body_thresholds = (0.0, 0.15, 0.25, 0.35, 0.50)
        risk_ranges = (
            (0.0, None),
            (0.3, None),
            (0.5, None),
            (0.7, None),
            (1.0, None),
            (0.0, 2.0),
            (0.3, 2.0),
            (0.5, 2.0),
            (0.5, 1.5),
            (0.7, 2.5),
        )
        entry_distance_caps = (None, 0.30, 0.45, 0.60, 0.80)
        max_hour_length = 6
    else:
        volume_thresholds = (0.0, 1.0, 1.2, 1.5, 2.0)
        body_thresholds = (0.0, 0.25, 0.50)
        risk_ranges = (
            (0.0, None),
            (0.3, None),
            (0.5, None),
            (0.7, None),
            (0.5, 2.0),
            (0.5, 1.5),
        )
        entry_distance_caps = (None, 0.45, 0.80)
        max_hour_length = 4
    return [
        FilterSpec(
            direction=direction,
            hours=hours,
            min_volume_factor=volume,
            min_reclaim_body_atr=body,
            min_risk_atr=min_risk,
            max_risk_atr=max_risk,
            max_entry_distance_atr=max_entry_distance,
        )
        for direction in ("long", "short", "both")
        for hours in _hour_windows(max_length=max_hour_length)
        for volume in volume_thresholds
        for body in body_thresholds
        for min_risk, max_risk in risk_ranges
        for max_entry_distance in entry_distance_caps
    ]


def _adjusted_rows(
    rows: list[dict[str, Any]],
    *,
    cost_multiplier: float = 1.0,
    extra_cost_r_per_trade: float = 0.0,
) -> list[dict[str, Any]]:
    adjusted: list[dict[str, Any]] = []
    for row in rows:
        cost_r = _safe_float(row.get("cost_r"))
        extra_cost = max(cost_multiplier - 1.0, 0.0) * cost_r + max(extra_cost_r_per_trade, 0.0)
        item = dict(row)
        item["r_value"] = _safe_float(row.get("r_value")) - extra_cost
        item["cost_r"] = cost_r + extra_cost
        adjusted.append(item)
    return adjusted


def _cost_stress(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    scenarios = {
        "extra_0_03r_per_trade": {"extra_cost_r_per_trade": 0.03},
        "extra_0_05r_per_trade": {"extra_cost_r_per_trade": 0.05},
        "cost_x1_5": {"cost_multiplier": 1.5},
        "cost_x2_0": {"cost_multiplier": 2.0},
        "cost_x2_0_extra_0_03r_per_trade": {"cost_multiplier": 2.0, "extra_cost_r_per_trade": 0.03},
    }
    return {name: summarize_rows(_adjusted_rows(rows, **params)) for name, params in scenarios.items()}


def _split_masks(rows: list[dict[str, Any]], *, oos_days: int, train_ratio: float) -> tuple[int, int, dict[str, Any]]:
    if not rows:
        return 0, 0, {}
    timestamps = [_parse_ts(row.get("entry_ts")) for row in rows]
    clean = [ts for ts in timestamps if ts is not None]
    first_ts = min(clean)
    last_ts = max(clean)
    if int(oos_days) > 0:
        cutoff = last_ts - timedelta(days=int(oos_days))
        method = "last_n_days"
    else:
        ratio = max(0.1, min(float(train_ratio), 0.9))
        cutoff_index = max(0, min(len(clean) - 1, int((len(clean) - 1) * ratio)))
        cutoff = sorted(clean)[cutoff_index]
        method = "train_ratio"
    train_mask = 0
    oos_mask = 0
    for idx, ts in enumerate(timestamps):
        if ts is None:
            continue
        if ts < cutoff:
            train_mask |= 1 << idx
        else:
            oos_mask |= 1 << idx
    return train_mask, oos_mask, {
        "method": method,
        "first_entry_ts": first_ts.isoformat(),
        "last_entry_ts": last_ts.isoformat(),
        "cutoff_ts": cutoff.isoformat(),
        "train_rows": train_mask.bit_count(),
        "oos_rows": oos_mask.bit_count(),
    }


def _symbol_masks(rows: list[dict[str, Any]]) -> dict[str, int]:
    masks: dict[str, int] = {}
    for idx, row in enumerate(rows):
        symbol = str(row.get("symbol") or "").upper()
        if not symbol:
            continue
        masks[symbol] = masks.get(symbol, 0) | (1 << idx)
    return masks


def _rank_symbols(
    rows: list[dict[str, Any]],
    mask: int,
    *,
    min_symbol_train_trades: int,
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, float]] = {}
    for idx in _iter_mask_indices(mask):
        row = rows[idx]
        symbol = str(row.get("symbol") or "").upper()
        if not symbol:
            continue
        item = grouped.setdefault(symbol, {"closed": 0.0, "total_r": 0.0})
        item["closed"] += 1.0
        item["total_r"] += _safe_float(row.get("r_value"))
    ranked: list[dict[str, Any]] = []
    for symbol, item in grouped.items():
        closed = int(item["closed"])
        if closed < max(int(min_symbol_train_trades), 1):
            continue
        total = float(item["total_r"])
        adjusted = total - 0.05 * closed
        if adjusted <= 0.0:
            continue
        ev = total / max(float(closed), 1.0)
        ranked.append(
            {
                "symbol": symbol,
                "closed": closed,
                "total_r": round(total, 4),
                "extra_0_05r_total_r": round(adjusted, 4),
                "ev_r": round(ev, 4),
                "score": round(adjusted + max(ev, 0.0) * 10.0 + math.log10(closed + 10.0), 6),
            }
        )
    ranked.sort(key=lambda item: (_safe_float(item.get("score")), _safe_float(item.get("extra_0_05r_total_r"))), reverse=True)
    return ranked


def _decision(
    *,
    train_summary: dict[str, Any],
    oos_summary: dict[str, Any],
    all_summary: dict[str, Any],
    train_stress: dict[str, dict[str, Any]],
    oos_stress: dict[str, dict[str, Any]],
    min_oos_trades: int,
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    blockers: list[str] = []
    if _safe_float(train_summary.get("total_r")) <= 0.0 or _safe_float(train_summary.get("ev_r")) <= 0.0:
        blockers.append("train_not_positive")
    if _safe_float(dict(train_stress.get("extra_0_05r_per_trade") or {}).get("total_r")) <= 0.0:
        blockers.append("train_extra_cost_not_positive")
    if _safe_float(all_summary.get("total_r")) <= 0.0 or _safe_float(all_summary.get("ev_r")) <= 0.0:
        blockers.append("full_period_not_positive")
    if _safe_int(oos_summary.get("closed")) < int(min_oos_trades):
        reasons.append("oos_sample_thin")
    elif _safe_float(oos_summary.get("total_r")) <= 0.0 or _safe_float(oos_summary.get("ev_r")) <= 0.0:
        blockers.append("oos_not_positive")
    elif _safe_float(dict(oos_stress.get("extra_0_05r_per_trade") or {}).get("total_r")) <= 0.0:
        blockers.append("oos_extra_cost_not_positive")
    else:
        reasons.append("oos_positive_after_extra_cost")
    if _safe_float(all_summary.get("positive_year_fraction")) < 0.60:
        blockers.append("weak_full_year_consistency")
    if _safe_float(all_summary.get("positive_symbol_fraction")) < 0.50:
        blockers.append("weak_full_symbol_consistency")
    if blockers:
        return "REJECT", blockers + reasons
    if "oos_sample_thin" in reasons:
        return "PAPER_WATCH_THIN_OOS", reasons
    return "WALKFORWARD_CANDIDATE", reasons


def _score(
    *,
    oos_summary: dict[str, Any],
    all_summary: dict[str, Any],
    oos_stress: dict[str, dict[str, Any]],
    all_stress: dict[str, dict[str, Any]],
    selected_symbol_count: int,
    total_symbol_count: int,
    days: float,
) -> float:
    oos_extra = _safe_float(dict(oos_stress.get("extra_0_05r_per_trade") or {}).get("total_r"))
    all_extra = _safe_float(dict(all_stress.get("extra_0_05r_per_trade") or {}).get("total_r"))
    density = _safe_int(all_summary.get("closed")) / max(days, 1.0)
    breadth = selected_symbol_count / max(total_symbol_count, 1)
    return round(
        oos_extra * 2.0
        + all_extra
        + _safe_float(oos_summary.get("profit_to_dd")) * 2.0
        + _safe_float(all_summary.get("profit_to_dd"))
        + min(density, 1.0) * 12.0
        + min(breadth, 1.0) * 2.0,
        6,
    )


def _top_symbol_counts(raw: str, *, min_symbols: int, total_symbols: int) -> list[int]:
    values: list[int] = []
    seen: set[int] = set()
    for part in str(raw or "").split(","):
        count = _safe_int(part, 0)
        if count <= 0:
            continue
        count = min(max(count, min_symbols), total_symbols)
        if count not in seen:
            values.append(count)
            seen.add(count)
    return values or [min(max(min_symbols, 1), total_symbols)]


def build_payload(
    paths: list[Path],
    *,
    policy_names: set[str],
    oos_days: int,
    train_ratio: float,
    min_train_trades: int,
    min_oos_trades: int,
    min_symbol_train_trades: int,
    min_symbols: int,
    top_symbol_counts_raw: str,
    search_preset: str,
    max_results: int,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC)
    load_summary, rows = _load_rows(paths, policy_names)
    if not rows:
        raise ValueError("no matching trade rows found")

    diagnostics = [_diagnostics(row) for row in rows]
    setup_hours = [_safe_int(diag.get("setup_hour_utc"), -1) for diag in diagnostics]
    volume_values = [_safe_float(diag.get("volume_factor")) for diag in diagnostics]
    body_values = [_safe_float(diag.get("reclaim_body_atr")) for diag in diagnostics]
    risk_values = [_safe_float(diag.get("risk_atr")) for diag in diagnostics]
    entry_distance_values = [_safe_float(diag.get("entry_distance_atr"), 999.0) for diag in diagnostics]
    all_mask = (1 << len(rows)) - 1
    train_mask, oos_mask, split = _split_masks(rows, oos_days=oos_days, train_ratio=train_ratio)
    symbol_masks = _symbol_masks(rows)
    total_symbol_count = len(symbol_masks)
    top_symbol_counts = _top_symbol_counts(
        top_symbol_counts_raw,
        min_symbols=max(int(min_symbols), 1),
        total_symbols=max(total_symbol_count, 1),
    )

    direction_masks = {
        "long": _mask_from_predicate(rows, lambda row: str(row.get("direction") or "") == "long"),
        "short": _mask_from_predicate(rows, lambda row: str(row.get("direction") or "") == "short"),
        "both": all_mask,
    }
    specs = _filter_specs(preset=search_preset)
    hour_masks = {hours: _mask_from_allowed_ints(setup_hours, set(hours)) for hours in {spec.hours for spec in specs}}
    volume_masks = {threshold: _mask_from_numeric(volume_values, minimum=threshold) for threshold in sorted({spec.min_volume_factor for spec in specs})}
    body_masks = {threshold: _mask_from_numeric(body_values, minimum=threshold) for threshold in sorted({spec.min_reclaim_body_atr for spec in specs})}
    risk_masks = {
        (spec.min_risk_atr, spec.max_risk_atr): _mask_from_numeric(
            risk_values,
            minimum=spec.min_risk_atr,
            maximum=spec.max_risk_atr,
        )
        for spec in specs
    }
    entry_distance_masks = {
        spec.max_entry_distance_atr: all_mask
        if spec.max_entry_distance_atr is None
        else _mask_from_numeric(entry_distance_values, maximum=spec.max_entry_distance_atr)
        for spec in specs
    }

    timestamps = [_parse_ts(row.get("entry_ts")) for row in rows]
    clean_ts = [ts for ts in timestamps if ts is not None]
    days = max((max(clean_ts) - min(clean_ts)).total_seconds() / 86400.0, 1.0) if clean_ts else 1.0
    candidates: list[dict[str, Any]] = []
    seen_filter_masks: set[int] = set()
    seen_candidate_masks: set[int] = set()

    for spec in specs:
        filter_mask = (
            direction_masks[spec.direction]
            & hour_masks[spec.hours]
            & volume_masks[spec.min_volume_factor]
            & body_masks[spec.min_reclaim_body_atr]
            & risk_masks[(spec.min_risk_atr, spec.max_risk_atr)]
            & entry_distance_masks[spec.max_entry_distance_atr]
        )
        if filter_mask in seen_filter_masks:
            continue
        seen_filter_masks.add(filter_mask)
        train_filter_mask = filter_mask & train_mask
        if train_filter_mask.bit_count() < int(min_train_trades):
            continue
        ranked_symbols = _rank_symbols(
            rows,
            train_filter_mask,
            min_symbol_train_trades=int(min_symbol_train_trades),
        )
        if len(ranked_symbols) < max(int(min_symbols), 1):
            continue
        for symbol_count in top_symbol_counts:
            if len(ranked_symbols) < symbol_count:
                continue
            selected_symbols = [str(item["symbol"]) for item in ranked_symbols[:symbol_count]]
            selected_symbol_mask = 0
            for symbol in selected_symbols:
                selected_symbol_mask |= symbol_masks[symbol]
            candidate_mask = filter_mask & selected_symbol_mask
            if candidate_mask in seen_candidate_masks:
                continue
            seen_candidate_masks.add(candidate_mask)
            candidate_train_mask = candidate_mask & train_mask
            candidate_oos_mask = candidate_mask & oos_mask
            if candidate_train_mask.bit_count() < int(min_train_trades):
                continue
            all_rows = _rows_from_mask(rows, candidate_mask)
            train_rows = _rows_from_mask(rows, candidate_train_mask)
            oos_rows = _rows_from_mask(rows, candidate_oos_mask)
            train_summary = summarize_rows(train_rows)
            oos_summary = summarize_rows(oos_rows)
            all_summary = summarize_rows(all_rows)
            train_stress = _cost_stress(train_rows)
            oos_stress = _cost_stress(oos_rows)
            all_stress = _cost_stress(all_rows)
            decision, reasons = _decision(
                train_summary=train_summary,
                oos_summary=oos_summary,
                all_summary=all_summary,
                train_stress=train_stress,
                oos_stress=oos_stress,
                min_oos_trades=int(min_oos_trades),
            )
            if decision == "REJECT":
                continue
            candidates.append(
                {
                    "decision": decision,
                    "reasons": reasons,
                    "score": _score(
                        oos_summary=oos_summary,
                        all_summary=all_summary,
                        oos_stress=oos_stress,
                        all_stress=all_stress,
                        selected_symbol_count=len(selected_symbols),
                        total_symbol_count=total_symbol_count,
                        days=days,
                    ),
                    "filter_name": spec.name,
                    "filter_contract": spec.contract(),
                    "selected_symbols": selected_symbols,
                    "selected_symbol_count": len(selected_symbols),
                    "train_summary": train_summary,
                    "oos_summary": oos_summary,
                    "all_summary": all_summary,
                    "train_cost_stress": train_stress,
                    "oos_cost_stress": oos_stress,
                    "all_cost_stress": all_stress,
                    "ranked_symbols": ranked_symbols[: min(len(ranked_symbols), 20)],
                    "signals_per_day": round(_safe_int(all_summary.get("closed")) / max(days, 1.0), 6),
                }
            )

    decision_rank = {"WALKFORWARD_CANDIDATE": 0, "PAPER_WATCH_THIN_OOS": 1}
    candidates.sort(
        key=lambda item: (
            decision_rank.get(str(item.get("decision")), 9),
            -_safe_float(item.get("score")),
            -_safe_float(dict(item.get("oos_summary") or {}).get("total_r")),
            -_safe_float(dict(item.get("all_summary") or {}).get("total_r")),
        )
    )
    candidates = candidates[: max(int(max_results), 1)]
    return {
        "schema_version": "micro_intrabar_walkforward_symbol_filters_v1",
        "generated_at": generated_at.isoformat(),
        "authority": "research_only_no_live_authority_change",
        "policy_names": sorted(policy_names),
        "source": load_summary,
        "row_count": len(rows),
        "symbol_count": total_symbol_count,
        "split": split,
        "search_space": {
            "filter_specs": len(specs),
            "search_preset": search_preset,
            "min_train_trades": int(min_train_trades),
            "min_oos_trades": int(min_oos_trades),
            "min_symbol_train_trades": int(min_symbol_train_trades),
            "min_symbols": int(min_symbols),
            "top_symbol_counts": top_symbol_counts,
        },
        "candidate_count": len(candidates),
        "decision_counts": {
            decision: sum(1 for item in candidates if item.get("decision") == decision)
            for decision in ("WALKFORWARD_CANDIDATE", "PAPER_WATCH_THIN_OOS")
        },
        "candidates": candidates,
    }


def _report_stamp(value: datetime) -> str:
    return value.strftime("%Y%m%dT%H%M%S%fZ")


def _render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Micro Intrabar Walk-Forward Symbol Filter Search",
        "",
        f"- generated_at: {payload.get('generated_at')}",
        f"- authority: {payload.get('authority')}",
        f"- row_count: {payload.get('row_count')}",
        f"- symbol_count: {payload.get('symbol_count')}",
        f"- split: {payload.get('split')}",
        f"- candidate_count: {payload.get('candidate_count')}",
        f"- decision_counts: {payload.get('decision_counts')}",
        "",
        "## Top Candidates",
    ]
    for item in list(payload.get("candidates") or [])[:20]:
        all_summary = dict(item.get("all_summary") or {})
        oos_summary = dict(item.get("oos_summary") or {})
        all_extra = dict(dict(item.get("all_cost_stress") or {}).get("extra_0_05r_per_trade") or {})
        oos_extra = dict(dict(item.get("oos_cost_stress") or {}).get("extra_0_05r_per_trade") or {})
        lines.append(
            "- "
            f"{item.get('decision')} score={item.get('score')} "
            f"filter={item.get('filter_name')} symbols={','.join(list(item.get('selected_symbols') or []))} "
            f"all_trades={all_summary.get('closed')} all_total_r={all_summary.get('total_r')} all_ev={all_summary.get('ev_r')} "
            f"oos_trades={oos_summary.get('closed')} oos_total_r={oos_summary.get('total_r')} oos_ev={oos_summary.get('ev_r')} "
            f"all_extra_0_05r={all_extra.get('total_r')} oos_extra_0_05r={oos_extra.get('total_r')} "
            f"reasons={item.get('reasons')}"
        )
    lines.append("")
    lines.append("Research only. This report does not enable live routing.")
    return "\n".join(lines) + "\n"


def main() -> int:
    args = _parse_args()
    paths = _expand_report_paths(args.report_path)
    policy_names = {part.strip() for part in str(args.policy or "").split(",") if part.strip()}
    generated_at = datetime.now(UTC)
    payload = build_payload(
        paths,
        policy_names=policy_names,
        oos_days=int(args.oos_days),
        train_ratio=float(args.train_ratio),
        min_train_trades=max(int(args.min_train_trades), 1),
        min_oos_trades=max(int(args.min_oos_trades), 1),
        min_symbol_train_trades=max(int(args.min_symbol_train_trades), 1),
        min_symbols=max(int(args.min_symbols), 1),
        top_symbol_counts_raw=str(args.top_symbol_counts),
        search_preset=str(args.search_preset),
        max_results=max(int(args.max_results), 1),
        generated_at=generated_at,
    )
    if args.write_report:
        report_dir = _resolve_path(args.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        stamp = _report_stamp(generated_at)
        json_path = report_dir / f"micro_intrabar_walkforward_symbol_filters_{stamp}.json"
        md_path = report_dir / f"micro_intrabar_walkforward_symbol_filters_{stamp}.md"
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
