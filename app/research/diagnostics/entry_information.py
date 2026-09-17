"""E001 deterministic matching, fixed-horizon outcomes, and descriptive inference."""
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.research.foundation.contracts import CostAssumptions, MatchingDesign


@dataclass(frozen=True)
class Decision:
    minute: int
    side: int
    stratum: tuple[int, int, int] | None


def _bin(value: float, edges: tuple[float, ...], open_upper: bool) -> int | None:
    if not np.isfinite(value) or value < edges[0]:
        return None
    index = bisect_right(edges, value) - 1
    if not open_upper and index >= len(edges) - 1:
        return None
    return index


def build_decisions(minutes, bank, signal, matching: MatchingDesign) -> list[Decision]:
    """Match only on completed 4h data; never accept outcomes as inputs."""
    positions = np.flatnonzero(signal['decision'])
    higher = bank[240].reindex(minutes.index[positions], method='ffill')
    decisions = []
    for position, (timestamp, row) in zip(positions, higher.iterrows()):
        efficiency_bin = _bin(float(row.er), matching.efficiency_ratio_edges, False)
        volatility_bin = _bin(float(row.atr / row.c), matching.volatility_ratio_edges, True)
        stratum = None
        if efficiency_bin is not None and volatility_bin is not None:
            stratum = (timestamp.hour // matching.utc_bucket_hours, efficiency_bin, volatility_bin)
        decisions.append(Decision(int(position), int(signal['side'][position]), stratum))
    return decisions


class HistoricalMatcher:
    """One chronological PCG64 stream; candidates are past non-signal decisions."""
    def __init__(self, decisions: list[Decision], design: MatchingDesign, embargo_minutes: int):
        positions = [decision.minute for decision in decisions]
        if positions != sorted(set(positions)):
            raise ValueError('decisions must be ordered and unique')
        self.pools = defaultdict(list)
        for decision in decisions:
            if decision.side == 0 and decision.stratum is not None:
                self.pools[decision.stratum].append(decision.minute)
        self.lookback = design.lookback_days * 1440
        self.count = design.controls_per_signal
        self.embargo = embargo_minutes
        self.rng = np.random.Generator(np.random.PCG64(design.random_seed))

    def select(self, decision: Decision) -> tuple[list[int], list[int]]:
        pool = self.pools.get(decision.stratum, [])
        lower = bisect_left(pool, decision.minute - self.lookback)
        upper = bisect_right(pool, decision.minute - self.embargo)
        candidates = pool[lower:upper]
        if len(candidates) < self.count:
            return candidates, []
        selected = sorted(int(value) for value in self.rng.choice(candidates, self.count, replace=False))
        return candidates, selected


class PriceResponses:
    """Measure unit-price responses; this class has no signal or matching logic."""
    def __init__(self, minutes: pd.DataFrame, costs: CostAssumptions):
        self.opens = minutes.o.to_numpy()
        self.highs = minutes.h.to_numpy()
        self.lows = minutes.l.to_numpy()
        self.costs = costs

    def measure(self, decision_minute: int, side: int, delay: int, horizon: int,
                end_exclusive: int) -> dict[str, float]:
        if side not in (-1, 1) or delay < 1 or horizon < 1 or decision_minute < 0:
            raise ValueError('invalid response request')
        entry_index = decision_minute + delay
        exit_index = entry_index + horizon
        if exit_index >= min(end_exclusive, len(self.opens)):
            raise ValueError('incomplete outcome')
        entry, exit_price = self.opens[entry_index], self.opens[exit_index]
        high = self.highs[entry_index:exit_index].max()
        low = self.lows[entry_index:exit_index].min()
        slippage = self.costs.slippage_bps / 10000
        entry_fill = entry * (1 + side * slippage)
        exit_fill = exit_price * (1 - side * slippage)
        fee = (entry_fill + exit_fill) * self.costs.taker_fee_bps / 10000
        # Normalize both gross and hypothetical net PnL by the same raw entry.
        net = (side * (exit_fill - entry_fill) - fee) / entry
        return {
            'gross_bps': float(side * (exit_price / entry - 1) * 10000),
            'market_net_bps': float(net * 10000),
            'favorable_bps': float(max(0., side * ((high if side == 1 else low) / entry - 1)) * 10000),
            'adverse_bps': float(min(0., side * ((low if side == 1 else high) / entry - 1)) * 10000),
        }


def descriptive(values: list[float]) -> dict:
    if not values:
        return {'count': 0, 'mean_bps': None, 'median_bps': None, 'p05_bps': None, 'p95_bps': None}
    return {'count': len(values), 'mean_bps': float(np.mean(values)),
            'median_bps': float(np.median(values)), 'p05_bps': float(np.quantile(values, .05)),
            'p95_bps': float(np.quantile(values, .95))}


def moving_block_interval(rows: list[dict], start, end, block_days: int,
                          repetitions: int, seed: int) -> dict:
    """Resample contiguous calendar days, preserving event-weighted means.

    Noncircular blocks, empty days included, no year-boundary crossing. Uses a
    separate RNG from matching. Control reuse means this is exploratory only.
    """
    days = pd.date_range(start, end, freq='D', inclusive='left')
    if len(days) < block_days or not rows:
        return {'status': 'insufficient', 'interval_bps': None}
    daily_sum = np.zeros(len(days))
    daily_count = np.zeros(len(days))
    for row in rows:
        index = (pd.Timestamp(row['decision_time']).normalize() - days[0]).days
        daily_sum[index] += row['excess_bps']
        daily_count[index] += 1
    rng = np.random.Generator(np.random.PCG64(seed))
    blocks = int(np.ceil(len(days) / block_days))
    starts = rng.integers(0, len(days) - block_days + 1, size=(repetitions, blocks))
    indices = (starts[:, :, None] + np.arange(block_days)).reshape(repetitions, -1)[:, :len(days)]
    denominators = daily_count[indices].sum(axis=1)
    sums = daily_sum[indices].sum(axis=1)
    sampled = sums[denominators > 0] / denominators[denominators > 0]
    if not len(sampled):
        return {'status': 'insufficient', 'interval_bps': None}
    return {'status': 'exploratory', 'interval_bps': [float(x) for x in np.quantile(sampled, [.025, .975])],
            'event_days': int((daily_count > 0).sum()), 'calendar_days': len(days),
            'valid_repetitions': len(sampled), 'selection_adjusted': False}


def control_reuse(matches: list[dict]) -> dict:
    counts = Counter(control for match in matches for control in match['selected'])
    total = sum(counts.values())
    return {'assignments': total, 'unique_controls': len(counts),
            'maximum_reuse': max(counts.values(), default=0),
            'concentration_equivalent_count': total * total / sum(n * n for n in counts.values()) if total else 0,
            'note': 'Concentration measure, not statistically independent sample size.'}
