"""Real process loss -> separate resume process, using synthetic public feeds."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.research.data.durable_capture_log import encoded, file_hash
from app.research.data.restartable_feed_capture import RestartableFeedCapture
from app.research.data.sealed_feed_pipeline import PipelineLimits
from app.research.data.snapshot_feed_audit import audit_epoch
from tests.incremental_audit_fixture import COMPARABLE
from tests.test_bounded_feed_collector import ScriptedTransport,load_contract

CASES={
 'before_admission':dict(stage='pipeline:before_unit_admission',occurrence=1,seconds=3),
 'before_audit_receipt':dict(stage='pipeline:before_audit_receipt',occurrence=1,seconds=3),
 'external_receipt_temporary':dict(stage='supervisor:RECEIPT:after_checkpoint_fsync',occurrence=3,seconds=3),
 'external_receipt_renamed':dict(stage='supervisor:RECEIPT:after_checkpoint_replace',occurrence=3,seconds=3),
 'fresh_state_before_network':dict(stage='fresh_epoch_before_network',occurrence=1,seconds=3),
 'result_without_end':dict(stage='after_result_before_end',occurrence=1,seconds=.6),
 'retry_wait_already_admitted':dict(stage='after_attempt_before_wait',occurrence=2,seconds=4.5,disconnect_first=True),
 'deadline_expired':dict(stage='pipeline:before_audit_receipt',occurrence=1,seconds=.6,delay_before_resume=.65),
}


def save(path,value):
    with path.open('x') as f:
        json.dump(value,f,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())


def child_pids():
    rows=subprocess.run(['ps','-axo','pid=,ppid=,args='],capture_output=True,text=True,check=True).stdout.splitlines()
    return [int(p[0]) for row in rows if len(p:=row.split(None,2))==3 and int(p[1])==os.getpid()
            and 'app.research.data.parent_bound_worker' in p[2]]


async def child(output,name,mode):
    spec=CASES[name];count=0
    def hook(stage):
        nonlocal count
        if stage==spec['stage']:
            count+=1
            if count==spec['occurrence']:
                print(json.dumps(dict(stage=stage,occurrence=count,parent=os.getpid(),workers=child_pids())),flush=True)
                signal.pause();raise RuntimeError('expected SIGKILL')
    if mode=='create':
        owner=RestartableFeedCapture.create(output/'run',duration_ns=int(spec['seconds']*1e9),
            policy=load_contract(ROOT/'configs/research/forward_data_policy_v1.json'),
            pipeline_limits=PipelineLimits(seal_seconds=.1),hook=hook)
        save(output/'external_handle.json',owner.handle())
    else:
        owner=RestartableFeedCapture.resume(output/'run',handle=json.loads((output/'external_handle.json').read_text()))
    transport=ScriptedTransport(disconnect_first=spec.get('disconnect_first',False) if mode=='create' else False)
    try:
        result=await owner.run(transport)
        if mode=='create': raise RuntimeError('crash stage not reached')
        save(output/(mode+'_result.json'),dict(result=result,connections=transport.connections,
            snapshots=transport.snapshot_count,process=os.getpid(),boot_identity=owner.plan['boot_identity']))
    finally:owner.close()


def command(output,name,mode):
    return [sys.executable,str(Path(__file__).resolve()),'--output',str(output),'--case',name,'--mode',mode]


def stopped(pid):
    state=subprocess.run(['ps','-p',str(pid),'-o','stat='],capture_output=True,text=True).stdout.strip()
    return not state or state.startswith('Z')


def run_case(output,name):
    output.mkdir();spec=CASES[name]
    proc=subprocess.Popen(command(output,name,'create'),stdout=subprocess.PIPE,stderr=subprocess.PIPE,
        start_new_session=True,cwd=ROOT,env=os.environ|{'PYTHONDONTWRITEBYTECODE':'1'})
    try:
        with selectors.DefaultSelector() as watcher:
            watcher.register(proc.stdout,selectors.EVENT_READ)
            if not watcher.select(15): raise RuntimeError('stage timeout')
            line=proc.stdout.readline(16385)
        if not line or len(line)>16384: raise RuntimeError('child did not signal stage')
        signal_row=json.loads(line)
        assert signal_row['stage']==spec['stage'] and signal_row['occurrence']==spec['occurrence']
        proc.kill();proc.wait(timeout=3);assert proc.returncode==-9
        started=time.monotonic()
        while any(not stopped(pid) for pid in signal_row['workers']):
            if time.monotonic()-started>3:raise RuntimeError('orphan worker still active')
            time.sleep(.025)
        stdout,stderr=proc.communicate(timeout=3)
        (output/'interrupted_stderr.log').write_bytes(stderr);assert not stdout
    finally:
        if proc.poll() is None:proc.kill();proc.wait(timeout=3)
        try:os.killpg(proc.pid,signal.SIGKILL)
        except ProcessLookupError:pass
    root=output/'run'
    before={str(p.relative_to(root)):file_hash(p) for p in root.rglob('*') if p.is_file()}
    save(output/'before_hashes.json',before)
    if spec.get('delay_before_resume'):time.sleep(spec['delay_before_resume'])
    for mode in ('resume','repeat'):
        done=subprocess.run(command(output,name,mode),capture_output=True,cwd=ROOT,timeout=20,
            env=os.environ|{'PYTHONDONTWRITEBYTECODE':'1'})
        (output/(mode+'_stderr.log')).write_bytes(done.stderr)
        if done.returncode:raise RuntimeError(mode+' failed: '+done.stderr.decode()[-3000:])
    resumed=json.loads((output/'resume_result.json').read_text());repeated=json.loads((output/'repeat_result.json').read_text())
    r=resumed['result'];rr=repeated['result']
    assert resumed['process']!=signal_row['parent'] and resumed['process']!=repeated['process']
    assert repeated['connections']==[] and repeated['snapshots']==0
    assert {k:v for k,v in r.items() if k!='storage'}=={k:v for k,v in rr.items() if k!='storage'}
    assert r['storage']['used_bytes']==rr['storage']['used_bytes']
    assert r['storage']['reserved_bytes']==rr['storage']['reserved_bytes']==0
    assert r['combined']['quality']['status']=='QUALITY_INPUTS_REJECTED'
    assert r['original_window']['window_end_ns']-r['original_window']['window_start_ns']==int(spec['seconds']*1e9)
    changed=[p for p,h in before.items() if file_hash(root/p)!=h]
    assert all(p.endswith('/replay-state/checkpoint.json') for p in changed),changed
    for result in r['results']:
        for audit in result['audits']:
            assert all(audit[k]==r['original_window'][k] for k in r['original_window'])
    expected_attempts=3 if name=='retry_wait_already_admitted' else 1 if name in ('result_without_end','deadline_expired') else 2
    assert r['attempts']==expected_attempts and r['retries_consumed']==expected_attempts-1
    comparisons=0
    if name in ('result_without_end','deadline_expired'):
        assert resumed['connections']==[] and resumed['snapshots']==0
    else:
        assert len(resumed['connections'])==2 and resumed['snapshots']==1
        fresh=r['results'][-1];index=fresh['index']
        base=audit_epoch(root/f'capture-{index:02d}/epoch-00/journal',root/f'capture-{index:02d}/epoch-00/audit',
            **r['original_window'],max_intervals=10000)
        for k in COMPARABLE:assert encoded(base[k])==encoded(fresh['audits'][0][k]),k
        comparisons=len(COMPARABLE)
        first=fresh['audits'][0]['first_audited_publication_ns']
        last=max((a['last_audited_publication_ns'] or r['original_window']['window_start_ns'])
            for old in r['results'][:-1] for a in old['audits']) if any(old['audits'] for old in r['results'][:-1]) else r['original_window']['window_start_ns']
        assert first>last
        for intervals in r['combined']['intervals'].values():
            assert all(hi<=last or lo>=first for lo,hi in intervals)
    row=dict(passed=True,case=name,parent_sigkill=signal_row,resume_process=resumed['process'],
        attempts=r['attempts'],retries_consumed=r['retries_consumed'],stop_reason=r['stop_reason'],
        resumed_fixture_connections=len(resumed['connections']),resumed_fixture_snapshots=resumed['snapshots'],
        full_replay_fields_compared=comparisons,original_window_unchanged=True,
        repeated_resume_no_network=True,gap_not_bridged=True,changed_existing_paths=changed,
        preserved_existing_files=len(before)-len(changed),new_market_requests=0,actual_orders=0)
    save(output/'verification.json',row);print(json.dumps(row),flush=True);return row


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--mode',choices=('all','create','resume','repeat'),default='all')
    parser.add_argument('--case',choices=CASES)
    args=parser.parse_args();output=args.output.resolve()
    if args.mode!='all':return asyncio.run(child(output,args.case,args.mode))
    output.mkdir();save(output/'plan.json',dict(cases=CASES,network='SYNTHETIC_ONLY',original_deletion=False))
    rows=[run_case(output/name,name) for name in CASES]
    save(output/'summary.json',dict(passed=True,cases=rows))


if __name__=='__main__':main()
