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
from app.services.common import clamp
from app.services.historical_walk_forward_proof import HistoricalWalkForwardProofService
from app.services.historical_walk_forward_split_review import HistoricalWalkForwardSplitReviewService
from app.services.plan_generator import RegimeProfile
from app.db.repositories import CandleRepository
from app.db.session import SessionLocal, init_db
from scripts.run_reaction_gate_variant_backtest import (
    VariantConfig,
    VariantPlanGenerator,
    _filtered_rows,
    _result_payload,
)


@dataclass(frozen=True, slots=True)
class ConfluenceVariantConfig:
    name: str
    remove_trend_proxy: bool = False
    fvg_relaxed: bool = False
    transition_override: bool = False


_DEFAULT_VARIANTS: tuple[ConfluenceVariantConfig, ...] = (
    ConfluenceVariantConfig(name="baseline"),
    ConfluenceVariantConfig(name="exp_1_no_trend_proxy", remove_trend_proxy=True),
    ConfluenceVariantConfig(name="exp_2_fvg_relaxed", fvg_relaxed=True),
    ConfluenceVariantConfig(name="exp_3_transition_override", transition_override=True),
    ConfluenceVariantConfig(name="exp_4_no_trend_proxy_plus_fvg_relaxed", remove_trend_proxy=True, fvg_relaxed=True),
    ConfluenceVariantConfig(name="exp_5_no_trend_proxy_plus_transition_override", remove_trend_proxy=True, transition_override=True),
    ConfluenceVariantConfig(name="exp_6_fvg_relaxed_plus_transition_override", fvg_relaxed=True, transition_override=True),
    ConfluenceVariantConfig(name="exp_7_all", remove_trend_proxy=True, fvg_relaxed=True, transition_override=True),
)


class ConfluenceShadowPlanGenerator(VariantPlanGenerator):
    _TRANSITION_MIN_CONFLUENCE_DELTA = 8.0
    _TRANSITION_ALIGNMENT_WEIGHT_MULTIPLIER = 0.5
    _TRANSITION_TREND_PROXY_WEIGHT_MULTIPLIER = 0.25
    _FVG_RELAX_FACTOR = 0.7

    def __init__(self, *, reaction_variant: VariantConfig, confluence_variant: ConfluenceVariantConfig):
        super().__init__(reaction_variant)
        self.confluence_variant = confluence_variant

    def _regime_profile(self, context) -> RegimeProfile:
        profile = super()._regime_profile(context)
        if not self.confluence_variant.transition_override or profile.name != "transition":
            return profile
        min_confluence_score = self._safe_float(self.settings.min_confluence_score, default=62.0)
        profile_min_confluence = self._safe_float(profile.min_confluence, default=min_confluence_score)
        return RegimeProfile(
            name=profile.name,
            min_confluence=max(min_confluence_score, profile_min_confluence - self._TRANSITION_MIN_CONFLUENCE_DELTA),
            rr_floor=profile.rr_floor,
            ev_floor=profile.ev_floor,
            weight_liquidity=profile.weight_liquidity,
            weight_fvg_displacement=profile.weight_fvg_displacement,
            weight_htf_alignment=profile.weight_htf_alignment,
            weight_ob_freshness=profile.weight_ob_freshness,
            weight_trend_proxy=profile.weight_trend_proxy,
        )

    def _active_feature_weights(
        self,
        *,
        profile: RegimeProfile,
        feature_overrides: dict[str, float] | None = None,
        importance_calibration: dict[str, dict] | None = None,
    ) -> tuple[dict[str, float], dict[str, float]]:
        base_weights, active_weights = super()._active_feature_weights(
            profile=profile,
            feature_overrides=feature_overrides,
            importance_calibration=importance_calibration,
        )
        adjusted = dict(active_weights)
        if self.confluence_variant.remove_trend_proxy:
            adjusted["trend_proxy"] = 0.0
        if self.confluence_variant.transition_override and profile.name == "transition":
            adjusted["htf_alignment"] = float(adjusted.get("htf_alignment", 0.0)) * self._TRANSITION_ALIGNMENT_WEIGHT_MULTIPLIER
            adjusted["trend_proxy"] = float(adjusted.get("trend_proxy", 0.0)) * self._TRANSITION_TREND_PROXY_WEIGHT_MULTIPLIER
        adjusted = self._normalize_weights(adjusted, min_weight=0.0)
        return base_weights, adjusted

    def _fvg_displacement_score(self, zone, context) -> float:
        base = float(super()._fvg_displacement_score(zone, context))
        if not self.confluence_variant.fvg_relaxed:
            return base
        floor = 45.0
        relaxed = floor + max(base - floor, 0.0) / self._FVG_RELAX_FACTOR
        return clamp(relaxed, 0.0, 100.0)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run future-blind transition/confluence shadow scans.")
    parser.add_argument("--lookback-days", type=int, default=365)
    parser.add_argument("--symbol", default="BTCUSDC")
    parser.add_argument("--family", default="sweep_reversal")
    parser.add_argument("--entry-model", default="LIMIT")
    parser.add_argument("--variants", default=",".join(item.name for item in _DEFAULT_VARIANTS))
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def _selected_variants(raw: str) -> list[ConfluenceVariantConfig]:
    requested = {item.strip() for item in str(raw or "").split(",") if item.strip()}
    selected = [item for item in _DEFAULT_VARIANTS if item.name in requested]
    if not selected:
        raise ValueError("no variants selected")
    return selected


def main() -> int:
    args = _parse_args()
    init_db()
    settings = get_settings()
    review = HistoricalWalkForwardSplitReviewService(settings=settings)
    confluence_variants = _selected_variants(args.variants)
    reaction_variant = VariantConfig(name="proof_reclaim_plus_one_bar", proof_reclaim=True, one_bar=True)

    with SessionLocal() as db:
        candle_repo = CandleRepository(db)
        baseline_proof = HistoricalWalkForwardProofService(candle_repo=candle_repo, settings=settings)
        latest_source_ts, _, first_source_ts, _ = baseline_proof._source_ts_bounds((str(args.symbol).upper(),))
        if latest_source_ts is None or first_source_ts is None:
            raise RuntimeError("unable to determine source candle bounds")
        start_ts = max(first_source_ts, latest_source_ts - timedelta(days=max(int(args.lookback_days), 1)))
        end_ts = latest_source_ts

        results: list[dict[str, Any]] = []
        for variant in confluence_variants:
            proof = HistoricalWalkForwardProofService(
                candle_repo=candle_repo,
                settings=settings,
                plan_generator=ConfluenceShadowPlanGenerator(
                    reaction_variant=reaction_variant,
                    confluence_variant=variant,
                ),
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
            result = _result_payload(
                variant=VariantConfig(name=variant.name),
                symbol_payload=symbol_payload,
                rows=rows,
                start_ts=start_ts,
                end_ts=end_ts,
                review=review,
            )
            result["confluence_variant"] = {
                "remove_trend_proxy": variant.remove_trend_proxy,
                "fvg_relaxed": variant.fvg_relaxed,
                "transition_override": variant.transition_override,
            }
            results.append(result)

    output = {
        "generated_at": datetime.now(UTC).isoformat(),
        "symbol": str(args.symbol).upper(),
        "family": str(args.family).lower(),
        "entry_model": str(args.entry_model).upper(),
        "lookback_days": int(args.lookback_days),
        "baseline_reaction_variant": reaction_variant.name,
        "notes": [
            "All variants keep proof_reclaim_plus_one_bar reaction rescue enabled.",
            "exp_1 removes trend_proxy weight completely.",
            "exp_2 relaxes fvg_displacement by scaling the score above the 45-point floor with a 0.7 factor.",
            "exp_3 applies transition-only overrides: min_confluence -8, htf_alignment weight x0.5, trend_proxy weight x0.25.",
        ],
        "results": results,
    }

    if args.write_report:
        out_dir = Path(settings.validation_report_dir) / "transition_confluence_shadow_scans"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / (
            f"transition_confluence_shadow_scan_{str(args.symbol).upper()}_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
        )
        out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        output["report_path"] = str(out_path)

    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
