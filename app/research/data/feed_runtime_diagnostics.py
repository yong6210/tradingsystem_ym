"""Bounded synchronous-phase measurements and fail-closed storage stall guards.

Measurements identify future local stalls; they cannot reconstruct an old call
stack or prove a 24-hour capacity envelope from a short sample.
"""
from contextlib import contextmanager
import time

from .bounded_feed_collector import FeedEpoch as FrozenFeedEpoch
from .durable_capture_log import integer


class SynchronousStallError(RuntimeError):
    pass


class PhaseStats:
    BOUNDS_NS = (1_000_000, 10_000_000, 50_000_000, 100_000_000, 250_000_000, 500_000_000, 1_000_000_000)
    NAMES = ('raw_append', 'raw_commit_and_process', 'audit_write_and_sync', 'flush_total')

    def __init__(self, *, max_block_ns=500_000_000):
        self.max_block_ns = integer(max_block_ns, 1)
        self.phases, self.slow_samples = {}, []

    def record(self, name, start, elapsed, cpu, failed):
        if name not in self.NAMES:
            raise ValueError('bounded phase name required')
        for value in (start, elapsed, cpu):
            integer(value)
        row = self.phases.setdefault(name, dict(calls=0, failures=0, wall_ns=0, cpu_ns=0,
                max_wall_ns=0, max_cpu_ns=0, histogram=[0]*(len(self.BOUNDS_NS)+1)))
        row['calls'] += 1
        row['failures'] += int(failed)
        row['wall_ns'] += elapsed
        row['cpu_ns'] += cpu
        row['max_wall_ns'] = max(row['max_wall_ns'], elapsed)
        row['max_cpu_ns'] = max(row['max_cpu_ns'], cpu)
        bucket = next((i for i,bound in enumerate(self.BOUNDS_NS) if elapsed <= bound), len(self.BOUNDS_NS))
        row['histogram'][bucket] += 1
        if elapsed >= 50_000_000:
            self.slow_samples.append(dict(phase=name, start_ns=start, elapsed_ns=elapsed, cpu_ns=cpu, failed=bool(failed)))
            del self.slow_samples[:-16]

    @contextmanager
    def measure(self, name):
        if name not in self.NAMES:
            raise ValueError('unknown phase')
        began, cpu0 = time.monotonic_ns(), time.process_time_ns()
        failed = True
        try:
            yield
            failed = False
        finally:
            elapsed, cpu = time.monotonic_ns()-began, time.process_time_ns()-cpu0
            self.record(name, began, elapsed, cpu, failed or elapsed > self.max_block_ns)
            if not failed and elapsed > self.max_block_ns:
                raise SynchronousStallError(f'{name} blocked {elapsed}ns; limit {self.max_block_ns}ns')

    def summary(self):
        return dict(phases=self.phases, histogram_upper_bounds_ns=self.BOUNDS_NS,
                    last_slow_samples=self.slow_samples, max_allowed_block_ns=self.max_block_ns)


class GuardedFeedEpoch(FrozenFeedEpoch):
    """New version of the bounded epoch; frozen v1 evidence remains reproducible."""
    def __init__(self, *args, **kwargs):
        self.metrics = PhaseStats()
        self.pending_peak = self.attempted_pending_peak = 0
        self.sampled_book_levels_peak = self.sampled_book_buffer_peak = 0
        super().__init__(*args, **kwargs)

    def emit(self, kind, channel, **fields):
        self.attempted_pending_peak = max(self.attempted_pending_peak, len(self.bridge.pending)+1)
        try:
            with self.metrics.measure('raw_append'):
                super().emit(kind, channel, **fields)
            self.pending_peak = max(self.pending_peak, len(self.bridge.pending))
        except BaseException:
            self.failed = True
            raise

    def flush(self):
        try:
            with self.metrics.measure('flush_total'):
                oldest = min((row['received_ns'] for _,row in self.bridge.pending), default=None)
                if oldest is not None and time.monotonic_ns()-oldest > 1_000_000_000:
                    raise SynchronousStallError('oldest pending raw record exceeded 1-second commit interval')
                with self.metrics.measure('raw_commit_and_process'):
                    batch = self.bridge.flush()
                if batch is None:
                    return
                if oldest is not None and batch['committed_ns']-oldest > 1_000_000_000:
                    raise SynchronousStallError('raw commit interval exceeded during storage')
                book = self.bridge.processor.book
                self.sampled_book_levels_peak = max(self.sampled_book_levels_peak, len(book.bids)+len(book.asks))
                self.sampled_book_buffer_peak = max(self.sampled_book_buffer_peak, len(getattr(book, 'buffer', [])))
                with self.metrics.measure('audit_write_and_sync'):
                    persisted = self.audit.append(batch)
                if self.bridge.processor.errors:
                    raise ValueError('processor failure: '+','.join(self.bridge.processor.errors))
            # Acknowledge only after individual and combined blocking guards.
            self.max_audit_sync_ns = max(self.max_audit_sync_ns, persisted-batch['observation']['published_ns'])
            self.last_audited_sequence = batch['last_sequence']
            self.batches += 1
            self.eligible_points += int(batch['observation']['eligible'])
            self.bridge.batches.clear()
        except BaseException:
            self.failed = True
            raise

    def diagnostics(self):
        return self.metrics.summary() | dict(pending_peak=self.pending_peak,
            attempted_pending_peak=self.attempted_pending_peak,
            sampled_book_levels_peak=self.sampled_book_levels_peak,
            sampled_book_buffer_peak=self.sampled_book_buffer_peak,
            retained_bridge_batches=len(self.bridge.batches))


def capacity_projection(*, raw_bytes, audit_bytes, calendar_ns, free_bytes,
                        reserve_bytes=16*1024**3, raw_budget_bytes=64*1024**3, audit_cap_bytes=32*1024**2):
    """Explicit constant-rate scenarios; observed calendar includes all gaps.

Never labels a short extrapolation as forecast, sufficient storage, or an
operational acceptance. Metadata, growth, peak and allocator effects are extra.
"""
    for value in (raw_bytes,audit_bytes,free_bytes,reserve_bytes):
        integer(value)
    for value in (calendar_ns,raw_budget_bytes,audit_cap_bytes):
        integer(value,1)
    day_ns = 86400*1_000_000_000
    def ceildiv(a,b): return (a+b-1)//b
    available = max(0,free_bytes-reserve_bytes)
    scenarios=[]
    for multiplier in (1,2,5):
        raw=ceildiv(raw_bytes*multiplier*day_ns,calendar_ns)
        audit=ceildiv(audit_bytes*multiplier*day_ns,calendar_ns)
        scenarios.append(dict(rate_multiplier=multiplier,raw_day_bytes=raw,audit_day_bytes=audit,
            raw_and_audit_day_bytes=raw+audit,raw_budget_exceeded=raw>raw_budget_bytes,
            single_audit_cap_exceeded=audit>audit_cap_bytes,free_above_reserve_exceeded=raw+audit>available))
    return dict(status='DIAGNOSTIC_NOT_CAPACITY_CERTIFICATION',calendar_ns=calendar_ns,
        raw_bytes=raw_bytes,audit_bytes=audit_bytes,free_bytes=free_bytes,reserve_bytes=reserve_bytes,
        audit_cap_bytes=audit_cap_bytes,available_above_reserve_bytes=available,scenarios=scenarios,
        single_audit_cap_ns_at_observed_rate=None if audit_bytes==0 else audit_cap_bytes*calendar_ns//audit_bytes,
        metadata_and_growth_included=False,full_day_ready=False)
