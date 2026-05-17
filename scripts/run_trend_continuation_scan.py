#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.db.repositories import CandleRepository
from app.db.session import SessionLocal, init_db
from app.services.historical_walk_forward_proof import HistoricalWalkForwardProofService
from app.services.historical_walk_forward_split_review import HistoricalWalkForwardSplitReviewService
from scripts.run_reaction_gate_variant_backtest import _filtered_rows, _result_payload
from scripts.run_transition_confluence_shadow_scan import (
    ConfluenceShadowPlanGenerator,
    ConfluenceVariantConfig,
    VariantConfig,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run repo-native future-blind trend_continuation scan with A/B comparison.")
    parser.add_argument("--lookback-days", type=int, default=365)
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--trend-entry-models", default="LIMIT,CONFIRM")
    parser.add_argument("--compare-a-entry-models", default="LIMIT")
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def _normalized_csv(raw: str) -> tuple[str, ...]:
    values = [str(item or "").strip().upper() for item in str(raw or "").split(",")]
    return tuple(item for item in values if item)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _daily_pnl(rows: list[dict[str, Any]]) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in rows:
        raw_ts = str(row.get("closed_ts") or "").strip()
        if not raw_ts:
            continue
        try:
            ts = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
        except ValueError:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        else:
            ts = ts.astimezone(UTC)
        day_key = ts.date().isoformat()
        realized_r = _safe_float(row.get("replayed_realized_r") or row.get("final_exit_realized_r"))
        out[day_key] = out.get(day_key, 0.0) + realized_r
    return out


def _correlation(a_rows: list[dict[str, Any]], b_rows: list[dict[str, Any]]) -> float | None:
    a_daily = _daily_pnl(a_rows)
    b_daily = _daily_pnl(b_rows)
    if not a_daily and not b_daily:
        return None
    days = sorted(set(a_daily) | set(b_daily))
    if len(days) < 2:
        return None
    a_values = [float(a_daily.get(day, 0.0)) for day in days]
    b_values = [float(b_daily.get(day, 0.0)) for day in days]
    mean_a = sum(a_values) / len(a_values)
    mean_b = sum(b_values) / len(b_values)
    cov = sum((x - mean_a) * (y - mean_b) for x, y in zip(a_values, b_values, strict=True))
    var_a = sum((x - mean_a) ** 2 for x in a_values)
    var_b = sum((y - mean_b) ** 2 for y in b_values)
    if var_a <= 1e-12 or var_b <= 1e-12:
        return None
    return cov / ((var_a ** 0.5) * (var_b ** 0.5))


def _regime_breakdown(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, float]] = {}
    for row in rows:
        regime = str(row.get("regime") or "unknown").strip().lower() or "unknown"
        payload = buckets.setdefault(regime, {"closed": 0.0, "total_r": 0.0})
        payload["closed"] += 1.0
        payload["total_r"] += _safe_float(row.get("replayed_realized_r") or row.get("final_exit_realized_r"))
    return [
        {"regime": regime, "closed": int(values["closed"]), "total_r": round(values["total_r"], 4)}
        for regime, values in sorted(buckets.items(), key=lambda item: (-item[1]["closed"], item[0]))
    ]


def _screen(result: dict[str, Any], *, corr_vs_a: float | None, corr_vs_b: float | None) -> dict[str, Any]:
    closed = int(result.get("closed_trades", 0) or 0)
    ev_r = float(result.get("ev_r", 0.0) or 0.0)
    corr_ok = True
    if corr_vs_a is not None and abs(float(corr_vs_a)) > 0.3:
        corr_ok = False
    if corr_vs_b is not None and abs(float(corr_vs_b)) > 0.3:
        corr_ok = False
    return {
        "ev_floor_pass": ev_r >= 0.20,
        "closed_floor_pass": closed >= 40,
        "correlation_pass": corr_ok,
        "screen_pass": ev_r >= 0.20 and closed >= 40 and corr_ok,
    }


def _simulate(
    *,
    proof: HistoricalWalkForwardProofService,
    review: HistoricalWalkForwardSplitReviewService,
    symbol: str,
    start_ts: datetime,
    end_ts: datetime,
    family: str,
    entry_models: tuple[str, ...],
    label: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    symbol_payload = proof._simulate_symbol(
        symbol=symbol,
        start_ts=start_ts,
        end_ts=end_ts,
        eligible_symbols={symbol},
        eligible_families={family},
        eligible_entry_models=set(entry_models),
        generate_on_new_15m_only=True,
        independent_signal_mode=True,
        max_candidates_per_bar=1,
        source_mode="engine_regenerated",
        blocked_time_contract=[],
        blocked_plan_ids=set(),
    )
    rows = _filtered_rows(list(symbol_payload.get("trade_rows") or []), start_ts=start_ts, end_ts=end_ts)
    payload = _result_payload(
        variant=VariantConfig(name=label),
        symbol_payload=symbol_payload,
        rows=rows,
        start_ts=start_ts,
        end_ts=end_ts,
        review=review,
    )
    payload["family"] = family
    payload["entry_models"] = list(entry_models)
    payload["regime_breakdown"] = _regime_breakdown(rows)
    return payload, rows


def main() -> int:
    args = _parse_args()
    init_db()
    settings = get_settings()
    review = HistoricalWalkForwardSplitReviewService(settings=settings)
    symbol = str(args.symbol).upper()
    trend_entry_models = _normalized_csv(args.trend_entry_models)
    compare_a_entry_models = _normalized_csv(args.compare_a_entry_models)

    with SessionLocal() as db:
        candle_repo = CandleRepository(db)
        baseline_proof = HistoricalWalkForwardProofService(candle_repo=candle_repo, settings=settings)
        latest_source_ts, _, first_source_ts, _ = baseline_proof._source_ts_bounds((symbol,))
        if latest_source_ts is None or first_source_ts is None:
            raise RuntimeError("unable to determine source candle bounds")
        start_ts = max(first_source_ts, latest_source_ts - timedelta(days=max(int(args.lookback_days), 1)))
        end_ts = latest_source_ts

        a_proof = HistoricalWalkForwardProofService(candle_repo=candle_repo, settings=settings)
        b_proof = HistoricalWalkForwardProofService(
            candle_repo=candle_repo,
            settings=settings,
            plan_generator=ConfluenceShadowPlanGenerator(
                reaction_variant=VariantConfig(name="proof_reclaim_plus_one_bar", proof_reclaim=True, one_bar=True),
                confluence_variant=ConfluenceVariantConfig(
                    name="exp_6_fvg_relaxed_plus_transition_override",
                    fvg_relaxed=True,
                    transition_override=True,
                ),
            ),
        )
        c_proof = HistoricalWalkForwardProofService(candle_repo=candle_repo, settings=settings)

        a_result, a_rows = _simulate(
            proof=a_proof,
            review=review,
            symbol=symbol,
            start_ts=start_ts,
            end_ts=end_ts,
            family="sweep_reversal",
            entry_models=compare_a_entry_models,
            label="a_baseline",
        )
        b_result, b_rows = _simulate(
            proof=b_proof,
            review=review,
            symbol=symbol,
            start_ts=start_ts,
            end_ts=end_ts,
            family="sweep_reversal",
            entry_models=("LIMIT",),
            label="b_transition_overlay_winner",
        )
        c_result, c_rows = _simulate(
            proof=c_proof,
            review=review,
            symbol=symbol,
            start_ts=start_ts,
            end_ts=end_ts,
            family="trend_continuation",
            entry_models=trend_entry_models,
            label="c_trend_continuation",
        )

    corr_vs_a = _correlation(a_rows, c_rows)
    corr_vs_b = _correlation(b_rows, c_rows)
    c_result["corr_vs_a_baseline_daily_pnl"] = None if corr_vs_a is None else round(float(corr_vs_a), 4)
    c_result["corr_vs_b_overlay_daily_pnl"] = None if corr_vs_b is None else round(float(corr_vs_b), 4)
    c_result["screen"] = _screen(c_result, corr_vs_a=corr_vs_a, corr_vs_b=corr_vs_b)

    output = {
        "generated_at": datetime.now(UTC).isoformat(),
        "symbol": symbol,
        "lookback_days": int(args.lookback_days),
        "source_mode": "engine_regenerated",
        "notes": [
            "A baseline uses strict sweep_reversal with the requested compare-a entry models.",
            "B overlay uses the current production-candidate winner: proof_reclaim_plus_one_bar + exp_6_fvg_relaxed_plus_transition_override.",
            "C uses the native trend_continuation family without adding a new routing stack.",
            "Correlation is computed on daily post-cost realized R vectors using replayed_realized_r / final_exit_realized_r.",
        ],
        "results": [a_result, b_result, c_result],
    }

    if args.write_report:
        out_dir = Path(settings.validation_report_dir) / "trend_continuation_scans"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / (
            f"trend_continuation_scan_{symbol}_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
        )
        out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        output["report_path"] = str(out_path)

    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
