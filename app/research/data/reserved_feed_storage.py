"""Single-owner storage budget including not-yet-written archive reservations.

Reservations are in-memory admission claims. Only the parent writes; after a
process restart there is no child output to discover outside this inventory.
Spending contexts must never yield or be entered from another thread.
"""
from contextlib import contextmanager

from .durable_capture_log import JournalError, integer
from .shared_feed_storage import SharedStorageBudget


class ReservedStorageBudget(SharedStorageBudget):
    def __init__(self, *args):
        self.reservations = {}
        self.spending_key = None
        self.remaining = 0
        self.peak_reserved = self.peak_effective = 0
        super().__init__(*args)

    def _totals(self):
        reserved = sum(self.reservations.values())+self.remaining
        self.peak_reserved = max(self.peak_reserved, reserved)
        self.peak_effective = max(self.peak_effective, self.used+reserved)
        return reserved

    def check(self, growth):
        integer(growth)
        reserved = self._totals()
        if self.spending_key is not None:
            if growth > self.remaining:
                raise JournalError('archive reservation exhausted')
            # During synchronous spending, growth is already part of remaining.
            super().check(reserved)
        else:
            super().check(growth+reserved)

    def reserve(self, key, amount):
        with self.mutation():
            integer(amount, 1)
            if type(key) is not str or not key or key in self.reservations or self.spending_key is not None:
                raise JournalError('invalid or repeated storage reservation')
            if len(self.reservations) >= 2:
                raise JournalError('storage reservation count bound')
            self.check(amount)
            self.reservations[key] = amount
            self._totals()

    def release(self, key):
        # Bookkeeping is allowed after failure, but cannot clear the failed latch.
        if key == self.spending_key:
            raise JournalError('cannot release active spending reservation')
        return self.reservations.pop(key, 0)

    @contextmanager
    def spend(self, key):
        with self.mutation():
            if self.spending_key is not None or key not in self.reservations:
                raise JournalError('exclusive existing reservation required')
            self.spending_key = key
            self.remaining = self.reservations.pop(key)
            try:
                yield
            finally:
                self.spending_key, self.remaining = None, 0

    def append(self, stream, data):
        before = self.used
        try:
            return super().append(stream, data)
        finally:
            if self.spending_key is not None:
                self.remaining -= self.used-before
            self._totals()

    def snapshot(self):
        reserved = self._totals()
        return super().snapshot() | dict(reserved_bytes=reserved,
            effective_used_bytes=self.used+reserved, peak_reserved_bytes=self.peak_reserved,
            peak_effective_bytes=self.peak_effective, pending_reservations=len(self.reservations))
