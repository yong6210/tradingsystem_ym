from __future__ import annotations

from collections import defaultdict, deque
from typing import Any


class ExecutionLaneTracker:
    def __init__(self, *, window: int = 20):
        self.window = max(int(window or 20), 1)
        self.base_r: deque[float] = deque(maxlen=self.window)
        self.variant_r: deque[float] = deque(maxlen=self.window)
        self.counts: dict[str, defaultdict[str, int]] = {
            "base": defaultdict(int),
            "variant": defaultdict(int),
        }

    @staticmethod
    def _lane_key(is_variant: bool) -> str:
        return "variant" if bool(is_variant) else "base"

    def record_intent(self, *, is_variant: bool) -> None:
        self.counts[self._lane_key(is_variant)]["intent"] += 1

    def record_submitted(self, *, is_variant: bool) -> None:
        self.counts[self._lane_key(is_variant)]["submitted"] += 1

    def record_filled(self, *, is_variant: bool) -> None:
        self.counts[self._lane_key(is_variant)]["filled"] += 1

    def record_closed(self, *, is_variant: bool, realized_r: float | None) -> None:
        lane = self._lane_key(is_variant)
        self.counts[lane]["closed"] += 1
        if realized_r is None:
            return
        values = self.variant_r if lane == "variant" else self.base_r
        values.append(float(realized_r))

    @staticmethod
    def _ev(values: deque[float]) -> float:
        return (sum(values) / len(values)) if values else 0.0

    @staticmethod
    def _dd(values: deque[float]) -> float:
        eq = 0.0
        peak = 0.0
        max_dd = 0.0
        for item in values:
            eq += float(item)
            peak = max(peak, eq)
            max_dd = max(max_dd, peak - eq)
        return max_dd

    def _rates_for_lane(self, lane: str) -> dict[str, float]:
        counts = self.counts[lane]
        return {
            "submitted_rate": counts["submitted"] / max(1, counts["intent"]),
            "filled_rate": counts["filled"] / max(1, counts["submitted"]),
            "closed_rate": counts["closed"] / max(1, counts["filled"]),
        }

    def _counts_for_lane(self, lane: str) -> dict[str, int]:
        counts = self.counts[lane]
        return {
            "intent": int(counts.get("intent", 0) or 0),
            "submitted": int(counts.get("submitted", 0) or 0),
            "filled": int(counts.get("filled", 0) or 0),
            "closed": int(counts.get("closed", 0) or 0),
        }

    def snapshot(self) -> dict[str, Any]:
        return {
            "window": self.window,
            "counts": {
                "base": self._counts_for_lane("base"),
                "variant": self._counts_for_lane("variant"),
            },
            "ev": {
                "base": self._ev(self.base_r),
                "variant": self._ev(self.variant_r),
            },
            "dd": {
                "base": self._dd(self.base_r),
                "variant": self._dd(self.variant_r),
            },
            "downstream": {
                "base": self._rates_for_lane("base"),
                "variant": self._rates_for_lane("variant"),
            },
        }


_TRACKER: ExecutionLaneTracker | None = None


def get_execution_lane_tracker(*, window: int = 20) -> ExecutionLaneTracker:
    global _TRACKER
    target_window = max(int(window or 20), 1)
    if _TRACKER is None or _TRACKER.window != target_window:
        _TRACKER = ExecutionLaneTracker(window=target_window)
    return _TRACKER


def reset_execution_lane_tracker(*, window: int | None = None) -> ExecutionLaneTracker:
    global _TRACKER
    target_window = _TRACKER.window if _TRACKER is not None and window is None else max(int(window or 20), 1)
    _TRACKER = ExecutionLaneTracker(window=target_window)
    return _TRACKER
