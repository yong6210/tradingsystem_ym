"""Bounded same-boot process restart with fresh market state and retained gaps.

Data only, <=120 seconds total original window. Invocation after process loss is
explicit; no daemon installation, credentials, order interfaces or raw removal.
"""
import asyncio
from dataclasses import asdict
from pathlib import Path
import subprocess
import sys
import time
import uuid

from .capture_supervisor_log import CaptureSupervisorLog
from .durable_capture_log import JournalError, decoded, encoded, file_hash, integer, keys, sync_directory
from .durable_sealed_pipeline import DurableSealedPipeline
from .feed_coverage_audit import combine_epochs
from .interruptible_feed_epoch import collect_epoch
from .pipelined_feed_collector import PipelinedFeedEpoch
from .recover_sealed_pipeline import recover_admitted_work
from .reserved_feed_storage import ReservedStorageBudget
from .scoped_feed_budget import ScopedFeedBudget
from .sealed_feed_pipeline import PipelineLimits
from .sealed_segment_handoff import sha
from ..foundation.forward_data_contract import validate_policy

NS=10**9


def source_hashes():
    return {p.name:file_hash(p) for p in sorted(Path(__file__).parent.glob('*.py'))}


def boot_identity():
    if sys.platform=='darwin':
        token=subprocess.run(['sysctl','-n','kern.bootsessionuuid'],check=True,capture_output=True,
                             text=True,timeout=2).stdout.strip()
    elif sys.platform.startswith('linux'):
        token=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    else: raise JournalError('unsupported same-boot monotonic clock')
    token=str(uuid.UUID(token))
    info=time.get_clock_info('monotonic')
    if not info.monotonic or info.adjustable: raise JournalError('unsupported monotonic clock')
    return dict(platform=sys.platform,boot_uuid=token,implementation=info.implementation)


def clock_sample():
    before=time.monotonic_ns(); wall=time.time_ns(); after=time.monotonic_ns()
    return dict(monotonic_ns=after,wall_ns=wall,uncertainty_ns=after-before)


class DeadlineTransport:
    """Check the fixed clock contract before every new transport request."""
    def __init__(self,owner,transport): self.owner,self.transport=owner,transport
    async def connect(self,*args,**kwargs):
        self.owner.check_clock()
        if time.monotonic_ns()>=self.owner.plan['window_end_ns']: raise TimeoutError('original deadline')
        return await self.transport.connect(*args,**kwargs)
    async def snapshot(self,*args,**kwargs):
        self.owner.check_clock()
        if time.monotonic_ns()>=self.owner.plan['window_end_ns']: raise TimeoutError('original deadline')
        return await self.transport.snapshot(*args,**kwargs)


class RestartableFeedCapture:
    def __init__(self,budget,log,*,hook=lambda stage:None):
        self.budget,self.log,self.hook=budget,log,hook
        self.plan=log.state['plan']; self.running=False
        self._last_clock=self.plan['clock_sample']['monotonic_ns']

    @classmethod
    def create(cls,root,*,duration_ns,policy,pipeline_limits=None,hook=lambda stage:None):
        validate_policy(policy); integer(duration_ns,1)
        if duration_ns>120*NS: raise JournalError('restart supervisor limited to 120 seconds total')
        identity=boot_identity(); sample=clock_sample(); limits=pipeline_limits or PipelineLimits()
        if sample['uncertainty_ns']>1_000_000: raise JournalError('clock sampling uncertainty')
        run_id=uuid.uuid4().hex
        budget=ReservedStorageBudget.create(root,run_id=run_id,max_bytes=policy['storage']['hard_run_bytes'],
                                           min_free_bytes=policy['storage']['min_free_bytes'])
        try:
            plan=dict(version=1,run_id=run_id,root=str(budget.root),storage=budget.contract,
                policy=decoded(encoded(policy)),pipeline_limits=asdict(limits),source_hashes=source_hashes(),
                boot_identity=identity,clock_sample=sample,window_start_ns=sample['monotonic_ns'],
                window_end_ns=sample['monotonic_ns']+duration_ns,clock_domain='same-boot:'+run_id,
                retry_delays_seconds=policy['storage']['retry_delays_seconds'])
            return cls(budget,CaptureSupervisorLog.create(budget,plan,hook=hook),hook=hook)
        except BaseException: budget.close(); raise

    @classmethod
    def resume(cls,root,*,handle,hook=lambda stage:None):
        keys(handle,'storage supervisor_anchor')
        budget=ReservedStorageBudget.resume(root,**{k:v for k,v in handle['storage'].items() if k!='version'})
        try:
            log=CaptureSupervisorLog.resume(budget,handle['supervisor_anchor'],hook=hook)
            obj=cls(budget,log,hook=hook)
            p=obj.plan
            keys(p,'version run_id root storage policy pipeline_limits source_hashes boot_identity clock_sample window_start_ns window_end_ns clock_domain retry_delays_seconds')
            if (type(p['version']) is not int or p['version']!=1 or p['root']!=str(budget.root) or
                p['storage']!=budget.contract or handle['storage']!=budget.contract or p['run_id']!=budget.contract['run_id']):
                raise JournalError('supervisor storage binding')
            validate_policy(p['policy']); PipelineLimits(**p['pipeline_limits'])
            if p['source_hashes']!=source_hashes(): raise JournalError('supervisor implementation changed')
            if p['retry_delays_seconds']!=p['policy']['storage']['retry_delays_seconds']:
                raise JournalError('retry policy differs')
            if not 0<p['window_end_ns']-p['window_start_ns']<=120*NS or p['window_start_ns']!=p['clock_sample']['monotonic_ns']:
                raise JournalError('supervisor original window differs')
            obj.check_clock(); obj._results()  # Verify all acknowledged results before any new request.
            return obj
        except BaseException: budget.close(); raise

    def handle(self): return dict(storage=self.budget.contract,supervisor_anchor=self.log.anchor())

    def check_clock(self):
        if boot_identity()!=self.plan['boot_identity']: raise JournalError('boot or clock domain changed')
        now=clock_sample(); base=self.plan['clock_sample']
        if now['uncertainty_ns']>1_000_000 or now['monotonic_ns']<self._last_clock:
            raise JournalError('clock uncertainty or regression')
        drift=abs((now['wall_ns']-base['wall_ns'])-(now['monotonic_ns']-base['monotonic_ns']))
        allowance=self.plan['policy']['quality']['max_wall_monotonic_drift_ms']*1_000_000
        if drift+base['uncertainty_ns']+now['uncertainty_ns']>allowance:
            raise JournalError('wall versus monotonic drift')
        self._last_clock=now['monotonic_ns']
        return now['monotonic_ns']

    def scope(self): return {k:self.plan[k] for k in ('window_start_ns','window_end_ns','clock_domain')}

    def capture_root(self,index): return self.budget.root/f'capture-{index:02d}'

    def _receipt_hook(self,index):
        def hook(stage):
            if stage.endswith(':acknowledged'):
                self._retain_receipts(index)
            self.hook('pipeline:'+stage)
        return hook

    def _retain_receipts(self,index):
        a=self.log.state['attempts'][index]
        n=0 if a['anchor'] is None else a['anchor']['sequence']+1
        directory=self.capture_root(index)/'work-ledger'
        # At most a single lost acknowledgement plus the just-appended event;
        # inventory remains bounded by the frozen ledger's event limit.
        while n<256:
            path=directory/f'event-{n:06d}.json'
            if not path.exists(): break
            with path.open('rb') as stream: raw=stream.read(512*1024+1)
            if len(raw)>512*1024: raise JournalError('work event receipt size')
            row=decoded(raw)
            if row['sequence']!=n or row['event_sha256']!=sha(encoded({k:v for k,v in row.items() if k!='event_sha256'})):
                raise JournalError('work receipt checksum')
            expected='0'*64 if n==0 else self.log.state['attempts'][index]['anchor']['event_sha256']
            if row['previous_event_sha256']!=expected: raise JournalError('work receipt chain')
            self.log.append('RECEIPT',dict(index=index,anchor=dict(sequence=n,event_sha256=row['event_sha256'])))
            n+=1

    def _end(self,index,outcome,result):
        # An unacknowledged result remains as evidence. Each retry writes a new
        # result; only the END event chooses the authoritative one.
        path=self.budget.root/f'result-{index:02d}-{uuid.uuid4().hex}.json'
        if path.exists(): raise JournalError('result already exists')
        if len(encoded(result))>8*1024**2: raise JournalError('attempt result size')
        self.budget.atomic_json(path,result)
        self.hook('after_result_before_end')
        self.log.append('END',dict(index=index,outcome=outcome,result_file=path.name,result_sha256=file_hash(path)))

    def _results(self):
        result=[]
        for a in self.log.state['attempts']:
            if a['end'] is None: continue
            p=self.budget.path(self.budget.root/a['end']['result_file'])
            if not p.is_file() or file_hash(p)!=a['end']['result_sha256']:
                raise JournalError('acknowledged attempt result missing or corrupt')
            if p.stat().st_size>8*1024**2: raise JournalError('attempt result size')
            result.append(decoded(p.read_bytes()))
        return result

    async def _recover_interrupted(self):
        for a in list(self.log.state['attempts']):
            if a['end'] is not None: continue
            index=a['index']; root=self.capture_root(index)
            if a['anchor'] is None:
                # Before the first externally retained START receipt, no epoch
                # or network request was allowed to begin.
                paths=sorted((root/'work-ledger').glob('event-*.json'))
                if len(paths)>1: raise JournalError('work beyond unacknowledged START')
                outcome='ABANDONED_BEFORE_RECEIPT'
                result=dict(index=index,outcome=outcome,audits=[],interrupted=True)
            else:
                view=ScopedFeedBudget(self.budget,root)
                recovered=await recover_admitted_work(view,anchor=a['anchor'],hook=self._receipt_hook(index))
                outcome='PROCESS_INTERRUPTED'
                result=dict(index=index,outcome=outcome,audits=[e['summary'] for e in recovered['epochs']],
                            interrupted=True,recovery=recovered)
            self._end(index,outcome,result)

    async def run(self,transport):
        if self.running: raise JournalError('supervisor already running')
        self.running=True
        try:
            self.check_clock()
            if self.plan['source_hashes']!=source_hashes(): raise JournalError('supervisor implementation changed')
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

    def summary(self):
        results=self._results(); audits=[]; empty=[]
        for r in results:
            for a in r['audits']:
                if a['epoch'] is None:
                    if a['last_audited_sequence']!=0 or any(a['intervals'].values()):
                        raise JournalError('unidentified audit contains observations')
                    empty.append(r['index'])
                else: audits.append(a)
        combined=combine_epochs(self.plan['policy'],audits,**self.scope())
        interrupted=any(r['interrupted'] for r in results)
        if interrupted:
            combined['quality']['status']='QUALITY_INPUTS_REJECTED'
            combined['quality']['reasons'].append('PROCESS_INTERRUPTION_OR_UNACKNOWLEDGED_ATTEMPT')
        if empty:
            combined['quality']['status']='QUALITY_INPUTS_REJECTED'
            combined['quality']['reasons'].append('EMPTY_INTERRUPTED_AUDIT_PREFIX')
        if self.log.state['finish']!='ORIGINAL_DEADLINE':
            combined['quality']['status']='QUALITY_INPUTS_REJECTED'
            combined['quality']['reasons'].append('SUPERVISOR_NOT_CLEAN_DEADLINE')
        combined['quality']['profitability_evaluation_ready']=False
        return dict(stop_reason=self.log.state['finish'],original_window=self.scope(),
            attempts=len(self.log.state['attempts']),retries_consumed=max(0,len(self.log.state['attempts'])-1),
            results=results,combined=combined,empty_audit_attempts=empty,handle=self.handle(),storage=self.budget.snapshot(),
            continuous_runtime_coverage_certified=False,live_market_state_restored=False,
            fresh_state_each_attempt=True,full_day_pilot=False,strategy_adoption=False,
            private_requests=0,actual_orders=0,original_deletion=False)

    def close(self):
        if self.running: raise JournalError('cannot close active supervisor')
        self.budget.close()
