#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import MethodType
from typing import Any

import httpx

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.services.micro_main_strategy_research import (
    SessionImpulseRetestResearch,
    session_impulse_retest_profile_for_symbol,
)
from app.services.report_io import atomic_write_text
from scripts.run_micro_main_usdt_proxy_backtest import (
    _fetch_1m_klines,
    _resample_to_5m,
    _trade_to_row,
    canonical_symbol_for_proxy,
)


@dataclass(frozen=True, slots=True)
class Variant:
    name: str
    body_delta: float = 0.0
    volume_mult: float = 1.0
    trend_delta: float = 0.0
    overshoot_delta: float = 0.0
    drive_delta: float = 0.0
    max_risk_delta: float = 0.0
    retest_delta: float = 0.0
    close_delta: float = 0.0
    exclude_symbols: tuple[str, ...] = ()
    notes: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "body_delta": round(self.body_delta, 6),
            "volume_mult": round(self.volume_mult, 6),
            "trend_delta": round(self.trend_delta, 6),
            "overshoot_delta": round(self.overshoot_delta, 6),
            "drive_delta": round(self.drive_delta, 6),
            "max_risk_delta": round(self.max_risk_delta, 6),
            "retest_delta": round(self.retest_delta, 6),
            "close_delta": round(self.close_delta, 6),
            "exclude_symbols": list(self.exclude_symbols),
            "notes": self.notes,
        }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run raw-candle SessionImpulseRetest profile model search. This regenerates signals."
    )
    parser.add_argument(
        "--symbols",
        default="BTCUSDT,ETHUSDT,SOLUSDT,LINKUSDT,BNBUSDT,XRPUSDT,ADAUSDT,AVAXUSDT,BCHUSDT,LTCUSDT,NEARUSDT",
    )
    parser.add_argument("--days", type=int, default=1095)
    parser.add_argument("--max-variants", type=int, default=0)
    parser.add_argument("--search-name", default="continuation")
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _parse_dt(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(
        rows,
        key=lambda row: (
            _parse_dt(row.get("exit_ts")),
            _parse_dt(row.get("entry_ts")),
            str(row.get("symbol") or ""),
        ),
    )
    values = [_safe_float(row.get("r_value")) for row in ordered]
    total = sum(values)
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    wins = sum(1 for value in values if value > 0.0)
    closed = len(values)
    return {
        "trades": closed,
        "total_r": round(total, 4),
        "ev_r": round(total / closed, 4) if closed else 0.0,
        "win_rate": round(wins / closed, 4) if closed else 0.0,
        "max_dd_r": round(max_drawdown, 4),
    }


def _group_stats(rows: list[dict[str, Any]], key_fn) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(key_fn(row)), []).append(row)
    return {key: _stats(bucket) for key, bucket in sorted(grouped.items())}


def _quarter(value: Any) -> str:
    parsed = _parse_dt(value)
    return f"{parsed.year}Q{((parsed.month - 1) // 3) + 1}"


def _delta_map(current: dict[str, dict[str, Any]], baseline: dict[str, dict[str, Any]]) -> dict[str, float]:
    keys = sorted(set(current) | set(baseline))
    return {
        key: round(
            _safe_float(dict(current.get(key) or {}).get("total_r"))
            - _safe_float(dict(baseline.get(key) or {}).get("total_r")),
            4,
        )
        for key in keys
    }


def _recent(rows: list[dict[str, Any]], *, end_ts: datetime, days: int) -> list[dict[str, Any]]:
    threshold = end_ts - timedelta(days=days)
    return [row for row in rows if _parse_dt(row.get("entry_ts")) >= threshold]


def _apply_variant_profile(profile: dict[str, float], *, symbol: str, variant: Variant) -> dict[str, float]:
    if str(symbol).upper() in {item.upper() for item in variant.exclude_symbols}:
        return dict(profile)
    adjusted = dict(profile)
    adjusted["min_reclaim_body_atr"] = max(0.0, float(adjusted["min_reclaim_body_atr"]) + variant.body_delta)
    adjusted["min_volume_factor"] = max(0.0, float(adjusted["min_volume_factor"]) * variant.volume_mult)
    adjusted["min_trend_strength"] = max(0.0, float(adjusted["min_trend_strength"]) + variant.trend_delta)
    adjusted["reclaim_overshoot_atr"] = max(0.0, float(adjusted["reclaim_overshoot_atr"]) + variant.overshoot_delta)
    adjusted["min_drive_extension_atr"] = max(0.0, float(adjusted["min_drive_extension_atr"]) + variant.drive_delta)
    adjusted["max_risk_atr"] = max(
        float(adjusted.get("min_risk_atr", 0.0)),
        float(adjusted["max_risk_atr"]) + variant.max_risk_delta,
    )
    adjusted["max_retest_wait_minutes"] = max(0.0, float(adjusted["max_retest_wait_minutes"]) + variant.retest_delta)
    if variant.close_delta:
        adjusted["min_reclaim_close_long"] = min(0.95, max(0.05, float(adjusted["min_reclaim_close_long"]) + variant.close_delta))
        adjusted["max_reclaim_close_short"] = min(0.95, max(0.05, float(adjusted["max_reclaim_close_short"]) - variant.close_delta))
    return adjusted


def _format_signed(value: float, digits: int = 3) -> str:
    return f"{value:+.{digits}f}"


def _variant_name(*, body: float, volume: float, trend: float, overshoot: float) -> str:
    return (
        f"cont_body_{_format_signed(body, 4)}_volume_{volume:.3f}"
        f"_trend_{_format_signed(trend, 2)}_over_{_format_signed(overshoot, 3)}_except_XRP"
    )


def _build_variants() -> list[Variant]:
    variants: list[Variant] = [
        Variant(name="current_live_reference", notes="original current profile"),
        Variant(
            name="fine_best_reference",
            body_delta=0.085,
            volume_mult=0.82,
            trend_delta=-0.09,
            overshoot_delta=0.03,
            exclude_symbols=("XRPUSDC",),
            notes="best from latest_fine_raw_variant_search",
        ),
    ]
    seen = {variant.name for variant in variants}

    def add(variant: Variant) -> None:
        if variant.name in seen:
            return
        seen.add(variant.name)
        variants.append(variant)

    for body in (0.0825, 0.085, 0.0875, 0.09):
        for volume in (0.81, 0.82, 0.83):
            for trend in (-0.08, -0.09, -0.10, -0.11, -0.12):
                for overshoot in (0.035, 0.04, 0.045, 0.05):
                    add(
                        Variant(
                            name=_variant_name(body=body, volume=volume, trend=trend, overshoot=overshoot),
                            body_delta=body,
                            volume_mult=volume,
                            trend_delta=trend,
                            overshoot_delta=overshoot,
                            exclude_symbols=("XRPUSDC",),
                        )
                    )

    base = {
        "body_delta": 0.085,
        "volume_mult": 0.82,
        "trend_delta": -0.09,
        "overshoot_delta": 0.03,
        "exclude_symbols": ("XRPUSDC",),
    }
    for drive in (-0.04, -0.02, 0.02, 0.04):
        add(Variant(name=f"fine_best_drive_{_format_signed(drive, 2)}_except_XRP", drive_delta=drive, **base))
    for risk in (-0.20, -0.10, 0.10, 0.20, 0.30):
        add(Variant(name=f"fine_best_maxrisk_{_format_signed(risk, 2)}_except_XRP", max_risk_delta=risk, **base))
    for retest in (-1.0, 1.0, 2.0):
        add(Variant(name=f"fine_best_retest_wait_{_format_signed(retest, 0)}_except_XRP", retest_delta=retest, **base))
    for close in (-0.03, -0.015, 0.015, 0.03):
        add(Variant(name=f"fine_best_close_{_format_signed(close, 3)}_except_XRP", close_delta=close, **base))
    for exclusions in ((), ("ETHUSDC",), ("XRPUSDC", "ETHUSDC")):
        suffix = "all_symbols" if not exclusions else "except_" + "_".join(item.replace("USDC", "") for item in exclusions)
        add(Variant(name=f"fine_best_{suffix}", exclude_symbols=exclusions, **{k: v for k, v in base.items() if k != "exclude_symbols"}))

    return variants


def _variant_rows_for_symbol(
    *,
    engine: SessionImpulseRetestResearch,
    proxy_symbol: str,
    canonical_symbol: str,
    variant: Variant,
) -> list[dict[str, Any]]:
    base_profile = engine._signal_filter_profile()
    profile = _apply_variant_profile(base_profile, symbol=canonical_symbol, variant=variant)

    def patched_profile(self: SessionImpulseRetestResearch) -> dict[str, float]:
        return dict(profile)

    original = engine._signal_filter_profile
    engine._signal_filter_profile = MethodType(patched_profile, engine)
    try:
        trades = engine.backtest()
    finally:
        engine._signal_filter_profile = original
    return [
        _trade_to_row(
            trade=trade,
            proxy_symbol=proxy_symbol,
            canonical_symbol=canonical_symbol,
            profile_name=session_impulse_retest_profile_for_symbol(canonical_symbol),
        )
        for trade in trades
    ]


def _score_model(item: dict[str, Any]) -> float:
    stats = dict(item.get("stats") or {})
    return (
        _safe_float(item.get("delta_total_r"))
        + max(0.0, -_safe_float(item.get("delta_dd_r"))) * 8.0
        + _safe_float(item.get("delta_ev_r")) * 800.0
        + _safe_float(dict(item.get("recent_delta_total_r") or {}).get("365")) * 0.45
        + _safe_int(item.get("delta_trades")) * 0.03
        + _safe_float(item.get("worst_quarter_delta_r")) * 2.0
        - max(0.0, _safe_float(stats.get("max_dd_r")) - 12.0) * 20.0
        - _safe_int(item.get("negative_symbol_count")) * 300.0
        - _safe_int(item.get("negative_year_count")) * 400.0
        - _safe_int(item.get("negative_quarter_count")) * 120.0
    )


def _evaluate_models(
    rows_by_variant: dict[str, list[dict[str, Any]]],
    *,
    variants: list[Variant],
    end_ts: datetime,
) -> dict[str, Any]:
    baseline_rows = rows_by_variant["current_live_reference"]
    baseline = _stats(baseline_rows)
    baseline_recent = {str(days): _stats(_recent(baseline_rows, end_ts=end_ts, days=days)) for days in (365, 180, 90)}
    baseline_years = _group_stats(baseline_rows, lambda row: _parse_dt(row.get("entry_ts")).year)
    baseline_symbols = _group_stats(baseline_rows, lambda row: row.get("symbol"))
    baseline_quarters = _group_stats(baseline_rows, lambda row: _quarter(row.get("entry_ts")))

    variant_by_name = {variant.name: variant for variant in variants}
    models: list[dict[str, Any]] = []
    for name, rows in rows_by_variant.items():
        stats = _stats(rows)
        recent_stats = {str(days): _stats(_recent(rows, end_ts=end_ts, days=days)) for days in (365, 180, 90)}
        year_delta = _delta_map(_group_stats(rows, lambda row: _parse_dt(row.get("entry_ts")).year), baseline_years)
        symbol_delta = _delta_map(_group_stats(rows, lambda row: row.get("symbol")), baseline_symbols)
        quarter_delta = _delta_map(_group_stats(rows, lambda row: _quarter(row.get("entry_ts"))), baseline_quarters)
        item = {
            "name": name,
            "params": variant_by_name[name].as_dict(),
            "stats": stats,
            "delta_total_r": round(_safe_float(stats.get("total_r")) - _safe_float(baseline.get("total_r")), 4),
            "delta_ev_r": round(_safe_float(stats.get("ev_r")) - _safe_float(baseline.get("ev_r")), 4),
            "delta_dd_r": round(_safe_float(stats.get("max_dd_r")) - _safe_float(baseline.get("max_dd_r")), 4),
            "delta_trades": _safe_int(stats.get("trades")) - _safe_int(baseline.get("trades")),
            "recent_delta_total_r": {
                key: round(
                    _safe_float(recent_stats[key].get("total_r")) - _safe_float(baseline_recent[key].get("total_r")),
                    4,
                )
                for key in recent_stats
            },
            "recent_stats": recent_stats,
            "year_delta_total_r": year_delta,
            "symbol_delta_total_r": symbol_delta,
            "quarter_delta_total_r": quarter_delta,
            "negative_symbol_count": sum(1 for value in symbol_delta.values() if value < 0.0),
            "negative_symbols": [key for key, value in symbol_delta.items() if value < 0.0],
            "worst_symbol_delta_r": round(min(symbol_delta.values()), 4) if symbol_delta else 0.0,
            "negative_year_count": sum(1 for value in year_delta.values() if value < 0.0),
            "negative_quarter_count": sum(1 for value in quarter_delta.values() if value < 0.0),
            "worst_quarter_delta_r": round(min(quarter_delta.values()), 4) if quarter_delta else 0.0,
        }
        item["score"] = round(_score_model(item), 4)
        models.append(item)

    models.sort(key=lambda item: _safe_float(item.get("score")), reverse=True)
    strict = [
        item
        for item in models
        if item["name"] != "current_live_reference"
        and _safe_float(item.get("delta_total_r")) > 0.0
        and _safe_float(item.get("delta_ev_r")) >= 0.0
        and _safe_float(item.get("delta_dd_r")) <= 0.0
        and _safe_int(item.get("delta_trades")) > 0
        and _safe_int(item.get("negative_symbol_count")) == 0
        and _safe_int(item.get("negative_year_count")) == 0
        and _safe_int(item.get("negative_quarter_count")) == 0
    ]
    quality = [
        item
        for item in models
        if item["name"] != "current_live_reference"
        and _safe_float(item.get("delta_total_r")) > 0.0
        and _safe_float(item.get("delta_ev_r")) >= 0.005
        and _safe_int(item.get("negative_year_count")) == 0
        and _safe_int(item.get("negative_quarter_count")) == 0
    ]
    no_negative = [
        item
        for item in models
        if item["name"] != "current_live_reference"
        and _safe_int(item.get("negative_symbol_count")) == 0
        and _safe_int(item.get("negative_year_count")) == 0
        and _safe_int(item.get("negative_quarter_count")) == 0
    ]
    return {
        "baseline": baseline,
        "baseline_recent": baseline_recent,
        "strict_count": len(strict),
        "quality_count": len(quality),
        "no_negative_count": len(no_negative),
        "top_strict": strict[:100],
        "top_quality": quality[:120],
        "top_no_negative": no_negative[:150],
        "top_all": models[:150],
        "all_models": models,
    }


def _render_markdown(payload: dict[str, Any]) -> str:
    baseline = dict(payload.get("baseline") or {})
    lines = [
        f"# Micro Main {payload.get('search_name')} Raw Profile Search",
        "",
        f"- generated_at: {payload.get('generated_at')}",
        f"- variants: {payload.get('variant_count')}",
        f"- baseline: trades={baseline.get('trades')}, total_r={baseline.get('total_r')}, ev={baseline.get('ev_r')}, max_dd={baseline.get('max_dd_r')}",
        f"- strict: {payload.get('strict_count')}",
        f"- quality: {payload.get('quality_count')}",
        f"- no_negative: {payload.get('no_negative_count')}",
        "",
        "## Top Strict",
    ]
    for idx, item in enumerate(list(payload.get("top_strict") or [])[:15], start=1):
        stats = dict(item.get("stats") or {})
        recent = dict(item.get("recent_delta_total_r") or {})
        lines.append(
            f"{idx}. {item.get('name')}: trades={stats.get('trades')} ({item.get('delta_trades'):+}), "
            f"total={stats.get('total_r')} ({item.get('delta_total_r'):+}), ev={stats.get('ev_r')} "
            f"({item.get('delta_ev_r'):+}), dd={item.get('delta_dd_r'):+}, "
            f"recent365={_safe_float(recent.get('365')):+.4f}, worst_q={item.get('worst_quarter_delta_r')}"
        )
    lines.append("")
    lines.append("Full raw-candle signal regeneration. This is not post-trade filtering.")
    return "\n".join(lines) + "\n"


def main() -> int:
    args = _parse_args()
    settings = get_settings()
    generated_at = datetime.now(UTC)
    end_ts = generated_at.replace(second=0, microsecond=0)
    start_ts = end_ts - timedelta(days=max(int(args.days), 1))
    proxy_symbols = [item.strip().upper() for item in str(args.symbols or "").split(",") if item.strip()]
    variants = _build_variants()
    if int(args.max_variants or 0) > 0:
        variants = variants[: int(args.max_variants)]
    variant_names = [variant.name for variant in variants]
    rows_by_variant: dict[str, list[dict[str, Any]]] = {name: [] for name in variant_names}

    print(
        json.dumps(
            {
                "state": "start",
                "variants": len(variants),
                "symbols": proxy_symbols,
                "start_ts": start_ts.isoformat(),
                "end_ts": end_ts.isoformat(),
            },
            ensure_ascii=False,
        ),
        file=sys.stderr,
        flush=True,
    )

    with (
        httpx.Client(timeout=120.0, follow_redirects=True) as monthly_client,
        httpx.Client(base_url=settings.binance_rest_base_url, timeout=30.0) as rest_client,
    ):
        for proxy_symbol in proxy_symbols:
            canonical_symbol = canonical_symbol_for_proxy(proxy_symbol)
            if canonical_symbol is None:
                print(json.dumps({"state": "skip", "symbol": proxy_symbol, "reason": "missing_mapping"}), file=sys.stderr)
                continue
            candles_1m = _fetch_1m_klines(
                monthly_client,
                rest_client,
                symbol=proxy_symbol,
                start_ts=start_ts,
                end_ts=end_ts,
            )
            candles_5m = _resample_to_5m(candles_1m)
            if len(candles_1m) < 600 or len(candles_5m) < 200:
                print(
                    json.dumps(
                        {
                            "state": "skip",
                            "symbol": proxy_symbol,
                            "reason": "insufficient_candles",
                            "candles_1m": len(candles_1m),
                            "candles_5m": len(candles_5m),
                        },
                        ensure_ascii=False,
                    ),
                    file=sys.stderr,
                    flush=True,
                )
                continue
            engine = SessionImpulseRetestResearch(
                symbol=canonical_symbol,
                candles_1m=candles_1m,
                candles_5m=candles_5m,
                profile_name=session_impulse_retest_profile_for_symbol(canonical_symbol),
            )
            for index, variant in enumerate(variants, start=1):
                rows_by_variant[variant.name].extend(
                    _variant_rows_for_symbol(
                        engine=engine,
                        proxy_symbol=proxy_symbol,
                        canonical_symbol=canonical_symbol,
                        variant=variant,
                    )
                )
                if index == 1 or index == len(variants) or index % 50 == 0:
                    print(
                        json.dumps(
                            {
                                "state": "progress",
                                "symbol": proxy_symbol,
                                "variant_index": index,
                                "variant_count": len(variants),
                                "variant": variant.name,
                            },
                            ensure_ascii=False,
                        ),
                        file=sys.stderr,
                        flush=True,
                    )

    result = _evaluate_models(rows_by_variant, variants=variants, end_ts=end_ts)
    payload: dict[str, Any] = {
        "schema_version": f"micro_main_{args.search_name}_raw_profile_search_v1",
        "generated_at": generated_at.isoformat(),
        "search_name": str(args.search_name),
        "window": {"start_ts": start_ts.isoformat(), "end_ts": end_ts.isoformat(), "days": int(args.days)},
        "model_definition": "Full raw-candle SessionImpulseRetest profile search. Signals are regenerated for each variant.",
        "variant_count": len(variants),
        **result,
    }

    if args.write_report:
        report_dir = Path(settings.validation_report_dir) / "micro_main_raw_profile_model_searches"
        report_dir.mkdir(parents=True, exist_ok=True)
        stem = f"micro_main_{args.search_name}_raw_profile_search_{generated_at.strftime('%Y%m%dT%H%M%SZ')}"
        json_path = report_dir / f"{stem}.json"
        md_path = report_dir / f"{stem}.md"
        latest_json = report_dir / f"latest_{args.search_name}_raw_profile_search.json"
        latest_md = report_dir / f"latest_{args.search_name}_raw_profile_search.md"
        payload["report_path"] = str(json_path)
        payload["latest_report_path"] = str(latest_json)
        atomic_write_text(json_path, json.dumps(payload, ensure_ascii=False, indent=2))
        atomic_write_text(md_path, _render_markdown(payload))
        atomic_write_text(latest_json, json.dumps(payload, ensure_ascii=False, indent=2))
        atomic_write_text(latest_md, _render_markdown(payload))
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
