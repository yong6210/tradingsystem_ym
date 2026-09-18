"""V2 coordinator: durable admissions and receipts around the frozen scheduler.

All overrides are synchronous until acknowledgement: queued workers cannot run
between an admission mutation and its durable event. No automatic live restart.
"""
from dataclasses import asdict
import os
import sys
import time

from .archive_segment_reader import cursor_dict
from .background_incremental_audit import BackgroundIncrementalAudits
from .background_segment_archive import BackgroundArchives
from .durable_capture_log import JournalError
from .sealed_feed_pipeline import SealedFeedPipeline
from .work_receipt_ledger import WorkReceiptLedger


def guarded_command(kind, seconds):
    return [sys.executable, '-m', 'app.research.data.parent_bound_worker', kind,
            '--parent', str(os.getpid()), '--seconds', str(seconds)]


def archive_factory(directory, **kwargs):
    return BackgroundArchives(directory, **kwargs,
        _command=guarded_command('archive', kwargs['limits'].job_seconds))


def audit_factory(owner, **kwargs):
    return BackgroundIncrementalAudits(owner, **kwargs,
        _command=guarded_command('audit', kwargs['limits'].job_seconds))


class DurableSealedPipeline(SealedFeedPipeline):
    def __init__(self, budget, *, limits=None, worker_limits=None, _hook=lambda stage: None,
                 _archive_factory=archive_factory, _audit_factory=audit_factory):
        super().__init__(budget, limits=limits, worker_limits=worker_limits,
                         _archive_factory=_archive_factory, _audit_factory=_audit_factory)
        self.hook = _hook
        self.max_dispatch_ns = 0
        self.ledger = WorkReceiptLedger.create(budget.root/'work-ledger', budget=budget,
            limits=asdict(self.limits), worker_limits=asdict(self.worker_limits), hook=_hook)

    def add_epoch(self, directory, raw_cursor, audit_cursor, scope):
        try:
            index = super().add_epoch(directory, raw_cursor, audit_cursor, scope)
            c = self.channels[index]
            self.ledger.append('EPOCH', dict(index=index, directory=str(directory.relative_to(self.budget.root)),
                contract=c['owner'].contract, initial_receipt=c['owner'].receipt()))
            return index
        except BaseException as exc:
            self.fail('DURABLE_EPOCH:'+str(exc)); raise

    def submit(self, index, raw_tickets, audit_tickets):
        try:
            super().submit(index, raw_tickets, audit_tickets)
            self.hook('before_unit_admission')
            self.ledger.append('UNIT', dict(index=len(self.units)-1, channel=index,
                raw_tickets=[t.certificate.decode() for t in raw_tickets],
                audit_tickets=[t.certificate.decode() for t in audit_tickets]))
        except BaseException as exc:
            self.fail('DURABLE_UNIT:'+str(exc)); raise

    def end_epoch(self, index):
        try:
            super().end_epoch(index)
            c = self.channels[index]
            self.ledger.append('CLOSED', dict(channel=index, raw_cursor=cursor_dict(c['raw_cursor']),
                                             audit_cursor=cursor_dict(c['audit_cursor'])))
        except BaseException as exc:
            self.fail('DURABLE_CLOSE:'+str(exc)); raise

    def _dispatch(self):
        began = time.monotonic_ns()
        super()._dispatch()
        # Workers scheduled by super cannot execute until this method yields.
        # Thus no second audit checkpoint can outrun its previous ledger receipt.
        if any(m.process is not None for m in self.managers()): self.hook('worker_active')
        if any(c[k].results for c in self.channels for k in ('raw','audit_log')):
            self.hook('archive_registered')
        for u in self.units:
            if u['status'] == 'COMPLETE' and self.ledger.model['units'][u['index']]['receipt'] is None:
                c = self.channels[u['channel']]
                self.hook('before_audit_receipt')
                self.ledger.append('AUDIT', dict(unit=u['index'], receipt=c['auditor'].results[u['audit_job']]))
        for c in self.channels:
            if c['result'] is not None and not self.ledger.model['epochs'][c['index']]['final']:
                self.hook('before_final_receipt')
                self.ledger.append('FINAL', dict(channel=c['index'], receipt=c['result']['receipt']))
        self.max_dispatch_ns = max(self.max_dispatch_ns, time.monotonic_ns()-began)
        if self.max_dispatch_ns > 500_000_000:
            raise JournalError('durable dispatch synchronous stall')

    async def drain(self):
        await super().drain()
        self.ledger.append('COMPLETE', {})

    async def _close(self):
        try:
            await super()._close()
        finally:
            self.ledger.close()

    def snapshot(self):
        return super().snapshot() | dict(work_ledger_anchor=self.ledger.anchor(),
            work_ledger_events=len(self.ledger.events), work_ledger_complete=self.ledger.model['complete'],
            max_dispatch_ns=self.max_dispatch_ns, parent_guardian='SAMPLED_PPID_AND_INDEPENDENT_15S_MAX',
            automatic_live_restart=False)
