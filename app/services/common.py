from __future__ import annotations

import math
from statistics import mean, pstdev


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def safe_div(numerator: float, denominator: float, eps: float = 1e-9) -> float:
    return numerator / (denominator + eps)


def tanh(value: float) -> float:
    return math.tanh(value)


def winsorize(values: list[float], p_low: float = 0.01, p_high: float = 0.99) -> list[float]:
    if not values:
        return []
    sorted_vals = sorted(values)
    low_idx = int((len(sorted_vals) - 1) * p_low)
    high_idx = int((len(sorted_vals) - 1) * p_high)
    low_v = sorted_vals[low_idx]
    high_v = sorted_vals[high_idx]
    return [clamp(v, low_v, high_v) for v in values]


def zscore_latest(values: list[float], window: int = 50) -> float:
    if not values:
        return 0.0
    sample = values[-window:]
    mu = mean(sample)
    sigma = pstdev(sample)
    if sigma == 0:
        return 0.0
    return (sample[-1] - mu) / sigma


def ema_series(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    alpha = 2.0 / (period + 1)
    out: list[float] = [values[0]]
    for val in values[1:]:
        out.append(alpha * val + (1 - alpha) * out[-1])
    return out


def sma_latest(values: list[float], period: int) -> float:
    if not values:
        return 0.0
    sample = values[-period:]
    return sum(sample) / len(sample)
