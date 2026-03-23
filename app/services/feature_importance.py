from __future__ import annotations

from dataclasses import dataclass

from app.db.models import Candle, Zone
from app.services.common import clamp
from app.services.context_engine import ContextSnapshot
from app.services.plan_generator import PlanGenerator, RankedPlan

FEATURE_KEYS = [
    "liquidity",
    "fvg_displacement",
    "htf_alignment",
    "ob_freshness",
    "trend_proxy",
]


@dataclass(slots=True)
class FeatureSnapshot:
    generated_plans: int
    mean_ev: float
    mean_confidence: float
    top_rank_score: float

    def to_dict(self) -> dict[str, float | int]:
        return {
            "generated_plans": self.generated_plans,
            "mean_ev": round(self.mean_ev, 6),
            "mean_confidence": round(self.mean_confidence, 6),
            "top_rank_score": round(self.top_rank_score, 6),
        }


class FeatureImportanceService:
    def __init__(self, generator: PlanGenerator):
        self.generator = generator

    @staticmethod
    def _snapshot(ranked: list[RankedPlan]) -> FeatureSnapshot:
        if not ranked:
            return FeatureSnapshot(
                generated_plans=0,
                mean_ev=0.0,
                mean_confidence=0.0,
                top_rank_score=0.0,
            )

        mean_ev = sum(item.plan.ev for item in ranked) / len(ranked)
        mean_confidence = sum(item.plan.confidence for item in ranked) / len(ranked)
        top_rank_score = ranked[0].final_rank_score
        return FeatureSnapshot(
            generated_plans=len(ranked),
            mean_ev=mean_ev,
            mean_confidence=mean_confidence,
            top_rank_score=top_rank_score,
        )

    @staticmethod
    def _importance_score(baseline: FeatureSnapshot, ablated: FeatureSnapshot) -> float:
        delta_rank = baseline.top_rank_score - ablated.top_rank_score
        delta_ev = baseline.mean_ev - ablated.mean_ev
        delta_confidence = baseline.mean_confidence - ablated.mean_confidence
        delta_count = float(baseline.generated_plans - ablated.generated_plans)
        score = 0.45 * delta_rank + 18.0 * delta_ev + 35.0 * delta_confidence + 1.5 * delta_count
        return clamp(score, -100.0, 100.0)

    def analyze(
        self,
        *,
        symbol: str,
        zones: list[Zone],
        context: ContextSnapshot,
        candles_5m: list[Candle] | None = None,
        feature_overrides: dict[str, float] | None = None,
        importance_calibration: dict[str, dict] | None = None,
    ) -> dict:
        active_zones = [z for z in zones if z.state != "expired"]
        if not active_zones:
            return {
                "symbol": symbol,
                "available": False,
                "reason": "no_active_zones",
                "baseline": {},
                "by_feature": {},
                "ranking": [],
            }

        baseline_ranked = self.generator.generate(
            symbol=symbol,
            zones=active_zones,
            context=context,
            candles_5m=candles_5m,
            feature_overrides=feature_overrides,
            importance_calibration=importance_calibration,
        )
        baseline = self._snapshot(baseline_ranked)
        if baseline.generated_plans == 0:
            return {
                "symbol": symbol,
                "available": False,
                "reason": "baseline_empty",
                "baseline": baseline.to_dict(),
                "by_feature": {},
                "ranking": [],
            }

        by_feature: dict[str, dict] = {}
        ranking: list[dict] = []
        for feature in FEATURE_KEYS:
            ranked = self.generator.generate(
                symbol=symbol,
                zones=active_zones,
                context=context,
                candles_5m=candles_5m,
                feature_overrides={**(feature_overrides or {}), feature: 0.0},
                importance_calibration=importance_calibration,
            )
            ablated = self._snapshot(ranked)
            importance_score = self._importance_score(baseline, ablated)

            delta_rank = baseline.top_rank_score - ablated.top_rank_score
            delta_ev = baseline.mean_ev - ablated.mean_ev
            delta_confidence = baseline.mean_confidence - ablated.mean_confidence
            delta_count = baseline.generated_plans - ablated.generated_plans
            row = {
                "feature": feature,
                "importance_score": round(importance_score, 6),
                "delta_top_rank_score": round(delta_rank, 6),
                "delta_mean_ev": round(delta_ev, 6),
                "delta_mean_confidence": round(delta_confidence, 6),
                "delta_generated_plans": int(delta_count),
                "ablated": ablated.to_dict(),
            }
            by_feature[feature] = row
            ranking.append(row)

        ranking.sort(key=lambda item: item["importance_score"], reverse=True)
        return {
            "symbol": symbol,
            "available": True,
            "reason": None,
            "baseline": baseline.to_dict(),
            "by_feature": by_feature,
            "ranking": ranking,
        }
