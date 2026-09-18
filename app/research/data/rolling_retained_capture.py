"""Finite retained shards with fresh market sessions and one original window.

A qualification runner, not a 24-hour service. Completed shards are immutable;
active journal/worker metadata is reset by creating a new namespace. Rotation
closes sockets and reacquires a snapshot, so its gap is never counted as data.
"""
from contextlib import ExitStack
from dataclasses import asdict
from pathlib import Path
import time
import uuid

from .archive_segment_reader import restore_cursor, segment_ref
from .collector_custody_ledger import CustodyLedger, validate_work
from .closed_capture_retirement import SEMANTIC_FIELDS
from .durable_capture_log import JournalError, decoded, encoded, file_hash, integer, keys, sync_directory
from .feed_coverage_audit import combine_epochs
from .incremental_feed_audit import IncrementalFeedAudit
from .recover_retained_pipeline import recover_retained_work
from .recover_sealed_pipeline import archive_identity
from .recovery_custody_journal import RecoveryCustodyJournal
from .reserved_feed_storage import ReservedStorageBudget
from .restartable_feed_capture import RestartableFeedCapture, DeadlineTransport, boot_identity, clock_sample, source_hashes
from .retained_feed_collector import RetainedFeedEpoch
from .retained_feed_pipeline import RetainedFeedPipeline
from .retirement_admission import SizingReplay
from .rolling_capture_log import RollingCaptureLog, MAX_SHARDS
from .rolling_feed_epoch import collect_rolling_epoch
from .scoped_feed_budget import ScopedFeedBudget
from .sealed_feed_pipeline import PipelineLimits
from .sealed_segment_handoff import SealTicket, certificate, sha
from .work_receipt_ledger import WorkReceiptLedger
from ..foundation.forward_data_contract import validate_policy

NS=10**9
MAX_RESULT_BYTES=8*1024**2


def validate_rotation(duration_ns,rotation_ns,limits):
    integer(duration_ns,1);integer(rotation_ns,1)
    if duration_ns>120*NS:raise JournalError('rolling qualification limited to 120 seconds')
    if not .5<=limits.seal_seconds<=2:
        raise JournalError('rolling seal cadence unqualified; require 0.5 to 2 seconds')
    if not NS<=rotation_ns<=30*NS:
        raise JournalError('rotation interval must be 1 to 30 seconds')
    if (duration_ns+rotation_ns-1)//rotation_ns>MAX_SHARDS:
        raise JournalError('planned shard count exceeds bounded manifest')
    period=int(limits.seal_seconds*NS)
    # One periodic seal per flusher pass; reserve final seal and phase boundary.
    units=(min(duration_ns,rotation_ns)+period-1)//period+2
    if units>limits.max_units:raise JournalError('rotation exceeds per-shard work budget')
    return dict(max_planned_shards=(duration_ns+rotation_ns-1)//rotation_ns,
                conservative_units_per_shard=units,per_shard_unit_limit=limits.max_units,
                input_frames_batched_or_dropped=False,adaptive_cadence=False)


def inspect_completed_shard(view,handle,expected,*,require_complete):
    """Read-only cold replay and custody validation of acknowledged evidence."""
    with ExitStack() as stack:
        work=WorkReceiptLedger.resume(view.root/'work-ledger',budget=view,anchor=handle['work_anchor']);stack.callback(work.close)
        custody=CustodyLedger.resume(view.root/'collector-custody',budget=view,anchor=handle['custody_anchor']);stack.callback(custody.close)
        validate_work(custody,work)
        if require_complete and not work.model['complete']:raise JournalError('clean shard has incomplete work ledger')
        if len(expected)!=len(work.model['epochs']):raise JournalError('shard audit set differs')
        for index,channel in enumerate(work.model['epochs']):
            contract=channel['contract']
            for kind,key in [('raw','raw_initial'),('audit_log','audit_initial')]:
                journal=RecoveryCustodyJournal.open_for_recovery(view.root/contract[key]['journal'],budget=view,
                    handle=custody.model['epochs'][index][kind]);stack.callback(journal.close)
                # Completed outcomes must not hide unfinished custody deletion.
                for name in journal.custody_anchors:
                    source,intent,done=journal._state(name)
                    if require_complete and (source.exists() or not done.exists()):
                        raise JournalError('clean shard has unfinished retirement')
            owner=IncrementalFeedAudit.resume(view.root/channel['directory']/'replay-state',budget=view,
                contract=contract,anchor=channel['receipt']);stack.callback(owner.close)
            if owner.receipt()!=channel['receipt']:raise JournalError('unacknowledged audit advance in ended shard')
            replay=SizingReplay.cold(contract)
            for unit_id in channel['unit_ids']:
                unit=work.model['units'][unit_id];refs=[]
                if unit['receipt'] is None:raise JournalError('ended shard has incomplete admitted work')
                for kind,key in [('raw','raw_tickets'),('audit','audit_tickets')]:
                    for text in unit[key]:
                        ticket=SealTicket(text.encode());row=certificate(ticket.certificate)
                        refs.append(segment_ref(ticket,archive_directory=channel['directory']+'/'+kind+'-archives',
                                                archive_id=sha(encoded(archive_identity(row)))))
                replay.advance(audit_ref=refs[-1],raw_refs=refs[:-1])
            if channel['final']:
                replay.finalize(**{key:restore_cursor(channel[key]) for key in ('raw_cursor','audit_cursor')})
            for field in SEMANTIC_FIELDS:
                if encoded(replay.summary()[field])!=encoded(expected[index][field]) or encoded(owner.summary()[field])!=encoded(expected[index][field]):
                    raise JournalError('ended shard cold replay differs: '+field)
        return dict(units=len(work.model['units']),retired_units=len(custody.model['retained']))


class RollingRetainedCapture:
    check_clock=RestartableFeedCapture.check_clock

    def __init__(self,budget,log,hook):
        self.budget,self.log,self.hook=budget,log,hook
        self.plan=log.state['plan'];self.running=False
        self._last_clock=self.plan['clock_sample']['monotonic_ns']

    @classmethod
    def create(cls,root,*,duration_ns,policy,rotation_ns=10*NS,pipeline_limits=None,hook=lambda stage:None):
        validate_policy(policy);limits=pipeline_limits or PipelineLimits(seal_seconds=.5)
        capacity=validate_rotation(duration_ns,rotation_ns,limits)
        identity=boot_identity();sample=clock_sample()
        if sample['uncertainty_ns']>1_000_000:raise JournalError('clock sampling uncertainty')
        run_id=uuid.uuid4().hex
        budget=ReservedStorageBudget.create(root,run_id=run_id,max_bytes=policy['storage']['hard_run_bytes'],
                                           min_free_bytes=policy['storage']['min_free_bytes'])
        try:
            plan=dict(version=1,root=str(budget.root),run_id=run_id,storage=budget.contract,
                policy=decoded(encoded(policy)),pipeline_limits=asdict(limits),rotation_ns=rotation_ns,capacity=capacity,
                source_hashes=source_hashes(),boot_identity=identity,clock_sample=sample,
                window_start_ns=sample['monotonic_ns'],window_end_ns=sample['monotonic_ns']+duration_ns,
                clock_domain='same-boot-rolling:'+run_id)
            return cls(budget,RollingCaptureLog.create(budget,plan,hook),hook)
        except BaseException:budget.close();raise

    @classmethod
    def resume(cls,root,*,handle,hook=lambda stage:None):
        keys(handle,'storage rolling_anchor')
        budget=ReservedStorageBudget.resume(root,**{k:v for k,v in handle['storage'].items() if k!='version'})
        try:
            log=RollingCaptureLog.resume(budget,handle['rolling_anchor'],hook);obj=cls(budget,log,hook);p=obj.plan
            keys(p,'version root run_id storage policy pipeline_limits rotation_ns capacity source_hashes boot_identity clock_sample window_start_ns window_end_ns clock_domain')
            if (type(p['version']) is not int or p['version']!=1 or p['root']!=str(budget.root) or
                    p['storage']!=budget.contract or p['run_id']!=budget.contract['run_id'] or
                    p['source_hashes']!=source_hashes() or p['window_start_ns']!=p['clock_sample']['monotonic_ns']):
                raise JournalError('rolling storage, window or implementation binding')
            validate_policy(p['policy'])
            if p['capacity']!=validate_rotation(p['window_end_ns']-p['window_start_ns'],p['rotation_ns'],PipelineLimits(**p['pipeline_limits'])):
                raise JournalError('rolling capacity contract differs')
            obj.check_clock()
            return obj
        except BaseException:budget.close();raise

    def handle(self):return dict(storage=self.budget.contract,rolling_anchor=self.log.anchor())
    def scope(self):return {k:self.plan[k] for k in ('window_start_ns','window_end_ns','clock_domain')}
    def shard_root(self,index):return self.budget.root/f'shard-{index:02d}'

    def _end(self,index,outcome,result):
        raw=encoded(result)
        if len(raw)>MAX_RESULT_BYTES:raise JournalError('rolling shard result byte bound')
        path=self.budget.root/f'result-{index:02d}-{uuid.uuid4().hex}.json'
        self.budget.atomic_json(path,result)
        self.hook('rolling:result_before_end')
        self.log.append('END',dict(index=index,outcome=outcome,result_file=path.name,result_sha256=file_hash(path)))

    def _results(self):
        rows=[]
        for shard in self.log.state['shards']:
            if shard['end'] is None:continue
            end=shard['end'];path=self.budget.path(self.budget.root/end['result_file'])
            if path.stat().st_size>MAX_RESULT_BYTES or file_hash(path)!=end['result_sha256']:
                raise JournalError('rolling acknowledged result changed')
            row=decoded(path.read_bytes())
            if row['index']!=shard['index'] or row['outcome']!=end['outcome']:
                raise JournalError('rolling result identity differs')
            if row['handle'] is not None:
                view=ScopedFeedBudget(self.budget,self.shard_root(shard['index']))
                row['inspection']=inspect_completed_shard(view,row['handle'],row['audits'],
                    require_complete=row['outcome'] in ('PLANNED_ROLLOVER','ORIGINAL_DEADLINE'))
            rows.append(row)
        return rows

    async def _recover_open(self):
        """A lost process terminates this qualification window; no new sockets."""
        for shard in self.log.state['shards']:
            if shard['end'] is not None:continue
            index=shard['index'];root=self.shard_root(index)
            if shard['handle'] is None:
                # READY is fenced before epoch construction or network access.
                if list(root.glob('epoch-*')):raise JournalError('epoch before durable rolling READY')
                outcome='ABANDONED_BEFORE_READY';audits=[];handle=None;recovery=None
            else:
                recovery=await recover_retained_work(ScopedFeedBudget(self.budget,root),handle=shard['handle'])
                outcome='PROCESS_INTERRUPTED';audits=[r['summary'] for r in recovery['epochs']]
                handle=recovery['retention_handle']
            self._end(index,outcome,dict(index=index,outcome=outcome,audits=audits,handle=handle,
                interrupted=True,recovery=recovery,pipeline=None,epoch=None))
            self.log.append('FINISH',dict(reason='PROCESS_INTERRUPTED'))
            return

    async def run(self,transport):
        if self.running:raise JournalError('rolling capture already running')
        self.running=True
        try:
            self.check_clock()
            if self.plan['source_hashes']!=source_hashes():raise JournalError('rolling implementation changed')
            self._results()  # Validate acknowledged evidence before any new request.
            await self._recover_open()
            while self.log.state['finish'] is None:
                now=self.check_clock();shards=self.log.state['shards'];index=len(shards)
                previous=shards[-1]['end']['outcome'] if shards else None
                if previous=='ABANDONED_BEFORE_READY':reason='PROCESS_INTERRUPTED'
                elif previous not in (None,'PLANNED_ROLLOVER'):reason=previous
                elif now>=self.plan['window_end_ns']:reason='ORIGINAL_DEADLINE'
                elif index>=MAX_SHARDS:reason='SHARD_LIMIT'
                else:reason=None
                if reason:
                    self.log.append('FINISH',dict(reason=reason));break
                deadline=min(now+self.plan['rotation_ns'],self.plan['window_end_ns'])
                self.log.append('BEGIN',dict(index=index,admitted_ns=now,deadline_ns=deadline))
                root=self.shard_root(index)
                with self.budget.mutation():root.mkdir();sync_directory(self.budget.root)
                view=ScopedFeedBudget(self.budget,root)
                view.atomic_json(root/'storage.json',view.contract)
                pipeline=epoch=None
                try:
                    pipeline=RetainedFeedPipeline(view,limits=PipelineLimits(**self.plan['pipeline_limits']),
                        _hook=lambda stage:self.hook('pipeline:'+stage))
                    self.log.append('READY',dict(index=index,handle=pipeline.handle()))
                    # Setup and drain consume real time inside the original
                    # denominator. Do not create a late connection after either
                    # the shard deadline or the original deadline.
                    if self.check_clock()>=deadline:raise JournalError('rolling setup exhausted shard deadline')
                    epoch=RetainedFeedEpoch(root/'epoch-00',dict(self.scope(),run_id=self.plan['run_id']),
                        self.plan['policy']['storage'],budget=view,pipeline=pipeline)
                    self.hook('rolling:fresh_epoch_before_network')
                    row=await collect_rolling_epoch(epoch,DeadlineTransport(self,transport),stop_at_ns=deadline,audit_control=pipeline)
                    if not pipeline.failed.is_set():await pipeline.drain()
                finally:
                    if epoch is not None and not epoch.epoch_closed:
                        epoch.failed=True;epoch.close()
                    if pipeline is not None:await pipeline.close()
                result=dict(index=index,outcome=row['outcome'],audits=[c['result'] for c in pipeline.channels if c['result'] is not None],
                            handle=pipeline.handle(),pipeline=pipeline.snapshot(),epoch=row,interrupted=False)
                self._end(index,row['outcome'],result)
                # No predecessor object is carried into the next live shard.
                pipeline=epoch=None
            return self.summary()
        finally:self.running=False

    def summary(self):
        rows=self._results();audits=[];interrupted=any(r['interrupted'] for r in rows)
        for row in rows:
            for audit in row['audits']:
                if audit['epoch'] is not None:audits.append(audit)
                elif audit['last_audited_sequence'] or any(audit['intervals'].values()):raise JournalError('unidentified rolling audit')
        combined=combine_epochs(self.plan['policy'],audits,**self.scope())
        if interrupted or self.log.state['finish']!='ORIGINAL_DEADLINE':
            combined['quality']['status']='QUALITY_INPUTS_REJECTED'
            combined['quality']['reasons'].append('ROLLING_INTERRUPTION_OR_INCOMPLETE_WINDOW')
        combined['quality']['profitability_evaluation_ready']=False
        pipelines=[r['pipeline'] for r in rows if r['pipeline'] is not None]
        return dict(stop_reason=self.log.state['finish'],original_window=self.scope(),shards=len(rows),results=rows,
            combined=combined,handle=self.handle(),storage=self.budget.snapshot(),
            total_units=sum(r.get('inspection',{}).get('units',0) for r in rows),
            max_units_in_one_shard=max((r.get('inspection',{}).get('units',0) for r in rows),default=0),
            original_deletion=any(r.get('inspection',{}).get('retired_units',0)>0 for r in rows),
            fresh_market_state_each_shard=True,rollover_gaps_credited=False,metadata_rotation='NEW_BOUNDED_SHARD_NAMESPACE',
            total_metadata_unbounded=False,max_shards=MAX_SHARDS,global_inventory_still_grows=True,
            automatic_restart_after_process_loss=False,transport_failure_retries=False,
            continuous_runtime_coverage_certified=False,live_market_state_restored=False,
            full_day_pilot=False,strategy_adoption=False,private_requests=0,actual_orders=0)

    def close(self):
        if self.running:raise JournalError('cannot close active rolling capture')
        self.budget.close()
