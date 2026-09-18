"""Bounded interval reduction of verified chronological observations.

Retains merged intervals and one previous lease, never every observation.
Fragmentation beyond a fixed interval limit fails closed instead of truncating.
"""
from .durable_capture_log import integer
from ..foundation.forward_data_contract import REQUIREMENTS


class IntervalLimitError(RuntimeError):
    pass


class CompactIntervals:
    def __init__(self, start_ns, end_ns, *, max_intervals=100_000):
        self.start, self.end = integer(start_ns), integer(end_ns, 1)
        if self.end <= self.start:
            raise ValueError('nonempty window required')
        self.limit = integer(max_intervals, 1)
        self.intervals = {name: [] for name in REQUIREMENTS}
        self.exclusions = []
        self.previous = self.first = None
        self.points = self.count = self.peak = 0
        self.failed = False

    def _union(self, target, left, right):
        left, right = max(self.start, left), min(self.end, right)
        if left >= right:
            return
        # New right endpoints cannot precede existing endpoints. A lifecycle
        # receipt can nevertheless reach backwards across previous intervals.
        if target and right < target[-1][1]:
            raise ValueError('interval right endpoint regressed')
        while target and target[-1][1] >= left:
            left = min(left, target.pop()[0])
            self.count -= 1
        if self.count >= self.limit:
            raise IntervalLimitError('merged interval budget exceeded')
        target.append((left, right))
        self.count += 1
        self.peak = max(self.peak, self.count)

    def add(self, published_ns, expiries, exclusions=()):
        if self.failed:
            raise IntervalLimitError('interval reducer failed')
        try:
            published = integer(published_ns)
            if self.previous is not None and published < self.previous[0]:
                raise ValueError('publication clock regressed')
            if not set(expiries).issubset(REQUIREMENTS):
                raise ValueError('unknown eligibility requirement')
            for value in expiries.values():
                integer(value)
            if self.previous is not None:
                left, old = self.previous
                for name, until in old.items():
                    self._union(self.intervals[name], left, min(published, until))
            for left, right in exclusions:
                integer(left)
                integer(right)
                if right != published:
                    raise ValueError('exclusion must end at this publication')
                self._union(self.exclusions, left, right)
            if self.first is None:
                self.first = published
            self.previous = (published, dict(expiries))
            self.points += 1
        except BaseException:
            self.failed = True
            raise

    def finish(self):
        if self.failed:
            raise IntervalLimitError('interval reducer failed')
        result, output_count = {}, 0
        def append(rows, left, right):
            nonlocal output_count
            if output_count >= self.limit:
                self.failed = True
                raise IntervalLimitError('final interval budget exceeded')
            rows.append([left, right])
            output_count += 1

        # Both inputs are already merged and ordered. Each exclusion is scanned
        # once per requirement, including cuts reaching far into the past.
        for name, intervals in self.intervals.items():
            rows, index = [], 0
            for left, right in intervals:
                cursor = left
                while index < len(self.exclusions) and self.exclusions[index][1] <= left:
                    index += 1
                scan = index
                while scan < len(self.exclusions) and self.exclusions[scan][0] < right:
                    lo, hi = self.exclusions[scan]
                    if lo > cursor:
                        append(rows, cursor, min(lo, right))
                    cursor = max(cursor, hi)
                    if cursor >= right:
                        break
                    scan += 1
                index = scan
                if cursor < right:
                    append(rows, cursor, right)
            result[name] = rows
        return result, list(self.exclusions)
