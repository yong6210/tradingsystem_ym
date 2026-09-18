"""Versioned supervisor for opt-in closed-capture retention and restart.

No active-journal retirement, daemon or longer collection window. Frozen v1
supervisor events and raw retirement remain unchanged. A separate externally
anchored registration routes an ended attempt through gzip-only recovery.
"""
from contextlib import ExitStack
import asyncio
from pathlib import Path
import re

from . import closed_capture_retirement as retirement
from .durable_capture_log import JournalError, ZERO, decoded, digest, encoded, file_hash, integer, keys, lock_directory, sync_directory
from .durable_sealed_pipeline import DurableSealedPipeline
from .interruptible_feed_epoch import collect_epoch
from .pipelined_feed_collector import PipelinedFeedEpoch
from .restartable_feed_capture import RestartableFeedCapture, DeadlineTransport, NS, source_hashes
from .retirement_admission import forecast_retirement, prepare_if_economic, _replay_size
from .scoped_feed_budget import ScopedFeedBudget
from .sealed_feed_pipeline import PipelineLimits
from .sealed_segment_handoff import sha
import time


class RetentionFeedCapture(RestartableFeedCapture):
    def __init__(self, budget, log, *, hook=lambda stage: None):
        super().__init__(budget, log, hook=hook)
        self.retention_anchors = {}
        self.retention_status = []
        self.mode_hash = None

    def _mode(self):
        return dict(version=1, root=str(self.budget.root), run_id=self.plan['run_id'],
                    mode='OPT_IN_CLOSED_CAPTURE_RETENTION_WITH_EXTERNAL_REGISTRATION',
                    implementation_sha256=file_hash(Path(__file__)))

    @classmethod
    def create(cls, root, **kwargs):
        obj = super().create(root, **kwargs)
        try:
            obj.budget.atomic_json(obj.budget.root/'retention-mode.json', obj._mode())
            obj.mode_hash = file_hash(obj.budget.root/'retention-mode.json')
            return obj
        except BaseException:
            obj.close()
            raise

    @classmethod
    def resume(cls, root, *, handle, hook=lambda stage: None):
        keys(handle, 'storage supervisor_anchor retention_mode_sha256 retention_anchors')
        # Base resume performs no network or raw-dependent recovery: it checks
        # clock/source contracts and pinned result files only. Do not weaken it.
        base = RestartableFeedCapture.resume(root,
            handle={k: handle[k] for k in ('storage', 'supervisor_anchor')}, hook=hook)
        obj = cls(base.budget, base.log, hook=hook)
        try:
            obj.mode_hash = digest(handle['retention_mode_sha256'])
            obj.retention_anchors = decoded(encoded(handle['retention_anchors']))
            obj._check_mode()
            obj._results()  # Validate archive custody before returning a usable supervisor.
            return obj
        except BaseException:
            obj.close()
            raise

    def _check_mode(self):
        path = self.budget.path(self.budget.root/'retention-mode.json')
        if (not path.is_file() or path.stat().st_size > 4096 or
                file_hash(path) != self.mode_hash or decoded(path.read_bytes()) != self._mode()):
            raise JournalError('retention supervisor mode binding')
        if type(self.retention_anchors) is not dict or len(self.retention_anchors) > 7:
            raise JournalError('retention registration count or type')
        for name, value in self.retention_anchors.items():
            if type(name) is not str or not re.fullmatch('[0-9]{2}', name):
                raise JournalError('retention registration index')
            digest(value)
        actual = {p.name for p in self.budget.root.glob('retention-[0-9]*.json')}
        expected = {f'retention-{name}.json' for name in self.retention_anchors}
        if actual != expected:
            raise JournalError('unanchored or missing retention registration; offline inspection required')

    def handle(self):
        return super().handle() | dict(retention_mode_sha256=self.mode_hash,
                                      retention_anchors=dict(self.retention_anchors))

    def _initialize_capture_retention(self, view):
        """Register before ledger/data creation; all bytes still share one owner."""
        if list(view.root.iterdir()):
            raise JournalError('retention capture must start empty')
        with view.mutation(), lock_directory(view.root):
            # Local identity copy only, never a second ReservedStorageBudget.
            view.atomic_json(view.root/'storage.json', view.contract)
            retirement.register_retention_policy(view)

    def _registration_body(self, index, plan_anchor):
        attempt = self.log.state['attempts'][index]
        return dict(version=1, index=index, capture=str(self.capture_root(index)),
                    run_id=self.plan['run_id'], end=attempt['end'], work_anchor=attempt['anchor'],
                    plan_anchor=plan_anchor, mode_sha256=self.mode_hash)

    def _load_registration(self, index):
        name = f'{index:02d}'
        if name not in self.retention_anchors or index >= len(self.log.state['attempts']):
            raise JournalError('retention registration has no attempt')
        attempt = self.log.state['attempts'][index]
        if attempt['end'] is None or attempt['end']['outcome'] != 'ORIGINAL_DEADLINE':
            raise JournalError('retention requires acknowledged clean attempt')
        path = self.budget.path(self.budget.root/f'retention-{name}.json')
        if path.stat().st_size > 32768 or file_hash(path) != self.retention_anchors[name]:
            raise JournalError('retention registration external anchor differs')
        row = decoded(path.read_bytes())
        keys(row, 'version index capture run_id end work_anchor plan_anchor mode_sha256')
        keys(row['plan_anchor'], 'plan_sha256')
        digest(row['plan_anchor']['plan_sha256'])
        if row != self._registration_body(index, row['plan_anchor']):
            raise JournalError('retention registration attempt binding')
        return row

    def _inspect_retained(self, index, result):
        registration = self._load_registration(index)
        view = ScopedFeedBudget(self.budget, self.capture_root(index))
        plan = retirement.load_plan(view, registration['plan_anchor'])
        if (plan['work_anchor'] != registration['work_anchor'] or result['interrupted'] or
                result.get('pipeline', {}).get('work_ledger_anchor') != plan['work_anchor']):
            raise JournalError('retention plan differs from acknowledged work')
        if [retirement.semantic(a) for a in result['audits']] != [e['expected'] for e in plan['epochs']]:
            raise JournalError('retention plan differs from acknowledged audit')
        present = completed = 0
        with ExitStack() as stack:
            stack.callback(lock_directory(view.root/'retirement').close)
            retirement.locked_sources(stack, view, plan)
            for i, entry in enumerate(plan['entries']):
                retirement.verify_archive(view, entry)
                source = view.path(view.root/entry['source'])
                intent = view.path(view.root/'retirement'/f'intent-{i:04d}.json')
                done = view.path(view.root/'retirement'/f'done-{i:04d}.json')
                binding = dict(plan_sha256=registration['plan_anchor']['plan_sha256'], entry=i,
                               source=entry['source'], bytes=entry['bytes'], sha256=entry['sha256'])
                for path in (intent, done):
                    if path.exists() and (path.stat().st_size > 4096 or decoded(path.read_bytes()) != binding):
                        raise JournalError('retention receipt binding')
                if done.exists() and (not intent.exists() or source.exists()):
                    raise JournalError('retired source reappeared or intent lost')
                if not source.exists() and not intent.exists():
                    raise JournalError('missing raw without retirement intent')
                if source.exists() and (source.stat().st_size != entry['bytes'] or file_hash(source) != entry['sha256']):
                    raise JournalError('retention source changed')
                present += int(source.exists())
                completed += int(done.exists())
            # Cold memory replay adds no checkpoints on repeated restart. This
            # proves historical semantics only; no processor is reused live.
            proof, _, _ = _replay_size(plan)
        return dict(index=index, phase='RETIRED' if completed == len(plan['entries']) else 'PENDING',
                    raw_sources_present=present, completed_entries=completed, entries=len(plan['entries']),
                    semantic_fields_each=17, explicit_source='GZIP_ONLY',
                    cold_replay_sha256=sha(encoded(proof)), live_market_state_restored=False)

    def _results(self):
        self._check_mode()
        results = super()._results()
        mapping = {r['index']: r for r in results}
        for name in self.retention_anchors:
            if int(name) not in mapping:
                raise JournalError('retention registration has no acknowledged result')
        for attempt in self.log.state['attempts']:
            root = self.capture_root(attempt['index'])
            if f"{attempt['index']:02d}" not in self.retention_anchors and (
                    (root/'retirement').exists() or list(root.glob('retirement-replay-*'))):
                raise JournalError('unregistered retirement evidence; preserve and inspect')
        self.retention_status = [self._inspect_retained(int(name), mapping[int(name)])
                                 for name in sorted(self.retention_anchors)]
        return results

    def prepare_closed_retention(self, index, *, minimum_net_savings_bytes=1):
        """Two-phase API: persist returned handle before run may finish unlinks."""
        integer(index); integer(minimum_net_savings_bytes, 1)
        if self.running or self.log.state['finish'] is None:
            raise JournalError('retention preparation requires finished idle supervisor')
        self._results()
        if index >= len(self.log.state['attempts']) or f'{index:02d}' in self.retention_anchors:
            raise JournalError('unknown or already registered retention attempt')
        attempt = self.log.state['attempts'][index]
        if attempt['end'] is None or attempt['end']['outcome'] != 'ORIGINAL_DEADLINE':
            raise JournalError('retention requires clean acknowledged attempt')
        view = ScopedFeedBudget(self.budget, self.capture_root(index))
        control_bytes = len(encoded(self._registration_body(index, dict(plan_sha256=ZERO))))
        estimate = forecast_retirement(view, work_anchor=attempt['anchor'],
                        minimum_net_savings_bytes=minimum_net_savings_bytes+control_bytes)
        if not estimate['admitted']:
            return dict(admitted=False, estimate=estimate, registration_bytes=control_bytes, handle=self.handle())
        self.budget.check(estimate['conservative_peak_growth_bytes']+control_bytes)
        decision = prepare_if_economic(view, work_anchor=attempt['anchor'],
                        minimum_net_savings_bytes=minimum_net_savings_bytes+control_bytes,
                        hook=lambda s: self.hook('retention_prepare:'+s))
        if not decision['anchor']:
            raise JournalError('retention admission changed')
        path = self.budget.root/f'retention-{index:02d}.json'
        body = self._registration_body(index, decision['anchor'])
        if len(encoded(body)) != control_bytes:
            raise JournalError('retention registration size changed')
        self.budget.atomic_json(path, body, lambda s: self.hook('retention_register:'+s))
        self.retention_anchors[f'{index:02d}'] = file_hash(path)
        return dict(admitted=True, estimate=decision['estimate'], registration_bytes=control_bytes,
                    handle=self.handle(), raw_deletion_performed=False)

    def _recover_registered_retention(self):
        self._results()  # All registrations checked before any mutation.
        for name in sorted(self.retention_anchors):
            index = int(name)
            registration = self._load_registration(index)
            view = ScopedFeedBudget(self.budget, self.capture_root(index))
            retirement.retire_raw(view, anchor=registration['plan_anchor'],
                                  hook=lambda s: self.hook('retention:'+s))
        self._results()

    def summary(self):
        result = super().summary()
        return result | dict(retention=list(self.retention_status),
            original_deletion=any(r['raw_sources_present'] < r['entries'] for r in self.retention_status),
            active_segment_retirement_implemented=False, retention_replay_adds_files=False)

    async def run(self,transport):
        if self.running: raise JournalError('supervisor already running')
        self.running=True
        try:
            self.check_clock()
            if self.plan['source_hashes']!=source_hashes(): raise JournalError('supervisor implementation changed')
            self._recover_registered_retention()
            await self._recover_interrupted()
            while self.log.state['finish'] is None:
                now=self.check_clock(); attempts=self.log.state['attempts']; index=len(attempts)
                previous=attempts[-1]['end']['outcome'] if attempts else None
                if previous=='FATAL_FAILURE': reason='FATAL_FAILURE'
                elif previous=='ORIGINAL_DEADLINE' or now>=self.plan['window_end_ns']: reason='ORIGINAL_DEADLINE'
                elif index>len(self.plan['retry_delays_seconds']): reason='RETRY_EXHAUSTED'
                else: reason=None
                if reason:
                    self.log.append('FINISH',dict(reason=reason)); break
                wake=now+(0 if index==0 else self.plan['retry_delays_seconds'][index-1]*NS)
                if wake>=self.plan['window_end_ns']:
                    self.log.append('FINISH',dict(reason='RETRY_WOULD_REACH_DEADLINE')); break
                self.log.append('ATTEMPT',dict(index=index,admitted_ns=now,wake_ns=wake))
                self.hook('after_attempt_before_wait')
                await asyncio.sleep(max(0,(wake-time.monotonic_ns())/NS))
                if self.check_clock()>=self.plan['window_end_ns']:
                    self._end(index,'ORIGINAL_DEADLINE',dict(index=index,outcome='ORIGINAL_DEADLINE',audits=[],interrupted=False))
                    continue
                root=self.capture_root(index)
                with self.budget.mutation(): root.mkdir(); sync_directory(self.budget.root)
                view=ScopedFeedBudget(self.budget,root)
                self._initialize_capture_retention(view)
                pipeline=epoch=None
                try:
                    pipeline=DurableSealedPipeline(view,limits=PipelineLimits(**self.plan['pipeline_limits']),
                                                  _hook=self._receipt_hook(index))
                    epoch=PipelinedFeedEpoch(root/'epoch-00',dict(self.scope(),run_id=self.plan['run_id']),
                                            self.plan['policy']['storage'],budget=view,pipeline=pipeline)
                    self.hook('fresh_epoch_before_network')
                    row=await collect_epoch(epoch,DeadlineTransport(self,transport),audit_control=pipeline)
                    if not pipeline.failed.is_set(): await pipeline.drain()
                    audits=[c['result'] for c in pipeline.channels if c['result'] is not None]
                    result=dict(index=index,outcome=row['outcome'],audits=audits,interrupted=False,
                                epoch=row,pipeline=pipeline.snapshot())
                finally:
                    if epoch is not None and not epoch.epoch_closed:
                        epoch.failed=True
                        epoch.close()
                    if pipeline is not None: await pipeline.close()
                result['pipeline']=pipeline.snapshot()
                self._end(index,row['outcome'],result)
            return self.summary()
        finally: self.running=False
