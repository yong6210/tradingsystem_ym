"""Opt-in synthetic runner with parent-anchored incremental generation audits."""
import time
import uuid

from .continuous_generation_capture import (ContinuousGenerationEpoch, GenerationStore, MAX_GENERATIONS,
    MAX_UNITS, NS, implementation_hashes, validate_plan)
from .durable_capture_log import JournalError, file_hash
from .durable_sealed_pipeline import archive_factory
from .generation_archive_custody import register_policy
from .incremental_generation_pipeline import IncrementalGenerationArchives as GenerationArchives
from .queued_feed_fixture import QueuedTransport
from .reserved_feed_storage import ReservedStorageBudget
from .rolling_feed_epoch import collect_rolling_epoch


class ArchivedGenerationStore(GenerationStore):
    def __init__(self, budget, plan, *, pipeline, hook):
        self.pipeline = pipeline
        super().__init__(budget, plan, hook=hook)

    def end(self, terminal):
        result = super().end(terminal)
        self.pipeline.submit(self.index)
        return result


class ArchivedGenerationEpoch(ContinuousGenerationEpoch):
    def flush(self):
        self.store.pipeline.check()
        return super().flush()


async def run_synthetic_capture(output, *, duration_ns, rotation_ns=8*NS, seal_ns=NS//2,
        transport, max_bytes=128*1024**2, hook=lambda stage:None,
        _archive_factory=archive_factory, _job_seconds=15):
    if type(transport) is not QueuedTransport:
        raise JournalError('archived generation qualification requires synthetic queued transport')
    validate_plan(duration_ns,rotation_ns,seal_ns)
    run_id, epoch_id = uuid.uuid4().hex, uuid.uuid4().hex
    start = time.monotonic_ns()
    plan = dict(version=1,run_id=run_id,process_epoch=epoch_id,window_start_ns=start,
        window_end_ns=start+duration_ns,clock_domain='local-monotonic-synthetic',rotation_ns=rotation_ns,
        seal_ns=seal_ns,max_generations=MAX_GENERATIONS,max_units_per_generation=MAX_UNITS,
        public_requests=0,actual_orders=0,implementation_hashes=implementation_hashes())
    budget = ReservedStorageBudget.create(output,run_id=run_id,max_bytes=max_bytes,min_free_bytes=0)
    store = pipeline = None
    try:
        policy_hash = register_policy(budget)
        pipeline = GenerationArchives(budget,policy_hash=policy_hash,hook=hook,
                                      factory=_archive_factory,job_seconds=_job_seconds)
        store = ArchivedGenerationStore(budget,plan,pipeline=pipeline,hook=hook)
        pipeline.plan_hash = file_hash(budget.root/'generation-plan.json')
        epoch = ArchivedGenerationEpoch(store)
        result = await collect_rolling_epoch(epoch,transport,stop_at_ns=plan['window_end_ns'],audit_control=pipeline)
        # A worker can latch the shared budget before the coordinator's next
        # dispatch. Preserve its cause even if the collector stops first.
        try: pipeline.check()
        except Exception as exc:
            pipeline.fail(exc)
            if result['outcome'] == 'ORIGINAL_DEADLINE': result.update(outcome='FATAL_FAILURE',reason=pipeline.error)
        if result['outcome'] == 'ORIGINAL_DEADLINE' and not pipeline.failed.is_set():
            try: await pipeline.drain()
            except Exception as exc:
                pipeline.fail(exc)
                result.update(outcome='FATAL_FAILURE',reason=pipeline.error)
        else:
            pipeline.collecting = False
        await pipeline.close()
        result.update(generations=store.index+1,total_units=store.total_units,
            peak_units_per_generation=store.peak_units,handoffs=store.handoffs,max_handoff_ns=store.max_handoff_ns,
            audit=store.replay.summary(complete=result['outcome']=='ORIGINAL_DEADLINE'),
            storage=budget.snapshot(),pipeline=pipeline.snapshot(),
            handle=dict(plan_sha256=pipeline.plan_hash,policy_sha256=policy_hash),
            public_requests=0,private_requests=0,actual_orders=0,compression_integrated=True,incremental_generation_audit=True,
            live_resume_supported=False,full_day_ready=False)
        return result
    finally:
        try:
            if pipeline is not None: await pipeline.close()
        finally:
            if store is not None: store.close()
            budget.close()
