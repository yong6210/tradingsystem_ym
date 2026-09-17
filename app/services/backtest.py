from __future__ import annotations

import random
from dataclasses import dataclass

from app.db.models import ZoneOutcome


@dataclass
class BacktestReport:
    trades: int
    mean_ev: float
    p5_ev: float
    p50_ev: float
    p95_ev: float
    method: str = "empirical_outcome_summary"
    out_of_sample_validated: bool = False


class BacktestService:
    @staticmethod
    def _trade_ev(outcome: ZoneOutcome) -> float:
        win = 1.0 if outcome.hit_1r else 0.0
        reward = 3.0 if outcome.hit_3r else 2.0 if outcome.hit_2r else 1.0 if outcome.hit_1r else 0.0
        loss = 1.0 if not outcome.hit_1r else 0.0
        return win * reward - loss

    def walk_forward(self, outcomes: list[ZoneOutcome], train_months: int = 3, test_months: int = 1) -> BacktestReport:
        """Legacy outcome summary; no model is trained or tested on held-out windows.

        Keep the method name for existing callers, but expose the actual methodology
        in the report. Contract-faithful walk-forward proof lives in
        HistoricalWalkForwardProofService.
        """
        if not outcomes:
            return BacktestReport(trades=0, mean_ev=0.0, p5_ev=0.0, p50_ev=0.0, p95_ev=0.0)

        outcomes = sorted(outcomes, key=lambda x: x.entry_ts)
        evs = [self._trade_ev(o) for o in outcomes]
        evs_sorted = sorted(evs)

        return BacktestReport(
            trades=len(evs),
            mean_ev=sum(evs) / len(evs),
            p5_ev=evs_sorted[max(0, int(0.05 * (len(evs_sorted) - 1)))],
            p50_ev=evs_sorted[int(0.50 * (len(evs_sorted) - 1))],
            p95_ev=evs_sorted[int(0.95 * (len(evs_sorted) - 1))],
        )

    def monte_carlo(
        self, outcomes: list[ZoneOutcome], simulations: int = 200, *, seed: int | None = None
    ) -> BacktestReport:
        """Bootstrap outcome-derived R values; these are not net exchange fill returns."""
        if isinstance(simulations, bool) or not isinstance(simulations, int) or simulations < 1:
            raise ValueError("simulations must be a positive integer")
        if not outcomes:
            return BacktestReport(trades=0, mean_ev=0.0, p5_ev=0.0, p50_ev=0.0, p95_ev=0.0, method="iid_bootstrap_mean_ev")

        base = [self._trade_ev(o) for o in outcomes]
        rng = random.Random(seed)
        runs: list[float] = []
        for _ in range(simulations):
            sample = rng.choices(base, k=len(base))
            runs.append(sum(sample) / len(sample))

        s = sorted(runs)
        return BacktestReport(
            trades=len(base),
            mean_ev=sum(runs) / len(runs),
            p5_ev=s[int(0.05 * (len(s) - 1))],
            p50_ev=s[int(0.50 * (len(s) - 1))],
            p95_ev=s[int(0.95 * (len(s) - 1))],
            method="iid_bootstrap_mean_ev",
        )
