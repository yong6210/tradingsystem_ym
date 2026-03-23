from __future__ import annotations

from app.core.config import get_settings
from app.db.models import Zone, ZoneOutcome
from app.services.common import clamp


class LearningService:
    def __init__(self):
        self.settings = get_settings()

    @staticmethod
    def _beta_mean(hits: int, total: int, *, prior_mean: float, prior_strength: float) -> float:
        alpha = prior_mean * prior_strength
        beta = (1.0 - prior_mean) * prior_strength
        return (hits + alpha) / max(total + alpha + beta, 1e-9)

    @staticmethod
    def summarize(outcomes: list[ZoneOutcome]) -> dict[str, float]:
        if not outcomes:
            return {
                "p1r": 0.0,
                "p2r": 0.0,
                "p3r": 0.0,
                "avgMFE": 0.0,
                "avgMAE": 0.0,
                "sweep_success_rate": 0.0,
                "ev_r": 0.0,
                "sample_size": 0.0,
            }

        n = len(outcomes)
        hit_1r = sum(1 for o in outcomes if o.hit_1r)
        hit_2r = sum(1 for o in outcomes if o.hit_2r)
        hit_3r = sum(1 for o in outcomes if o.hit_3r)
        p1r = LearningService._beta_mean(hit_1r, n, prior_mean=0.55, prior_strength=16.0)
        p2r = LearningService._beta_mean(hit_2r, n, prior_mean=0.40, prior_strength=16.0)
        p3r = LearningService._beta_mean(hit_3r, n, prior_mean=0.22, prior_strength=16.0)
        avg_mfe = sum(o.mfe_atr for o in outcomes) / n
        avg_mae = sum(o.mae_atr for o in outcomes) / n

        sweep_n = sum(1 for o in outcomes if o.sweep_detected)
        sweep_success = sum(1 for o in outcomes if o.sweep_detected and o.sweep_success)
        if sweep_n:
            sweep_success_rate = LearningService._beta_mean(
                sweep_success,
                sweep_n,
                prior_mean=0.45,
                prior_strength=10.0,
            )
        else:
            sweep_success_rate = 0.0

        # Expected R using hierarchical hit probabilities.
        ev_r = (p1r - p2r) * 1.0 + (p2r - p3r) * 2.0 + p3r * 3.0 - (1.0 - p1r)

        return {
            "p1r": p1r,
            "p2r": p2r,
            "p3r": p3r,
            "avgMFE": avg_mfe,
            "avgMAE": avg_mae,
            "sweep_success_rate": sweep_success_rate,
            "ev_r": ev_r,
            "sample_size": float(n),
        }

    def update_zone_quality(self, zone: Zone, stats: dict[str, float]) -> Zone:
        sample_size = int(stats.get("sample_size", 0.0))
        sample_factor = clamp(sample_size / max(self.settings.min_zone_sample_for_full_confidence, 1), 0.15, 1.0)
        quality = (
            35
            + stats.get("p1r", 0.0) * 12
            + stats.get("p2r", 0.0) * 24
            + stats.get("p3r", 0.0) * 18
            + stats.get("sweep_success_rate", 0.0) * 8
            + min(stats.get("avgMFE", 0.0), 3.0) * 2
            - min(stats.get("avgMAE", 0.0), 3.0) * 6
            + stats.get("ev_r", 0.0) * 10
        )
        blended = 0.65 * zone.base_strength + 0.35 * quality
        zone.quality = clamp(zone.quality * (1.0 - sample_factor) + blended * sample_factor, 0, 100)
        zone.stats = stats
        return zone

    @staticmethod
    def strategy_metric(stats: dict[str, float]) -> dict[str, float]:
        win_rate = stats.get("p1r", 0.0)
        p2 = stats.get("p2r", 0.0)
        p3 = stats.get("p3r", 0.0)
        avg_win = max(0.0, p2 * 2.0 + p3 * 3.0)
        avg_loss = 1.0
        ev = win_rate * avg_win - (1.0 - win_rate) * avg_loss
        return {
            "win_rate": win_rate,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "ev": ev,
            "p1r": stats.get("p1r", 0.0),
            "p2r": p2,
            "p3r": p3,
        }
