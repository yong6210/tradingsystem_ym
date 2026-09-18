"""Offline fixed-scenario collector load/fault diagnostics; no market requests."""
import argparse
import asyncio
import faulthandler
import json
from pathlib import Path
import resource
import shutil
import subprocess
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.research.data import bounded_feed_collector_v2 as collector
from app.research.data.bounded_feed_collector import RetryableTransportError, DurableJsonl
from app.research.data.durable_capture_log import DurableCaptureLog
from app.research.data.feed_runtime_diagnostics import GuardedFeedEpoch, capacity_projection
from app.research.foundation.forward_data_contract import load_contract

CASES = {
    'paced_200': dict(rate=200, duration_ns=2_000_000_000, expected='ORIGINAL_DEADLINE'),
    'paced_2000': dict(rate=2000, duration_ns=2_000_000_000, expected='ORIGINAL_DEADLINE'),
    'slow_raw': dict(rate=200, duration_ns=2_000_000_000, expected='FATAL_FAILURE'),
    'slow_audit': dict(rate=200, duration_ns=2_000_000_000, expected='FATAL_FAILURE'),
    'combined_stall': dict(rate=200, duration_ns=2_000_000_000, expected='FATAL_FAILURE'),
    'startup_block': dict(rate=200, duration_ns=2_000_000_000, expected='FATAL_FAILURE'),
    'pending_overflow': dict(rate=2000, duration_ns=2_000_000_000, expected='FATAL_FAILURE'),
    'raw_enospc': dict(rate=200, duration_ns=2_000_000_000, expected='FATAL_FAILURE'),
}


def dump(path, value):
    with path.open('x') as stream:
        stream.write(json.dumps(value, indent=2)+'\n')


class PacedSocket:
    """Small synthetic frames, no external queue or genuine exchange timestamps."""
    def __init__(self, channel, rate):
        self.channel, self.period = channel, 1/rate if channel=='public' else 1
        self.closed = asyncio.Event()
        self.next_at = time.monotonic()
        self.count, self.last_depth = 0, 12

    async def recv(self):
        delay = max(0, self.next_at-time.monotonic())
        if delay:
            try:
                await asyncio.wait_for(self.closed.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass
        if self.closed.is_set():
            raise RetryableTransportError('SCRIPTED_CLOSED')
        self.next_at = max(self.next_at, time.monotonic())+self.period
        self.count += 1
        if self.channel=='market':
            stream = 'btcusdc@markPrice@1s'
            data = dict(e='markPriceUpdate',s='BTCUSDC',E=1000+self.count,T=2000,p='100',i='100',r='0')
        elif self.count==1 or self.count%10==0:
            stream = 'btcusdc@depth@100ms'
            previous = self.last_depth
            if self.count==1:
                first,last,previous=9,12,8
            else:
                first=last=previous+1
                self.last_depth=last
            data=dict(e='depthUpdate',s='BTCUSDC',E=1000+self.count,T=999+self.count,U=first,u=last,pu=previous,b=[],a=[])
        else:
            stream='btcusdc@bookTicker'
            data=dict(e='bookTicker',s='BTCUSDC',E=1000+self.count,T=999+self.count,u=self.last_depth,b='100',B='2',a='101',A='4')
        return json.dumps(dict(stream=stream,data=data))

    async def close(self):
        self.closed.set()


class OfflineTransport:
    def __init__(self, rate, startup_block=False):
        self.rate, self.startup_block = rate, startup_block
        self.sockets=[]

    async def connect(self, channel, url, timeout, *, deadline_ns):
        socket=PacedSocket(channel,self.rate)
        self.sockets.append(socket)
        return socket

    async def snapshot(self, timeout, *, deadline_ns):
        began=time.monotonic_ns()
        if self.startup_block:
            time.sleep(.9)  # Deliberate synchronous stall; not an observed cause.
        return dict(request_started_ns=began,received_ns=time.monotonic_ns(),received_utc_ns=time.time_ns(),
                    http_status=200,wire_text=json.dumps(dict(lastUpdateId=10,
                    bids=[['100','2'],['99','3']],asks=[['101','4'],['102','5']])))


def worker(directory, case):
    spec=CASES[case]
    transport=OfflineTransport(spec['rate'], startup_block=case=='startup_block')
    policy=load_contract(ROOT/'configs/research/forward_data_policy_v1.json')
    original_commit,original_audit=DurableCaptureLog.commit,DurableJsonl.append
    injected=[]
    def commit(writer):
        if writer.sequence>2 and not any(i['phase']=='raw_commit' for i in injected) and case in ('slow_raw','raw_enospc','combined_stall'):
            injected.append(dict(phase='raw_commit',started_ns=time.monotonic_ns()))
            if case=='raw_enospc':
                raise OSError(28,'injected ENOSPC; actual disk was not filled')
            time.sleep(.3 if case=='combined_stall' else .65)
        return original_commit(writer)
    def audit(writer,value):
        if (writer.path.name=='batches.jsonl' and value['last_sequence']>2 and
                not any(i['phase']=='audit_sync' for i in injected) and case in ('slow_audit','combined_stall')):
            injected.append(dict(phase='audit_sync',started_ns=time.monotonic_ns()))
            time.sleep(.3 if case=='combined_stall' else .65)
        return original_audit(writer,value)
    class SmallPending(GuardedFeedEpoch):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs)
            if case=='pending_overflow':
                self.bridge.max_pending=8
    with (directory/'stack_sample.txt').open('x') as stack:
        if case in ('slow_raw','slow_audit','startup_block','combined_stall'):
            faulthandler.dump_traceback_later(.5, file=stack, repeat=False)
        began,cpu=time.monotonic_ns(),time.process_time_ns()
        try:
            with patch.object(DurableCaptureLog,'commit',commit),patch.object(DurableJsonl,'append',audit),\
                    patch.object(collector,'FeedEpoch',SmallPending):
                result=asyncio.run(collector.run_bounded(directory/'capture',duration_ns=spec['duration_ns'],
                                  transport=transport,policy=policy))
        finally:
            faulthandler.cancel_dump_traceback_later()
        wall_ns,cpu_ns=time.monotonic_ns()-began,time.process_time_ns()-cpu
    assert result['stop_reason']==spec['expected'],result['stop_reason']
    assert result['combined']['quality']['calendar_ns']==spec['duration_ns']
    assert result['retries_used']==0
    assert all(socket.closed.is_set() for socket in transport.sockets)
    if case.startswith('paced_'):
        assert not result['audits'][0]['errors'] and result['epochs'][0]['eligible_point_observations']>0
        assert result['epochs'][0]['diagnostics']['retained_bridge_batches']==0
    else:
        assert 'COLLECTOR_FAILURE' in result['combined']['quality']['reasons']
    rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    report=dict(status='PASS_FIXED_OFFLINE_SCENARIO',case=case,requested_public_events_per_second=spec['rate'],
        fixture='small synthetic bookTicker/depth frames and one mark per second; no external producer',
        generated_frames=sum(s.count for s in transport.sockets),wall_ns=wall_ns,cpu_ns=cpu_ns,
        original_window_ns=spec['duration_ns'],
        generated_frames_per_original_second=sum(s.count for s in transport.sockets)*1e9/spec['duration_ns'],
        process_peak_rss_bytes=rss if sys.platform=='darwin' else rss*1024,injected=injected,
        stop_reason=result['stop_reason'],epoch=result['epochs'][0] if result['epochs'] else None,
        audits=[dict(errors=r['errors'],unaudited_committed_records=r['unaudited_committed_records']) for r in result['audits']],
        network_requests=0,actual_orders=0,full_day_ready=False)
    dump(directory/'result.json',report)


def cold_worker(directory):
    rows=[]
    def phase(name,fn):
        began,cpu=time.monotonic_ns(),time.process_time_ns()
        result=fn()
        rows.append(dict(phase=name,wall_ns=time.monotonic_ns()-began,cpu_ns=time.process_time_ns()-cpu))
        return result
    with (directory/'stack_sample.txt').open('x') as stack:
        faulthandler.dump_traceback_later(.5,file=stack,repeat=False)
        try:
            httpx=phase('import_httpx',lambda: __import__('httpx'))
            phase('import_websockets_client',lambda: __import__('websockets.asyncio.client'))
            client=phase('construct_default_httpx_tls_client',lambda: httpx.AsyncClient(trust_env=False,follow_redirects=False))
            asyncio.run(client.aclose())
            async def mock_request():
                async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request:httpx.Response(200,json={}))) as mock:
                    await mock.get('https://fixture.invalid/')
            phase('mock_http_request_no_network',lambda:asyncio.run(mock_request()))
        finally:
            faulthandler.cancel_dump_traceback_later()
    dump(directory/'result.json',dict(phases=rows,network_requests=0,
        scope='fresh Python process; OS file cache not flushed; excludes real DNS/TLS/network waits',
        original_nine_second_cause_proven=False))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--worker',type=Path)
    parser.add_argument('--case',choices=list(CASES)+['cold'])
    args=parser.parse_args()
    if args.worker:
        cold_worker(args.worker) if args.case=='cold' else worker(args.worker,args.case)
        return
    if args.output is None:
        parser.error('--output required')
    args.output.mkdir(parents=True,exist_ok=False)
    dump(args.output/'scenario_plan.json',dict(cases=CASES,cold_processes=3,network_requests=0,
        synthetic_raw_audit_stall_seconds=.65,synthetic_combined_each_phase_seconds=.3,
        synthetic_startup_stall_seconds=.9,small_pending_limit=8,
        source_hashes={str(path.relative_to(ROOT)):__import__('hashlib').sha256(path.read_bytes()).hexdigest()
            for path in [Path(__file__).resolve(),ROOT/'app/research/data/bounded_feed_collector_v2.py',
                         ROOT/'app/research/data/feed_runtime_diagnostics.py']}))
    results={}
    for case in [*CASES,'cold-0','cold-1','cold-2']:
        directory=args.output/case
        directory.mkdir()
        child=subprocess.run([sys.executable,str(Path(__file__).resolve()),'--worker',str(directory),
                              '--case','cold' if case.startswith('cold-') else case],capture_output=True,text=True,timeout=12)
        (directory/'worker_output.log').write_text(child.stdout+child.stderr)
        if child.returncode:
            raise RuntimeError(f'{case}: child exit {child.returncode}; retained evidence at {directory}')
        results[case]=json.loads((directory/'result.json').read_text())
    source=ROOT/'reports/validation/bounded_feed_v3_20260918/collection_result.json'
    archived=json.loads(source.read_text())
    projection=capacity_projection(raw_bytes=archived['total_raw_bytes'],audit_bytes=sum(e['audit_bytes'] for e in archived['epochs']),
        calendar_ns=archived['original_window']['window_end_ns']-archived['original_window']['window_start_ns'],
        free_bytes=shutil.disk_usage(args.output).free)
    dump(args.output/'capacity_projection.json',dict(source=str(source.relative_to(ROOT)),projection=projection))
    failed_source=ROOT/'reports/validation/bounded_feed_20260918/epoch-00/journal/segment-0000000.jsonl'
    records=[json.loads(line)['payload'] for line in failed_source.read_text().splitlines()[1:]]
    gaps=[dict(before_kind=a['kind'],after_kind=b['kind'],before_ns=a['received_ns'],after_ns=b['received_ns'],
               gap_ns=b['received_ns']-a['received_ns']) for a,b in zip(records,records[1:])]
    historical=dict(source=str(failed_source.relative_to(ROOT)),largest_receipt_gaps=sorted(gaps,key=lambda r:r['gap_ns'],reverse=True)[:5],
        contemporaneous_stack_available=False,contemporaneous_rest_phase_timing_available=False,
        original_cause_proven=False,interpretation='Injection reproduces a failure class; it does not identify the historical cause.')
    dump(args.output/'historical_gap_analysis.json',historical)
    report=dict(status='PASS_SCOPED_LOAD_DIAGNOSTICS',scenarios=results,capacity=projection,
        original_nine_second_cause_proven=False,network_requests=0,actual_orders=0,full_day_ready=False,
        blockers=['32MiB audit cap has no rotation; constant-rate archived projection exceeds it.',
                  'Original nine-second stall lacks contemporaneous phase/stack evidence.',
                  'Short synthetic frames and cached fresh-process initialization do not qualify full-day capacity.'])
    dump(args.output/'summary.json',report)
    print(json.dumps(dict(status=report['status'],cases=len(CASES),cold_processes=3,full_day_ready=False),indent=2))


if __name__=='__main__':
    main()
