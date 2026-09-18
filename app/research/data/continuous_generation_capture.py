"""Finite same-session storage generations; synthetic qualification only.

Physical v1 journals keep their local sequences. Raw payloads contain an explicit
global hash chain consumed by the unchanged live bridge. This is a new format;
old readers are neither patched nor asked to treat a local reset as continuity.
No live resume, compression, retirement, or long-run capacity claim is made.
"""
import time
import uuid
from pathlib import Path

from .durable_capture_log import (CommitReceipt, JournalError, ZERO, encoded,
                                 file_hash, integer, sync_directory)
from .durable_market_feed import DurableFeedBridge
from .feed_audit_state_codec import pack
from .feed_runtime_diagnostics import GuardedFeedEpoch, PhaseStats, SynchronousStallError
from .generation_feed_replay import GenerationReplay, sha
from .rolling_feed_epoch import collect_rolling_epoch
from .sealed_segment_handoff import SealedJournal
from .shared_feed_storage import SharedStorageBudget

NS = 10**9
MAX_GENERATIONS = 16
MAX_UNITS = 62
MAX_METADATA = 8*1024**2


def implementation_hashes():
    return {p.name:file_hash(p) for p in sorted(Path(__file__).parent.glob('*.py'))}


def validate_plan(duration_ns, rotation_ns, seal_ns):
    for value in (duration_ns, rotation_ns, seal_ns):
        integer(value, 1)
    if duration_ns > 120*NS or not NS <= rotation_ns <= 30*NS or not NS//2 <= seal_ns <= 2*NS:
        raise JournalError('unqualified duration or generation cadence')
    if (duration_ns+rotation_ns-1)//rotation_ns > MAX_GENERATIONS:
        raise JournalError('generation count bound')
    if (min(duration_ns, rotation_ns)+seal_ns-1)//seal_ns+2 > MAX_UNITS:
        raise JournalError('per-generation unit bound')


class LogicalRawJournal:
    """Global receipt facade; each physical generation embeds full logical rows."""
    def __init__(self, owner):
        self.owner = owner
        self.sequence = 0
        self.record_hash = ZERO
        self.epoch = owner.plan['process_epoch']
        self.pending = []
        self.total_bytes = 0

    def append(self, payload):
        if len(self.pending) >= 2048:
            raise JournalError('logical pending bound')
        body = dict(sequence=self.sequence+1, epoch=self.epoch,
                    previous_record_sha256=self.record_hash, payload=payload)
        row = body | dict(sha256=sha(body))
        self.owner.raw.append(row)
        self.sequence, self.record_hash = row['sequence'], row['sha256']
        self.total_bytes += len(encoded(row))
        self.pending.append(row)
        return self.sequence

    def commit(self):
        receipt = self.owner.raw.commit()
        return CommitReceipt(self.sequence, self.record_hash, receipt.available_monotonic_ns)

    def close(self):
        self.owner.close()


class LogicalAudit:
    def __init__(self, owner):
        self.owner = owner
        self.bytes = self.lines = 0

    def append(self, batch):
        owner = self.owner
        owner.replay.accept(owner.logical.pending, batch)
        # Both replay implementations must agree on all processor state, not
        # just the published best bid/ask. Neither is restored at handoff.
        if pack(owner.bridge.processor, owner.replay.reducer) != owner.replay.seed()['replay']:
            raise JournalError('live and independently replayed processor state differ')
        owner.audit.append(batch)
        receipt = owner.audit.commit()
        owner.logical.pending.clear()
        self.bytes += len(encoded(batch))
        self.lines += 1
        return receipt.available_monotonic_ns

    def close(self):
        self.owner.close()


class GenerationStore:
    def __init__(self, budget, plan, *, hook=lambda stage: None):
        self.budget, self.plan, self.hook = budget, plan, hook
        self.scope = {k:plan[k] for k in ('window_start_ns', 'window_end_ns', 'clock_domain')}
        self.replay = GenerationReplay(self.scope)
        self.raw = self.audit = None
        self.closed = self.failed = False
        self.index = 0
        self.units = self.total_units = self.peak_units = 0
        self.unit_hash = ZERO
        self.last_sealed = 0
        self.last_seal_ns = time.monotonic_ns()
        self.generation_started_ns = self.last_seal_ns
        self.max_handoff_ns = 0
        self.handoffs = 0
        self.logical = LogicalRawJournal(self)
        self.bridge = None
        self.budget.atomic_json(budget.root/'generation-plan.json', plan)
        try:
            self._prepare(0, ZERO)
        except BaseException:
            self.close()
            raise

    @property
    def directory(self):
        return self.budget.root/f'generation-{self.index:04d}'

    def _write(self, path, value, stage):
        if len(encoded(value)) > MAX_METADATA or path.exists():
            raise JournalError('generation metadata bound or immutable path exists')
        self.budget.atomic_json(path, value, lambda point: self.hook(stage+':'+point))

    def _prepare(self, index, previous_end_hash):
        directory = self.budget.root/f'generation-{index:04d}'
        directory.mkdir()
        sync_directory(directory.parent)
        raw = audit = None
        try:
            raw = SealedJournal.create(directory/'raw', budget=self.budget,
                run_id=self.plan['run_id'], rotation_bytes=8*1024**2, max_record_bytes=4*1024**2)
            audit = SealedJournal.create(directory/'audit', budget=self.budget,
                run_id=self.plan['run_id'], rotation_bytes=8*1024**2, max_record_bytes=4*1024**2)
            seed = self.replay.seed()
            self._write(directory/'seed.json', seed, 'seed')
            start = dict(version=1, index=index, plan_sha256=sha(self.plan), previous_end_sha256=previous_end_hash,
                seed_sha256=file_hash(directory/'seed.json'), raw_metadata_sha256=file_hash(raw.directory/'metadata.json'),
                audit_metadata_sha256=file_hash(audit.directory/'metadata.json'),
                global_sequence=self.logical.sequence, global_raw_sha256=self.logical.record_hash,
                global_audit_batches=self.replay.batches, global_audit_sha256=self.replay.audit_hash)
            self._write(directory/'start.json', start, 'start')
            if index:
                previous = self.directory
                link = dict(version=1, previous_end_sha256=previous_end_hash,
                            next_index=index, next_start_sha256=file_hash(directory/'start.json'))
                self._write(previous/'handoff.json', link, 'handoff')
            self.raw, self.audit = raw, audit
            self.index = index
        except BaseException:
            if raw is not None: raw.close()
            if audit is not None: audit.close()
            raise

    def seal(self):
        if self.logical.sequence == self.last_sealed:
            return
        if self.logical.pending or self.bridge.pending or self.replay.processor.sequence != self.logical.sequence:
            raise JournalError('seal requires a fully audited global fence')
        if self.units >= MAX_UNITS:
            raise JournalError('generation unit bound exceeded')
        raw, audit = self.raw.seal(), self.audit.seal()
        if not raw or len(raw) > 16 or len(audit) != 1:
            raise JournalError('generation sealed unit bounds')
        row = dict(version=1, index=self.units, previous_unit_sha256=self.unit_hash,
                   raw=[t.certificate.decode() for t in raw], audit=[t.certificate.decode() for t in audit],
                   global_sequence=self.logical.sequence, global_raw_sha256=self.logical.record_hash,
                   global_audit_batches=self.replay.batches, global_audit_sha256=self.replay.audit_hash)
        self._write(self.directory/f'unit-{self.units:04d}.json', row, 'unit')
        self.unit_hash = sha(row)
        self.units += 1
        self.total_units += 1
        self.peak_units = max(self.peak_units, self.units)
        self.last_sealed = self.logical.sequence
        self.last_seal_ns = time.monotonic_ns()

    def end(self, terminal):
        self.seal()
        row = dict(version=1, start_sha256=file_hash(self.directory/'start.json'),
            terminal=terminal, global_sequence=self.logical.sequence, global_raw_sha256=self.logical.record_hash,
            global_audit_batches=self.replay.batches, global_audit_sha256=self.replay.audit_hash,
            seed_sha256=sha(self.replay.seed()), units=self.units, last_unit_sha256=self.unit_hash,
            raw_checkpoint_sha256=file_hash(self.raw.directory/'checkpoint.json'),
            audit_checkpoint_sha256=file_hash(self.audit.directory/'checkpoint.json'))
        self._write(self.directory/'end.json', row, 'end')
        self.raw.close()
        self.audit.close()
        return sha(row)

    def rotate(self):
        if self.index+1 >= MAX_GENERATIONS:
            raise JournalError('generation count bound exceeded')
        began = time.monotonic_ns()
        end_hash = self.end(False)
        self._prepare(self.index+1, end_hash)
        self.units = 0
        self.unit_hash = ZERO
        self.generation_started_ns = time.monotonic_ns()
        self.max_handoff_ns = max(self.max_handoff_ns, self.generation_started_ns-began)
        self.handoffs += 1
        self.hook('handoff:acknowledged')
        if self.max_handoff_ns > 500_000_000:
            raise SynchronousStallError('generation handoff exceeded 500ms')

    def close(self):
        if not self.closed:
            if self.raw is not None: self.raw.close()
            if self.audit is not None: self.audit.close()
            self.closed = True


class ContinuousGenerationEpoch(GuardedFeedEpoch):
    def __init__(self, store):
        self.store = store
        self.plan, self.directory = store.plan, store.budget.root
        self.metrics = PhaseStats()
        self.pending_peak = self.attempted_pending_peak = 0
        self.sampled_book_levels_peak = self.sampled_book_buffer_peak = 0
        self.sessions = {}
        self.failed = self.closing = False
        self.batches = self.eligible_points = self.discarded_after_failure = 0
        self.max_audit_sync_ns = self.last_audited_sequence = self.latest_received_utc_ns = 0
        self.journal = store.logical
        self.bridge = DurableFeedBridge(self.journal)
        store.bridge = self.bridge
        self.audit = LogicalAudit(store)
        self.emit('RUN_WINDOW', 'system', started_ns=self.plan['window_start_ns'], deadline_ns=self.plan['window_end_ns'])
        self.watchdog(time.monotonic_ns())
        self.flush()

    def flush(self):
        began = time.monotonic_ns()
        try:
            super().flush()
            now = time.monotonic_ns()
            if now-self.store.last_seal_ns >= self.plan['seal_ns']:
                self.store.seal()
            if (not self.closing and now < self.plan['window_end_ns'] and
                    now-self.store.generation_started_ns >= self.plan['rotation_ns']):
                self.store.rotate()
            if time.monotonic_ns()-began > self.metrics.max_block_ns:
                raise SynchronousStallError('flush plus generation work exceeded 500ms')
        except BaseException:
            self.failed = True
            raise

    def close(self):
        try:
            if not self.store.closed and not self.failed and not self.bridge.failed and not self.store.budget.failed:
                self.store.end(True)
        finally:
            self.store.close()


async def run_synthetic_capture(output, *, duration_ns, rotation_ns=8*NS, seal_ns=NS//2,
                                transport, max_bytes=128*1024**2, hook=lambda stage: None):
    """No default transport: qualification callers must supply synthetic input."""
    from .queued_feed_fixture import QueuedTransport
    if type(transport) is not QueuedTransport:
        raise JournalError('this generation qualification accepts only the synthetic queued transport')
    validate_plan(duration_ns, rotation_ns, seal_ns)
    run_id, epoch_id = uuid.uuid4().hex, uuid.uuid4().hex
    start = time.monotonic_ns()
    plan = dict(version=1, run_id=run_id, process_epoch=epoch_id, window_start_ns=start,
                window_end_ns=start+duration_ns, clock_domain='local-monotonic-synthetic',
                rotation_ns=rotation_ns, seal_ns=seal_ns, max_generations=MAX_GENERATIONS,
                max_units_per_generation=MAX_UNITS, public_requests=0, actual_orders=0,
                implementation_hashes=implementation_hashes())
    budget = SharedStorageBudget.create(output, run_id=run_id, max_bytes=max_bytes, min_free_bytes=0)
    store = None
    try:
        store = GenerationStore(budget, plan, hook=hook)
        epoch = ContinuousGenerationEpoch(store)
        result = await collect_rolling_epoch(epoch, transport, stop_at_ns=plan['window_end_ns'])
        result.update(generations=store.index+1, total_units=store.total_units,
            peak_units_per_generation=store.peak_units, handoffs=store.handoffs,
            max_handoff_ns=store.max_handoff_ns, audit=store.replay.summary(complete=result['outcome']=='ORIGINAL_DEADLINE'),
            storage=budget.snapshot(), public_requests=0, private_requests=0, actual_orders=0,
            compression_integrated=False, live_resume_supported=False, full_day_ready=False)
        return result
    finally:
        if store is not None: store.close()
        budget.close()
