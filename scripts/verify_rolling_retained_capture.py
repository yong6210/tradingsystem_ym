"""Fixed rollover capacity and process-loss drill. Synthetic inputs only."""
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
from app.research.data.durable_capture_log import decoded,encoded,sync_directory
from app.research.data.queued_feed_fixture import QueuedTransport
from app.research.data.rolling_retained_capture import RollingRetainedCapture
from tests.test_bounded_feed_collector import ScriptedTransport,load_contract
from tests.test_retained_feed_collector import inventory,cold_replay
from tests.incremental_audit_fixture import COMPARABLE

STAGES=('rolling:READY:after_checkpoint_replace','pipeline:custody_after_unlink',
        'rolling:result_before_end','rolling:END:after_checkpoint_replace',
        'second_BEGIN:after_checkpoint_replace','rolling:FINISH:after_checkpoint_replace')


def save(path,value):
    with path.open('x') as f:json.dump(value,f,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
    sync_directory(path.parent)


def policy():return load_contract(ROOT/'configs/research/forward_data_policy_v1.json')


async def capacity(output):
    output.mkdir();closed={};owner=None
    def hook(stage):
        if stage=='rolling:END:acknowledged':
            index=owner.log.state['shards'][-1]['index']
            closed[index]=inventory(owner.shard_root(index))
        if stage=='rolling:BEGIN:acknowledged':
            for index,hashes in closed.items():assert inventory(owner.shard_root(index))==hashes
    # This is fixed before observation. >62 total units is the qualification
    # target, not an invitation to search for a faster passing configuration.
    save(output/'plan.json',dict(duration_seconds=40,rotation_seconds=8,seal_seconds=.5,
         per_tick=20,levels_per_side=1000,expected_total_units_above=62,max_shards=16,
         total_window_cap_seconds=120,real_network_requests=0))
    owner=RollingRetainedCapture.create(output/'run',duration_ns=40*10**9,rotation_ns=8*10**9,policy=policy(),hook=hook)
    save(output/'initial_handle.json',owner.handle());transport=QueuedTransport(per_tick=20)
    try:
        result=await owner.run(transport);handle=owner.handle()
        assert result['stop_reason']=='ORIGINAL_DEADLINE'
        assert result['total_units']>62,result['total_units']
        assert result['max_units_in_one_shard']<=18,result['max_units_in_one_shard']
        assert len(transport.connections)==2*result['shards'] and transport.snapshots==result['shards']
        assert result['storage']['reserved_bytes']==0
        assert all(s.summary()['producer_thread_joined'] for s in transport.sockets)
        gaps=[];previous=None
        for row in result['results']:
            actual,=row['audits'];expected,=cold_replay(owner.shard_root(row['index']))
            for key in COMPARABLE:assert encoded(actual[key])==encoded(expected[key]),key
            if previous:
                gap=[previous['last_audited_publication_ns'],actual['first_audited_publication_ns']]
                assert gap[0]<gap[1]
                for spans in result['combined']['intervals'].values():
                    assert all(end<=gap[0] or begin>=gap[1] for begin,end in spans)
                gaps.append(gap)
            previous=actual
        files=inventory(owner.budget.root)
        assert sum(v[0] for v in files.values())==result['storage']['used_bytes']
        # Exhaustive, mutually exclusive byte classes; includes result JSONs,
        # all checkpoints/manifests and any temporaries, not just raw/gzip.
        costs=dict(gzip=0,raw_jsonl=0,result_json=0,other_metadata_and_temps=0)
        for name,(size,digest) in files.items():
            category='gzip' if name.endswith('.gz') else 'raw_jsonl' if name.endswith('.jsonl') else 'result_json' if name.startswith('result-') else 'other_metadata_and_temps'
            costs[category]+=size
        assert sum(costs.values())==result['storage']['used_bytes']
        save(output/'result.json',result);save(output/'handle.json',handle)
        save(output/'producer.json',[s.summary() for s in transport.sockets]);save(output/'costs.json',costs)
        save(output/'rollover_gaps.json',gaps);save(output/'closed_shard_hashes.json',closed)
    finally:owner.close()
    before=inventory(output/'run');owner=RollingRetainedCapture.resume(output/'run',handle=handle)
    try:
        transport=ScriptedTransport();again=await owner.run(transport)
        assert not transport.connections
        assert again['combined']==result['combined']
        assert inventory(output/'run')==before
    finally:owner.close()
    save(output/'final_hashes.json',inventory(output/'run'))
    summary=dict(passed=True,total_units=result['total_units'],max_units_in_one_shard=result['max_units_in_one_shard'],
        shards=result['shards'],semantic_fields_each=17,immutable_completed_shards=True,
        rollover_gaps=len(gaps),gap_nanoseconds=sum(b-a for a,b in gaps),
        shared_total_bytes=sum(costs.values()),all_file_classes_counted=True,completed_resume_no_growth=True,
        completed_resume_network_requests=0,full_day_pilot=False,actual_orders=0)
    save(output/'summary.json',summary);return summary


async def child(output,stage):
    owner=None;begins=0
    def hook(current):
        nonlocal begins
        if current=='rolling:BEGIN:after_checkpoint_replace':begins+=1
        match=current==stage or (stage=='second_BEGIN:after_checkpoint_replace' and current=='rolling:BEGIN:after_checkpoint_replace' and begins==2)
        if not match:return
        save(output/'before_crash_hashes.json',inventory(output/'run'))
        print(json.dumps(dict(stage=stage,pid=os.getpid(),completed_shards=sum(s['end'] is not None for s in owner.log.state['shards']))),flush=True)
        signal.pause();raise RuntimeError('expected SIGKILL')
    owner=RollingRetainedCapture.create(output/'run',duration_ns=3*10**9,rotation_ns=10**9,policy=policy(),hook=hook)
    save(output/'initial_handle.json',owner.handle())
    try:
        result=await owner.run(QueuedTransport(per_tick=20))
        raise RuntimeError('stage not reached '+str(result['stop_reason']))
    finally:owner.close()


async def recover(output,repeat=False):
    initial=decoded((output/'initial_handle.json').read_bytes())
    handle=decoded((output/'recovery.json').read_bytes())['handle'] if repeat else initial
    owner=RollingRetainedCapture.resume(output/'run',handle=handle);transport=ScriptedTransport()
    try:
        result=await owner.run(transport)
        # Parent waits until the original deadline. Recovery must not renew it.
        assert not transport.connections
        assert result['original_window']==owner.scope()
        assert result['stop_reason'] in ('PROCESS_INTERRUPTED','ORIGINAL_DEADLINE')
        assert not result['continuous_runtime_coverage_certified'] and not result['live_market_state_restored']
        save(output/('repeat.json' if repeat else 'recovery.json'),result)
    finally:owner.close()


def run_case(output,stage):
    output.mkdir();save(output/'case.json',dict(stage=stage))
    command=[sys.executable,str(Path(__file__).resolve()),'--output',str(output)]
    process=subprocess.Popen(command+['--child',stage],cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
    try:
        with selectors.DefaultSelector() as watcher:
            watcher.register(process.stdout,selectors.EVENT_READ)
            if not watcher.select(20):raise RuntimeError('rolling crash stage timeout')
            line=process.stdout.readline(4097)
        if not line or len(line)>4096:raise RuntimeError(process.stderr.read().decode())
        ready=json.loads(line);assert ready['stage']==stage
        os.kill(process.pid,signal.SIGKILL);process.wait(timeout=10);assert process.returncode==-9
        save(output/'signal.json',ready|dict(returncode=-9))
    finally:
        if process.poll() is None:os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=10)
        process.stdout.close();process.stderr.close()
    # No busy polling. Preserve the original deadline across separate processes.
    import time
    plan=decoded((output/'run/rolling-log/event-000000.json').read_bytes())['payload']
    time.sleep(max(0,(plan['window_end_ns']-time.monotonic_ns())/1e9)+.02)
    for flag in ('--recover','--repeat'):
        before=inventory(output/'run')
        p=subprocess.run(command+[flag],cwd=ROOT,capture_output=True,text=True,timeout=60)
        save(output/(flag[2:]+'_process.json'),dict(returncode=p.returncode,stdout=p.stdout,stderr=p.stderr))
        assert p.returncode==0,p.stderr
        if flag=='--repeat':assert before==inventory(output/'run')
    after=inventory(output/'run');save(output/'final_hashes.json',after)
    before=decoded((output/'before_crash_hashes.json').read_bytes())
    changed=[p for p in before if p in after and tuple(before[p])!=after[p]]
    assert all(p.endswith('/replay-state/checkpoint.json') for p in changed),changed
    gone=set(before)-set(after)
    assert all('/journal/segment-' in p or '/audit/segment-' in p for p in gone)
    result=decoded((output/'recovery.json').read_bytes())
    return dict(passed=True,stage=stage,parent_sigkill_returncode=-9,stop_reason=result['stop_reason'],
        shards=result['shards'],resumed_network_requests=0,repeated_resume_no_growth=True,
        preserved_existing_files=len(before)-len(changed)-len(gone),advanced_audit_checkpoints=changed,
        retired_synthetic_sources=sorted(gone),original_window_preserved=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--child',choices=STAGES);parser.add_argument('--recover',action='store_true');parser.add_argument('--repeat',action='store_true')
    args=parser.parse_args()
    if args.child:asyncio.run(child(args.output,args.child))
    elif args.recover or args.repeat:asyncio.run(recover(args.output,args.repeat))
    else:
        args.output.mkdir();summary=asyncio.run(capacity(args.output/'capacity'));print(json.dumps(summary),flush=True)
        cases=[]
        for i,stage in enumerate(STAGES):
            row=run_case(args.output/f'crash-{i:02d}',stage);cases.append(row);print(json.dumps(row),flush=True)
        save(args.output/'summary.json',dict(passed=True,capacity=summary,crashes=cases,public_requests=0,private_requests=0,actual_orders=0))
