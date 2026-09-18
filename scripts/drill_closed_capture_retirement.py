"""SIGKILL raw-retirement drills on newly generated disposable captures only."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.research.data.closed_capture_retirement import (
    register_retention_policy,prepare_retirement,retire_raw,replay_retired_capture,load_plan)
from app.research.data.durable_capture_log import file_hash
from app.research.data.durable_sealed_pipeline import DurableSealedPipeline
from app.research.data.pipelined_feed_collector import run_bounded
from app.research.data.reserved_feed_storage import ReservedStorageBudget
from app.research.data.sealed_feed_pipeline import PipelineLimits
from tests.test_bounded_feed_collector import ScriptedTransport,load_contract

STAGES=('intent:after_checkpoint_fsync','intent:after_checkpoint_replace','intent:after_directory_fsync',
        'before_unlink','after_unlink','after_source_directory_fsync','done:after_checkpoint_fsync',
        'done:after_checkpoint_replace','done:after_directory_fsync')


def save(path,value):
    with path.open('x') as f:
        json.dump(value,f,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())


def inventory(root):
    return {str(p.relative_to(root)):dict(sha256=file_hash(p),bytes=p.stat().st_size)
            for p in sorted(root.rglob('*')) if p.is_file()}


async def child(output,stage):
    def factory(budget,**kwargs):
        register_retention_policy(budget)
        return DurableSealedPipeline(budget,**kwargs)
    result=await run_bounded(output/'capture',duration_ns=450_000_000,transport=ScriptedTransport(),
        policy=load_contract(ROOT/'configs/research/forward_data_policy_v1.json'),
        pipeline_limits=PipelineLimits(seal_seconds=.1),_pipeline_factory=factory)
    assert result['stop_reason']=='ORIGINAL_DEADLINE',result['errors']
    contract=json.loads((output/'capture/storage.json').read_text())
    budget=ReservedStorageBudget.resume(output/'capture',**{k:v for k,v in contract.items() if k!='version'})
    try:
        anchor=prepare_retirement(budget,work_anchor=result['pipeline']['work_ledger_anchor'])
        save(output/'external_anchor.json',dict(anchor=anchor,storage=contract))
        save(output/'before_hashes.json',inventory(budget.root))
        def hook(current):
            if current==stage:
                print(json.dumps(dict(stage=current,pid=os.getpid())),flush=True)
                signal.pause();raise RuntimeError('expected SIGKILL')
        retire_raw(budget,anchor=anchor,hook=hook)
        raise RuntimeError('stage not reached')
    finally:budget.close()


def recover(output):
    handle=json.loads((output/'external_anchor.json').read_text());root=output/'capture'
    budget=ReservedStorageBudget.resume(root,**{k:v for k,v in handle['storage'].items() if k!='version'})
    try:
        anchor=handle['anchor'];plan=load_plan(budget,anchor)
        result=retire_raw(budget,anchor=anchor)
        first=inventory(root);second=retire_raw(budget,anchor=anchor);assert inventory(root)==first
        assert second['logical_raw_bytes_removed_this_call']==0
        proof=replay_retired_capture(budget,anchor=anchor)
        before=json.loads((output/'before_hashes.json').read_text());after=inventory(root)
        removed=sorted(set(before)-set(after));expected=sorted(e['source'] for e in plan['entries'])
        assert removed==expected
        assert all(after[name]==row for name,row in before.items() if name not in removed)
        assert all(not (root/e['source']).exists() for e in plan['entries'])
        proof_body=json.loads((root/proof['path']).read_text())
        assert proof_body['explicit_source']=='GZIP_ONLY' and proof['fields_each']==17
        row=dict(passed=True,retirement=result,second_call_idempotent=True,replay=proof,
            removed_sources=removed,removed_logical_raw_bytes=sum(before[p]['bytes'] for p in removed),
            preserved_existing_files=len(before)-len(removed),
            after_prepare_before_retire_bytes=sum(v['bytes'] for v in before.values()),
            after_retire_and_replay_bytes=sum(v['bytes'] for v in after.values()),
            new_fixture_raw_deletion=True,historical_evidence_deletion=False,new_network_requests=0,
            physical_disk_reclamation_certified=False,actual_orders=0)
        save(output/'recovery_result.json',row)
        return row
    finally:budget.close()


def run_case(output,stage):
    output.mkdir()
    proc=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--output',str(output),'--stage',stage],
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True,cwd=ROOT,
        env=os.environ|{'PYTHONDONTWRITEBYTECODE':'1'})
    try:
        with selectors.DefaultSelector() as watch:
            watch.register(proc.stdout,selectors.EVENT_READ)
            if not watch.select(15):raise RuntimeError('crash stage timeout')
            line=proc.stdout.readline(4097)
        if not line or len(line)>4096:raise RuntimeError('missing or oversized stage signal')
        signal_row=json.loads(line);assert signal_row==dict(stage=stage,pid=proc.pid)
        proc.kill();proc.wait(timeout=3);assert proc.returncode==-9
        stdout,stderr=proc.communicate(timeout=3);assert not stdout
        (output/'child_stderr.log').write_bytes(stderr)
    finally:
        if proc.poll() is None:proc.kill();proc.wait(timeout=3)
        try:os.killpg(proc.pid,signal.SIGKILL)
        except ProcessLookupError:pass
    row=recover(output)|dict(stage=stage,parent_sigkill_returncode=proc.returncode)
    save(output/'verification.json',row);print(json.dumps(row),flush=True)
    return row


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--stage',choices=STAGES)
    args=parser.parse_args();output=args.output.resolve()
    if args.stage:return asyncio.run(child(output,args.stage))
    output.mkdir();save(output/'plan.json',dict(stages=STAGES,disposition_scope='NEW_SYNTHETIC_CAPTURE_ONLY',
        prior_capture_mutation=False,new_network_requests=0))
    rows=[run_case(output/f'case-{i:02d}',stage) for i,stage in enumerate(STAGES)]
    save(output/'summary.json',dict(passed=True,cases=rows))


if __name__=='__main__':main()
