"""SIGKILL the integrated synthetic collector, recover in separate processes."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.research.data.durable_capture_log import JournalError, decoded, encoded, file_hash, sync_directory
from app.research.data.retained_feed_collector import run_bounded
from app.research.data.retained_feed_pipeline import RetainedFeedPipeline
from app.research.data.recover_retained_pipeline import recover_retained_work
from app.research.data.queued_feed_fixture import QueuedTransport
from app.research.data.reserved_feed_storage import ReservedStorageBudget
from app.research.data.sealed_feed_pipeline import PipelineLimits
from tests.incremental_audit_fixture import COMPARABLE
from tests.test_retained_feed_collector import inventory, cold_replay

STAGES=('collector_retention_registered','RETAIN:after_checkpoint_replace',
        'custody_intent:after_checkpoint_fsync','custody_after_unlink',
        'custody_done:after_checkpoint_fsync','custody_register:after_checkpoint_replace')


def save(path,value):
    with path.open('x') as f:
        json.dump(value,f,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
    sync_directory(path.parent)


async def child(output,stage):
    root=output/'run';pipeline=None
    def hook(current):
        if current!=stage:return
        raw=pipeline.journals[0]['raw']
        active=raw.active is not None and not raw.active.closed
        assert pipeline.channels[0]['closed_ns'] is None
        assert active, 'must crash while the next raw segment is open'
        assert not pipeline.budget.snapshot()['reserved_bytes']
        save(output/'before_crash_hashes.json',inventory(root))
        save(output/'audit_before_crash.json',pipeline.channels[0]['owner'].summary())
        save(output/'latest_handle.json',pipeline.handle())
        print(json.dumps(dict(stage=stage,pid=os.getpid(),raw_writer_active=active,
                             raw_sequence=raw.sequence,audited_sequence=pipeline.channels[0]['owner'].summary()['last_audited_sequence'])),flush=True)
        signal.pause();raise RuntimeError('expected SIGKILL')
    def factory(budget,**options):
        nonlocal pipeline
        pipeline=RetainedFeedPipeline(budget,**options,_hook=hook)
        save(output/'external_initial_handle.json',pipeline.handle())
        return pipeline
    policy=decoded((ROOT/'configs/research/forward_data_policy_v1.json').read_bytes())
    result=await run_bounded(root,duration_ns=3_000_000_000,transport=QueuedTransport(per_tick=20),
                            policy=policy,pipeline_limits=PipelineLimits(seal_seconds=.5),_pipeline_factory=factory)
    raise RuntimeError('crash stage not reached: '+str(result['errors']))


async def recover(output,repeat=False):
    root=output/'run';before=inventory(root)
    contract=decoded((root/'storage.json').read_bytes());contract.pop('version')
    handle=decoded((output/('recovery.json' if repeat else 'external_initial_handle.json')).read_bytes())
    if repeat:handle=handle['result']['retention_handle']
    budget=ReservedStorageBudget.resume(root,**contract)
    try:
        result=await recover_retained_work(budget,handle=handle)
        assert result['status']=='ADMITTED_PREFIX_ONLY_INTERRUPTED_RUN'
        assert result['gzip_source_reads']>0 and result['raw_source_reads']>0
        expected=decoded((output/'audit_before_crash.json').read_bytes())
        actual=result['epochs'][0]['summary']
        cold,=cold_replay(root)
        for key in COMPARABLE:
            assert encoded(actual[key])==encoded(expected[key])==encoded(cold[key]),key
        assert not actual['clean_stop_audited']
        assert not result['live_market_state_restored'] and not result['continuous_runtime_coverage_certified']
        assert result['resumed_network_requests']==result['actual_orders']==0
        row=dict(status='RECOVERED',result=result,semantic_fields_equal=len(COMPARABLE))
    except JournalError as exc:
        if decoded((output/'case.json').read_bytes())['stage']!='custody_register:after_checkpoint_replace':raise
        assert 'unanchored' in str(exc),str(exc)
        row=dict(status='REFUSED_UNANCHORED',error=str(exc))
    finally:budget.close()
    after=inventory(root)
    removed=sorted(set(before)-set(after))
    changed=sorted(p for p in before if p in after and before[p]!=after[p])
    assert not changed,changed
    if row['status']=='REFUSED_UNANCHORED':assert before==after
    if repeat:
        assert not removed
        added=set(after)-set(before)
        assert len(added)==1 and next(iter(added)).startswith('work-ledger/event-')
    row.update(removed_sources=removed,removed_bytes=sum(before[p][0] for p in removed),
               changed_existing_files=changed,preserved_existing_files=len(before)-len(removed),
               added_files=sorted(set(after)-set(before)))
    save(output/('repeat.json' if repeat else 'recovery.json'),row)
    save(output/('after_repeat_hashes.json' if repeat else 'after_recovery_hashes.json'),after)


def run_case(output,stage):
    output.mkdir();save(output/'case.json',dict(stage=stage))
    command=[sys.executable,str(Path(__file__).resolve()),'--output',str(output)]
    child_process=subprocess.Popen(command+['--stage',stage],stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                                   start_new_session=True,cwd=ROOT,env=os.environ|{'PYTHONDONTWRITEBYTECODE':'1'})
    try:
        with selectors.DefaultSelector() as watch:
            watch.register(child_process.stdout,selectors.EVENT_READ)
            if not watch.select(20):raise RuntimeError('crash stage timeout')
            line=child_process.stdout.readline(4097)
        if not line or len(line)>4096:raise RuntimeError('child failed: '+child_process.stderr.read().decode())
        ready=json.loads(line);assert ready['stage']==stage and ready['raw_writer_active']
        assert ready['raw_sequence']>ready['audited_sequence']
        os.kill(child_process.pid,signal.SIGKILL);child_process.wait(timeout=10)
        assert child_process.returncode==-9
        save(output/'signal.json',ready|dict(parent_sigkill_returncode=child_process.returncode))
    finally:
        if child_process.poll() is None:os.killpg(child_process.pid,signal.SIGKILL);child_process.wait(timeout=10)
        child_process.stdout.close();child_process.stderr.close()
    save(output/'after_crash_hashes.json',inventory(output/'run'))
    recovery=subprocess.run(command+['--recover'],cwd=ROOT,capture_output=True,text=True,timeout=120)
    save(output/'recovery_process.json',dict(returncode=recovery.returncode,stdout=recovery.stdout,stderr=recovery.stderr))
    assert recovery.returncode==0,recovery.stderr
    row=decoded((output/'recovery.json').read_bytes())
    if row['status']=='RECOVERED':
        repeated=subprocess.run(command+['--repeat'],cwd=ROOT,capture_output=True,text=True,timeout=120)
        save(output/'repeat_process.json',dict(returncode=repeated.returncode,stdout=repeated.stdout,stderr=repeated.stderr))
        assert repeated.returncode==0,repeated.stderr
    before=decoded((output/'before_crash_hashes.json').read_bytes());after=inventory(output/'run')
    for name,value in before.items():
        if name in after:assert tuple(value)==after[name],name
        else:assert '/journal/segment-' in name or '/audit/segment-' in name
    absent = {}
    for path in (output/'run').glob('epoch-*/*/custody/segment-*.jsonl.json'):
        registration=decoded(path.read_bytes());ticket=decoded(registration['ref']['certificate'])
        source=ticket['journal']+'/'+ticket['segment']['name']
        if not ((output/'run')/source).exists():absent[source]=ticket['segment']['bytes']
    return dict(stage=stage,passed=True,parent_sigkill_returncode=-9,raw_writer_active=True,
                outcome=row['status'],semantic_fields_equal=row.get('semantic_fields_equal',0),
                repeated_recovery=row['status']=='RECOVERED',recovery_network_requests=0,
                removed_sources=sorted(set(before)-set(after)),
                raw_removed_after_crash_bytes=sum(before[n][0] for n in set(before)-set(after)),
                total_registered_raw_absent_bytes=sum(absent.values()),registered_absent_sources=absent)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--stage',choices=STAGES);parser.add_argument('--recover',action='store_true')
    parser.add_argument('--repeat',action='store_true');args=parser.parse_args()
    if args.stage:asyncio.run(child(args.output,args.stage))
    elif args.recover or args.repeat:asyncio.run(recover(args.output,args.repeat))
    else:
        args.output.mkdir();rows=[]
        for i,stage in enumerate(STAGES):
            row=run_case(args.output/f'case-{i:02d}',stage);rows.append(row);print(json.dumps(row),flush=True)
        save(args.output/'summary.json',dict(passed=all(r['passed'] for r in rows),cases=rows,
             public_requests=0,private_requests=0,actual_orders=0,synthetic_transport=True))
