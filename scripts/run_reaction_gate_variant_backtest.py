#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.core.enums import EntryModel
from app.db.models import Zone
from app.db.repositories import CandleRepository
from app.db.session import SessionLocal, init_db
from app.services.acceptance_rejection_classifier import (
    AcceptanceRejectionClassifierService,
    AcceptanceRejectionResult,
)
from app.services.common import clamp
from app.services.report_io import atomic_write_text
from app.services.context_engine import ContextSnapshot
from app.services.historical_walk_forward_proof import HistoricalWalkForwardProofService
from app.services.historical_walk_forward_split_review import HistoricalWalkForwardSplitReviewService
from app.services.plan_generator import PlanGenerator


@dataclass(frozen=True, slots=True)
class VariantConfig:
    name: str
    zone_band: bool = False
    one_bar: bool = False
    proof_reclaim: bool = False
    zone_band_fraction: float | None = None
    proof_reclaim_total_bars: int | None = None
    proof_reclaim_exclude_recent_bars: int | None = None
    proof_reclaim_sweep_atr_threshold: float | None = None


_DEFAULT_VARIANTS: tuple[VariantConfig, ...] = (
    VariantConfig(name="baseline_strict"),
    VariantConfig(name="zone_band_only", zone_band=True),
    VariantConfig(name="one_bar_only", one_bar=True),
    VariantConfig(name="zone_band_plus_one_bar", zone_band=True, one_bar=True),
    VariantConfig(name="proof_reclaim_only", proof_reclaim=True),
    VariantConfig(name="proof_reclaim_plus_one_bar", proof_reclaim=True, one_bar=True),
    VariantConfig(name="proof_reclaim_plus_zone_band", proof_reclaim=True, zone_band=True),
    VariantConfig(name="all_relaxed", zone_band=True, one_bar=True, proof_reclaim=True),
)


class VariantReactionClassifier:
    def __init__(self, *, settings: Any, variant: VariantConfig):
        self.settings = settings
        self.variant = variant
        self.base = AcceptanceRejectionClassifierService(settings)

    def build_input_with_reason(self, *args: Any, **kwargs: Any) -> tuple[dict[str, Any] | None, str]:
        return self.base.build_input_with_reason(*args, **kwargs)

    def classify(self, input_payload: dict[str, Any] | None) -> AcceptanceRejectionResult:
        return self.base.classify(input_payload)

    def _zone_band_level(self, zone: Zone) -> float | None:
        width = max(float(zone.high) - float(zone.low), 0.0)
        if width <= 1e-9:
            return None
        band_fraction = float(
            self.variant.zone_band_fraction
            if self.variant.zone_band_fraction is not None
            else PlanGenerator._REACTION_SHADOW_ZONE_BAND_FRACTION
        )
        band = width * band_fraction
        if str(zone.dir_bias or "") == "support":
            return float(zone.low) + band
        if str(zone.dir_bias or "") == "resistance":
            return float(zone.high) - band
        return None

    def _proof_reclaim_shadow_signal(
        self,
        *,
        zone: Zone,
        context: ContextSnapshot,
        candles_5m: list[Any] | None,
    ) -> tuple[dict[str, Any] | None, str]:
        if not candles_5m:
            return None, "insufficient_candles"
        total_bars = int(
            self.variant.proof_reclaim_total_bars
            if self.variant.proof_reclaim_total_bars is not None
            else PlanGenerator._PROOF_RECLAIM_LOOKBACK_TOTAL_BARS
        )
        exclude_recent = int(
            self.variant.proof_reclaim_exclude_recent_bars
            if self.variant.proof_reclaim_exclude_recent_bars is not None
            else PlanGenerator._PROOF_RECLAIM_EXCLUDE_RECENT_BARS
        )
        if len(candles_5m) < total_bars:
            return None, "insufficient_candles"

        prior_window = candles_5m[-total_bars:-exclude_recent]
        if not prior_window:
            return None, "insufficient_prior_window"

        atr15 = float(context.atr15 or 0.0)
        if atr15 <= 1e-9:
            return None, "insufficient_atr"

        latest = candles_5m[-1]
        latest_high = float(latest.h)
        latest_low = float(latest.l)
        latest_close = float(latest.c)
        latest_range = max(latest_high - latest_low, 1e-9)
        close_position = (latest_close - latest_low) / latest_range
        sweep_atr_threshold = float(
            self.variant.proof_reclaim_sweep_atr_threshold
            if self.variant.proof_reclaim_sweep_atr_threshold is not None
            else PlanGenerator._PROOF_RECLAIM_SWEEP_ATR_THRESHOLD
        )
        sweep_threshold = atr15 * sweep_atr_threshold

        if str(zone.dir_bias or "") == "support":
            prior_level = min(float(c.l) for c in prior_window)
            if latest_low < prior_level - sweep_threshold and latest_close > prior_level and close_position >= 0.4:
                entry_model = (
                    EntryModel.LIMIT
                    if close_position >= 0.68
                    else EntryModel.SWEEP_CONFIRM
                    if close_position >= 0.52
                    else EntryModel.CONFIRM
                )
                return {
                    "entry_model": entry_model.value,
                    "swept_level": round(prior_level, 6),
                    "sweep_side": "below",
                }, "ok"
            return None, "proof_reclaim_not_met"

        if str(zone.dir_bias or "") == "resistance":
            prior_level = max(float(c.h) for c in prior_window)
            if latest_high > prior_level + sweep_threshold and latest_close < prior_level and close_position <= 0.6:
                entry_model = (
                    EntryModel.LIMIT
                    if close_position <= 0.32
                    else EntryModel.SWEEP_CONFIRM
                    if close_position <= 0.48
                    else EntryModel.CONFIRM
                )
                return {
                    "entry_model": entry_model.value,
                    "swept_level": round(prior_level, 6),
                    "sweep_side": "above",
                }, "ok"
            return None, "proof_reclaim_not_met"

        return None, "unsupported_zone_direction"

    def _proof_reclaim_result(
        self,
        *,
        signal: dict[str, Any],
        context: ContextSnapshot,
    ) -> AcceptanceRejectionResult:
        entry_model = str(signal.get("entry_model") or "")
        confirmed = entry_model == EntryModel.LIMIT.value
        session_quality = clamp(1.0 - (0.65 * float(context.friction_5m or 0.0) + 0.35 * float(context.jump_rate_5m or 0.0)), 0.0, 1.0)
        return AcceptanceRejectionResult(
            available=True,
            classification="rejection_confirmed" if confirmed else "rejection_tentative",
            rejection_score=82.0 if confirmed else 68.0,
            acceptance_score=18.0,
            rejection_hard_count=3 if confirmed else 2,
            acceptance_hard_count=0,
            mixed_reasons=[],
            input={
                "shadow_variant": "proof_reclaim",
                "swept_level": float(signal.get("swept_level") or 0.0),
                "sweep_side": str(signal.get("sweep_side") or ""),
                "outside_close_count": 0,
                "session_quality": float(session_quality),
            },
        )

    @staticmethod
    def _is_rejection(result: AcceptanceRejectionResult) -> bool:
        return bool(result.available) and str(result.classification or "") in {
            "rejection_confirmed",
            "rejection_tentative",
        }

    def classify_zone(
        self,
        *,
        zone: Zone,
        context: ContextSnapshot,
        candles_5m: list[Any] | None,
    ) -> AcceptanceRejectionResult:
        exact_input, exact_reason = self.base.build_input_with_reason(
            zone=zone,
            context=context,
            candles_5m=candles_5m,
        )
        if exact_input is not None:
            return self.base.classify(exact_input)

        last_result = self.base.classify(None)
        current_reason = str(exact_reason or "not_applicable")

        band_level = None
        if self.variant.zone_band and current_reason == "no_recent_level_sweep":
            band_level = self._zone_band_level(zone)
            if band_level is not None:
                zone_band_input, zone_band_reason = self.base.build_input_with_reason(
                    zone=zone,
                    context=context,
                    candles_5m=candles_5m,
                    sweep_level_override=band_level,
                    swept_level_type_override=f"{zone.type}_zone_band",
                )
                current_reason = str(zone_band_reason or current_reason)
                if zone_band_input is not None:
                    zone_band_result = self.base.classify(zone_band_input)
                    zone_band_result.input = dict(zone_band_result.input or {})
                    zone_band_result.input["shadow_variant"] = "zone_band"
                    if self._is_rejection(zone_band_result):
                        return zone_band_result
                    last_result = zone_band_result

        if self.variant.one_bar and current_reason == "insufficient_post_sweep_bars":
            kwargs: dict[str, Any] = {"min_event_bars": 1}
            if self.variant.zone_band and band_level is not None:
                kwargs["sweep_level_override"] = band_level
                kwargs["swept_level_type_override"] = f"{zone.type}_zone_band"
            one_bar_input, one_bar_reason = self.base.build_input_with_reason(
                zone=zone,
                context=context,
                candles_5m=candles_5m,
                **kwargs,
            )
            current_reason = str(one_bar_reason or current_reason)
            if one_bar_input is not None:
                one_bar_result = self.base.classify(one_bar_input)
                one_bar_result.input = dict(one_bar_result.input or {})
                one_bar_result.input["shadow_variant"] = "one_bar"
                if self._is_rejection(one_bar_result):
                    return one_bar_result
                last_result = one_bar_result

        if self.variant.proof_reclaim:
            proof_signal, _ = self._proof_reclaim_shadow_signal(zone=zone, context=context, candles_5m=candles_5m)
            if proof_signal is not None:
                return self._proof_reclaim_result(signal=proof_signal, context=context)

        return last_result


class VariantPlanGenerator(PlanGenerator):
    def __init__(self, variant: VariantConfig):
        super().__init__()
        self.variant = variant
        self.reaction_classifier = VariantReactionClassifier(settings=self.settings, variant=variant)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run future-blind reaction-gate variant backtests.")
    parser.add_argument("--lookback-days", type=int, default=365)
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--family", default="sweep_reversal")
    parser.add_argument("--entry-model", default="LIMIT")
    parser.add_argument("--variants", default=",".join(item.name for item in _DEFAULT_VARIANTS))
    parser.add_argument("--write-report", action="store_true")
    parser.add_argument("--zone-band-fraction", type=float, default=None)
    parser.add_argument("--proof-reclaim-total-bars", type=int, default=None)
    parser.add_argument("--proof-reclaim-exclude-recent-bars", type=int, default=None)
    parser.add_argument("--proof-reclaim-sweep-atr-threshold", type=float, default=None)
    return parser.parse_args()


def _selected_variants(raw: str, args: argparse.Namespace) -> list[VariantConfig]:
    requested = {item.strip() for item in str(raw or "").split(",") if item.strip()}
    selected = [
        VariantConfig(
            name=item.name,
            zone_band=item.zone_band,
            one_bar=item.one_bar,
            proof_reclaim=item.proof_reclaim,
            zone_band_fraction=args.zone_band_fraction,
            proof_reclaim_total_bars=args.proof_reclaim_total_bars,
            proof_reclaim_exclude_recent_bars=args.proof_reclaim_exclude_recent_bars,
            proof_reclaim_sweep_atr_threshold=args.proof_reclaim_sweep_atr_threshold,
        )
        for item in _DEFAULT_VARIANTS
        if item.name in requested
    ]
    if not selected:
        raise ValueError("no variants selected")
    return selected


def _metrics(review: HistoricalWalkForwardSplitReviewService, rows: list[dict[str, Any]]) -> dict[str, Any]:
    return dict(review._metrics(rows))


def _filtered_rows(rows: list[dict[str, Any]], *, start_ts: datetime, end_ts: datetime) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for row in rows:
        raw_ts = str(row.get("generated_ts") or row.get("entry_ts") or row.get("closed_ts") or "").strip()
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
        if start_ts <= ts <= end_ts:
            filtered.append(dict(row))
    return filtered


def _result_payload(
    *,
    variant: VariantConfig,
    symbol_payload: dict[str, Any],
    rows: list[dict[str, Any]],
    start_ts: datetime,
    end_ts: datetime,
    review: HistoricalWalkForwardSplitReviewService,
) -> dict[str, Any]:
    metrics = _metrics(review, rows)
    generated = int(symbol_payload.get("generated_contract_candidate_count", 0) or 0)
    selected = int(symbol_payload.get("selected_contract_candidate_count", 0) or 0)
    unfilled = int(symbol_payload.get("unfilled_candidate_count", 0) or 0)
    eligible_bars = int(symbol_payload.get("eligible_bar_count", 0) or 0)
    no_candidate_bars = int(symbol_payload.get("no_candidate_bar_count", 0) or 0)
    total_days = max((end_ts - start_ts).total_seconds() / 86400.0, 1e-9)
    return {
        "variant": variant.name,
        "window_start_utc": start_ts.isoformat(),
        "window_end_utc": end_ts.isoformat(),
        "generated_contract_candidates": generated,
        "selected_contract_candidates": selected,
        "unfilled_candidates": unfilled,
        "eligible_bars": eligible_bars,
        "no_candidate_bars": no_candidate_bars,
        "generated_candidates_per_week": round(generated / total_days * 7.0, 4),
        "selected_candidates_per_week": round(selected / total_days * 7.0, 4),
        "closed_trades": int(metrics.get("trades", 0) or 0),
        "win_rate": float(metrics.get("win_rate", 0.0) or 0.0),
        "ev_r": float(metrics.get("ev_r", 0.0) or 0.0),
        "total_r": float(metrics.get("total_r", 0.0) or 0.0),
        "profit_factor": metrics.get("profit_factor"),
        "avg_win_r": float(metrics.get("avg_win_r", 0.0) or 0.0),
        "avg_loss_r": float(metrics.get("avg_loss_r", 0.0) or 0.0),
        "max_drawdown_r": float(metrics.get("max_drawdown_r", 0.0) or 0.0),
        "avg_hold_bars": float(metrics.get("avg_hold_bars", 0.0) or 0.0),
        "stop_loss_share": float(metrics.get("stop_loss_share", 0.0) or 0.0),
        "target_tp3_share": float(metrics.get("target_tp3_share", 0.0) or 0.0),
        "session_end_flatten_share": float(metrics.get("session_end_flatten_share", 0.0) or 0.0),
        "worst_loss_streak": int(metrics.get("worst_loss_streak", 0) or 0),
    }


def main() -> int:
    args = _parse_args()
    init_db()
    settings = get_settings()
    variants = _selected_variants(args.variants, args)
    review = HistoricalWalkForwardSplitReviewService(settings=settings)

    with SessionLocal() as db:
        candle_repo = CandleRepository(db)
        baseline_proof = HistoricalWalkForwardProofService(candle_repo=candle_repo, settings=settings)
        latest_source_ts, _, first_source_ts, _ = baseline_proof._source_ts_bounds((str(args.symbol).upper(),))
        if latest_source_ts is None or first_source_ts is None:
            raise RuntimeError("unable to determine source candle bounds")
        start_ts = max(first_source_ts, latest_source_ts - timedelta(days=max(int(args.lookback_days), 1)))
        end_ts = latest_source_ts

        results: list[dict[str, Any]] = []
        for variant in variants:
            proof = HistoricalWalkForwardProofService(
                candle_repo=candle_repo,
                settings=settings,
                plan_generator=VariantPlanGenerator(variant),
            )
            symbol_payload = proof._simulate_symbol(
                symbol=str(args.symbol).upper(),
                start_ts=start_ts,
                end_ts=end_ts,
                eligible_symbols={str(args.symbol).upper()},
                eligible_families={str(args.family).lower()},
                eligible_entry_models={str(args.entry_model).upper()},
                generate_on_new_15m_only=True,
                independent_signal_mode=True,
                max_candidates_per_bar=1,
                source_mode="engine_regenerated",
                blocked_time_contract=[],
                blocked_plan_ids=set(),
            )
            rows = _filtered_rows(list(symbol_payload.get("trade_rows") or []), start_ts=start_ts, end_ts=end_ts)
            results.append(
                _result_payload(
                    variant=variant,
                    symbol_payload=symbol_payload,
                    rows=rows,
                    start_ts=start_ts,
                    end_ts=end_ts,
                    review=review,
                )
            )

    output = {
        "generated_at": datetime.now(UTC).isoformat(),
        "symbol": str(args.symbol).upper(),
        "family": str(args.family).lower(),
        "entry_model": str(args.entry_model).upper(),
        "lookback_days": int(args.lookback_days),
        "results": results,
    }

    if args.write_report:
        out_dir = Path(settings.validation_report_dir) / "reaction_gate_variant_backtests"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / (
            f"reaction_gate_variant_backtest_{str(args.symbol).upper()}_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
        )
        atomic_write_text(out_path, json.dumps(output, ensure_ascii=False, indent=2))
        output["report_path"] = str(out_path)

    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
