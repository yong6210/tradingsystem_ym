"""Audited-unit retirement coordinated with the frozen durable worker pipeline."""
import asyncio
from copy import deepcopy
import time

from .archive_segment_reader import segment_ref
from .collector_custody_ledger import CustodyLedger, validate_work
from .durable_capture_log import JournalError, ZERO, encoded
from .durable_sealed_pipeline import DurableSealedPipeline
from .sealed_segment_handoff import certificate


class RetainedFeedPipeline(DurableSealedPipeline):
    def __init__(self, budget, **kwargs):
        super().__init__(budget, **kwargs)
        self.journals = {}
        self.retirement_checked = set()
        self.retirement_decisions = []
        self.raw_bytes_removed = self.active_raw_bytes_removed = 0
        self.max_retirement_ns = 0
        try:
            self.custody = CustodyLedger.create(budget.root/'collector-custody', budget=budget, hook=self.hook)
        except BaseException:
            self.ledger.close()
            raise

    def bind_journals(self, index, raw, audit_log):
        if index in self.journals or index != len(self.journals):
            raise JournalError('collector journal ownership sequence')
        # Own cleanup even if the following durable registration fails.
        self.journals[index] = dict(raw=raw, audit_log=audit_log)
        self.custody.append('EPOCH', dict(channel=index, handles={k:v.handle() for k,v in self.journals[index].items()}))
        self.hook('collector_epoch_bound')

    def handle(self):
        return dict(work_anchor=self.ledger.anchor(), custody_anchor=self.custody.anchor())

    def _retire_ready(self):
        if self.budget.snapshot()['reserved_bytes']:
            return False
        ready = next((u for u in self.units if u['index'] not in self.retirement_checked and
                      self.ledger.model['units'][u['index']]['receipt'] is not None), None)
        if ready is None:
            return False
        began = time.monotonic_ns()
        unit = ready; channel = self.channels[unit['channel']]
        journals = self.journals[unit['channel']]
        handles = {k:j.handle() for k,j in journals.items()}
        names = {k:[] for k in journals}
        # Upper bound the exact registry event, including all candidate names.
        # Charge the entire event and all run/epoch opt-in metadata against EACH
        # candidate. This conservative gate cannot disguise metadata as savings.
        projected = deepcopy(handles)
        for task in unit['archive_tasks']:
            kind = task['kind']; name = certificate(task['ticket'].certificate)['segment']['name']
            names[kind].append(name); projected[kind]['custody_anchors'][name] = ZERO
        payload = dict(unit=unit['index'], channel=unit['channel'], work_anchor=self.ledger.anchor(),
                       audit_receipt=self.ledger.model['units'][unit['index']]['receipt'],
                       handles=projected, names=names)
        event = dict(version=1, sequence=len(self.custody.events),
                     previous_event_sha256=self.custody.anchor()['event_sha256'], kind='RETAIN', payload=payload,
                     event_sha256=ZERO)
        registry_bound = len(encoded(event))
        setup_bytes = sum(len(encoded(e)) for e in self.custody.events if e['kind'] != 'RETAIN')
        setup_bytes += sum((j.directory/'custody-policy.json').stat().st_size
                           for group in self.journals.values() for j in group.values())
        accepted = {k:[] for k in journals}; decisions = []
        for task in unit['archive_tasks']:
            kind = task['kind']; manager = channel[kind]
            descriptor = manager.results[task['job']]
            ref = segment_ref(task['ticket'], archive_directory=str(manager.store.directory.relative_to(self.budget.root)),
                              archive_id=descriptor['archive_id'])
            decision = journals[kind].admit_archive(task['ticket'], ref,
                minimum_net_savings_bytes=1+registry_bound+setup_bytes)
            decisions.append({k:v for k,v in decision.items() if k != 'handle'} | dict(kind=kind))
            if decision['admitted']:
                accepted[kind].append(decision['source'])
        removed = 0; registry_bytes = 0
        active = channel['closed_ns'] is None
        if any(accepted.values()):
            payload.update(handles={k:j.handle() for k,j in journals.items()}, names=accepted)
            before = self.custody.bytes
            self.custody.append('RETAIN', payload)
            registry_bytes = self.custody.bytes-before
            if registry_bytes > registry_bound:
                raise JournalError('custody event exceeded conservative cost forecast')
            validate_work(self.custody, self.ledger)
            self.hook('collector_retention_registered')
            # No await: no newly scheduled worker can reserve/read these files.
            for kind, journal in journals.items():
                if accepted[kind]:
                    present = {name:journal._entry(name)['bytes'] for name in accepted[kind]
                               if (journal.directory/name).exists()}
                    try:
                        journal.finish_retirement(names=accepted[kind])
                    finally:
                        # An exception after unlink still removed real bytes.
                        # Preserve accurate failure reports before propagating.
                        delta = sum(size for name,size in present.items() if not (journal.directory/name).exists())
                        removed += delta; self.raw_bytes_removed += delta
                        if active: self.active_raw_bytes_removed += delta
        self.retirement_checked.add(unit['index'])
        self.retirement_decisions.append(dict(unit=unit['index'], active_epoch=active,
            raw_bytes_removed=removed, registry_bytes=registry_bytes,
            registry_cost_upper_bound=registry_bound, setup_cost_charged_per_candidate=setup_bytes,
            candidates=decisions))
        self.max_retirement_ns = max(self.max_retirement_ns, time.monotonic_ns()-began)
        if self.max_retirement_ns > 500_000_000:
            raise JournalError('retirement synchronous stall')
        return True

    def _dispatch(self):
        began = time.monotonic_ns()
        # Before super schedules the next jobs, consume only previously durable
        # AUDIT receipts. One bounded unit per dispatch, never a history replay.
        self._retire_ready()
        super()._dispatch()
        self.max_dispatch_ns = max(self.max_dispatch_ns, time.monotonic_ns()-began)
        if self.max_dispatch_ns > 500_000_000:
            raise JournalError('retained dispatch synchronous stall')

    async def drain(self):
        began = time.monotonic_ns()
        await super().drain()
        while self._retire_ready():
            if time.monotonic_ns()-began > self.limits.drain_seconds*1e9:
                raise JournalError('retirement drain deadline')
            await asyncio.sleep(0)
        if len(self.retirement_checked) != len(self.units):
            raise JournalError('retirement drain incomplete')

    async def _close(self):
        try:
            await super()._close()
        finally:
            for group in self.journals.values():
                for journal in group.values(): journal.close()
            self.custody.close()

    def snapshot(self):
        return super().snapshot() | dict(retention_handle=self.handle(),
            collector_retirement_integrated=True, original_deletion=self.raw_bytes_removed > 0,
            logical_raw_bytes_removed=self.raw_bytes_removed,
            logical_raw_bytes_removed_while_epoch_open=self.active_raw_bytes_removed,
            max_retirement_ns=self.max_retirement_ns, retirement_decisions=self.retirement_decisions,
            retirement_checked_units=len(self.retirement_checked), metadata_rotation=False)
