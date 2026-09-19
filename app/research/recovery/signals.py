"""Streaming completed-bar confirmation; prefix-invariant and long/short symmetric."""
from collections import deque
from dataclasses import dataclass
from decimal import Decimal

from .models import Bar, Policy, Zone, dec


class BarHistory:
    def __init__(self):
        self.minutes = deque(maxlen=64)
        self.threes = deque(maxlen=16)
        self.last_end = None

    def reset(self):
        self.minutes.clear()
        self.threes.clear()

    def atr(self):
        if len(self.threes) < 15:
            return None
        bars = list(self.threes)[-15:]
        return sum((max(b.high - b.low, abs(b.high - a.close), abs(b.low - a.close))
                    for a, b in zip(bars, bars[1:])), dec(0)) / 14

    def push(self, bar):
        if self.last_end is not None and bar.end_ms <= self.last_end:
            raise ValueError("duplicate/out-of-order bar")
        gap = self.last_end is not None and bar.end_ms != self.last_end + 60000
        if gap:
            self.reset()
        self.last_end = bar.end_ms
        self.minutes.append(bar)
        three = None
        if bar.end_ms % 180000 == 0 and len(self.minutes) >= 3:
            a, b, c = list(self.minutes)[-3:]
            if b.end_ms - a.end_ms == c.end_ms - b.end_ms == 60000:
                three = Bar(c.end_ms, a.open, max(a.high, b.high, c.high),
                            min(a.low, b.low, c.low), c.close, c.received_ms)
                self.threes.append(three)
        return three, gap


@dataclass
class Confirmation:
    zone: Zone
    side: int
    buffer: Decimal
    started_ms: int
    state: str = "observing"
    observed_threes: int = 0
    recovery_ms: int | None = None
    retest: Bar | None = None
    confirmed_ms: int | None = None
    reason: str = "zone_touch"

    def advance(self, bar: Bar, three: Bar | None, policy: Policy):
        if self.state in ("failed", "expired", "confirmed", "consumed"):
            return self.state
        lower, upper = self.zone.bounds(self.side)
        low, high, close = bar.normalized(self.side)
        if self.recovery_ms is not None:
            if close < lower - self.buffer:
                self.state, self.reason = "failed", "recovery_lost"
                return self.state
            # At the exact deadline invalidation/expiry has priority over confirmation.
            if bar.end_ms >= self.recovery_ms + policy.confirmation_ms:
                self.state, self.reason = "expired", "retest_timeout"
                return self.state
            if self.retest is not None:
                previous_low = self.retest.normalized(self.side)[0]
                if bar.end_ms == self.retest.end_ms + 60000 and low >= previous_low - self.buffer and close > upper + self.buffer:
                    self.state, self.reason, self.confirmed_ms = "confirmed", "retest_held", bar.end_ms
                    return self.state
                self.retest = None
            if bar.end_ms > self.recovery_ms and lower - self.buffer <= low <= upper + self.buffer and close >= upper:
                self.retest, self.state = bar, "retest"
        elif three is not None and three.end_ms >= self.started_ms:
            self.observed_threes += 1
            low3, high3, close3 = three.normalized(self.side)
            if self.observed_threes >= policy.observation_bars:
                self.state, self.reason = "expired", "recovery_timeout"
            elif low3 <= upper and high3 >= lower and close3 > upper + self.buffer:
                self.state, self.recovery_ms, self.reason = "recovered", bar.end_ms, "three_minute_recovery"
        return self.state
