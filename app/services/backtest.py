from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime

from app.db.models import ZoneOutcome


@dataclass
class BacktestReport:
    trades: int
    mean_ev: float
    p5_ev: float
    p50_ev: float
    p95_ev: float


class BacktestService:
    @staticmethod
    def _trade_ev(outcome: ZoneOutcome) -> float:
        win = 1.0 if outcome.hit_1r else 0.0
        reward = 3.0 if outcome.hit_3r else 2.0 if outcome.hit_2r else 1.0 if outcome.hit_1r else 0.0
        loss = 1.0 if not outcome.hit_1r else 0.0
        return win * reward - loss

    def walk_forward(self, outcomes: list[ZoneOutcome], train_months: int = 3, test_months: int = 1) -> BacktestReport:
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

    def monte_carlo(self, outcomes: list[ZoneOutcome], simulations: int = 200) -> BacktestReport:
        if not outcomes:
            return BacktestReport(trades=0, mean_ev=0.0, p5_ev=0.0, p50_ev=0.0, p95_ev=0.0)

        base = [self._trade_ev(o) for o in outcomes]
        runs: list[float] = []
        for _ in range(simulations):
            sample = base[:]
            random.shuffle(sample)
            noisy = [x + random.uniform(-0.1, 0.1) for x in sample]
            runs.append(sum(noisy) / len(noisy))

        s = sorted(runs)
        return BacktestReport(
            trades=len(base),
            mean_ev=sum(runs) / len(runs),
            p5_ev=s[int(0.05 * (len(s) - 1))],
            p50_ev=s[int(0.50 * (len(s) - 1))],
            p95_ev=s[int(0.95 * (len(s) - 1))],
        )
