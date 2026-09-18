"""Offline parent SIGKILL drills with real collector, workers and fsync.

The harness retains the caller's receipt outside the interrupted run. No public
transport, private credentials, automatic live restart or original deletion.
"""
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.research.data.durable_capture_log import decoded, encoded, file_hash
from app.research.data.durable_sealed_pipeline import DurableSealedPipeline, guarded_command
from app.research.data.pipelined_feed_collector import run_bounded
from app.research.data.recover_sealed_pipeline import recover_admitted_work
from app.research.data.reserved_feed_storage import ReservedStorageBudget
from app.research.data.sealed_feed_pipeline import PipelineLimits
from app.research.data.snapshot_feed_audit import audit_epoch
from app.research.foundation.forward_data_contract import load_contract
from tests.incremental_audit_fixture import COMPARABLE
from tests.test_bounded_feed_collector import ScriptedTransport

STAGES = ('before_unit_admission', 'UNIT:after_checkpoint_fsync', 'UNIT:after_checkpoint_replace',
          'UNIT:after_directory_fsync', 'worker_active', 'archive_registered', 'before_audit_receipt',
          'AUDIT:after_checkpoint_replace', 'CLOSED:after_checkpoint_replace', 'before_final_receipt',
          'FINAL:after_checkpoint_replace', 'COMPLETE:after_checkpoint_replace')


def save(path, value):
    with path.open('x') as f:
        json.dump(value, f, indent=2); f.write('\n'); f.flush(); os.fsync(f.fileno())


def hashes(root):
    return {str(p.relative_to(root)):file_hash(p) for p in sorted(root.rglob('*')) if p.is_file()}


async def child(output, stage):
    managers = []
    def hook(current):
        if current == stage:
            print(json.dumps(dict(stage=stage, parent=os.getpid(), workers=[m.process.pid
                for p in managers for m in p.managers() if m.process is not None])), flush=True)
            signal.pause()
            raise RuntimeError('unexpected resume instead of SIGKILL')
    def factory(budget, **kwargs):
        manager = DurableSealedPipeline(budget, **kwargs, _hook=hook)
        save(output/'external_anchor.json', dict(anchor=manager.ledger.anchor(), budget=budget.contract))
        managers.append(manager)
        return manager
    result = await run_bounded(output/'capture', duration_ns=650_000_000,
        transport=ScriptedTransport(), policy=load_contract(ROOT/'configs/research/forward_data_policy_v1.json'),
        pipeline_limits=PipelineLimits(seal_seconds=.15), _pipeline_factory=factory)
    raise RuntimeError('stage not reached: '+str(result['errors']))


def signal_line(proc):
    with selectors.DefaultSelector() as watcher:
        watcher.register(proc.stdout, selectors.EVENT_READ)
        if not watcher.select(15): raise RuntimeError('child stage timeout')
        line = proc.stdout.readline(16385)
    if not line or len(line)>16384: raise RuntimeError('missing or oversized child stage')
    return json.loads(line)


def process_state(pid):
    row = subprocess.run(['ps','-p',str(pid),'-o','stat='], capture_output=True, text=True, check=False)
    return row.stdout.strip()


def stopped(pid):
    state = process_state(pid)
    return not state or state.startswith('Z')


def wait_stopped(pids):
    began = time.monotonic_ns()
    while any(not stopped(pid) for pid in pids):
        if time.monotonic_ns()-began>3_000_000_000: raise RuntimeError('orphan worker still running')
        time.sleep(.025)
    return time.monotonic_ns()-began


def spawn(output, mode, stage=None):
    command = [sys.executable, str(Path(__file__).resolve()), '--output', str(output), '--mode', mode]
    if stage: command += ['--stage',stage]
    return subprocess.Popen(command, cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, start_new_session=True, env=os.environ|{'PYTHONDONTWRITEBYTECODE':'1'})


def kill_at_stage(output, stage):
    proc = spawn(output, 'child', stage)
    try:
        reached = signal_line(proc)
        assert reached['stage']==stage and reached['parent']==proc.pid
        proc.kill(); proc.wait(timeout=3)
        assert proc.returncode == -signal.SIGKILL
        elapsed = wait_stopped(reached['workers'])
        stdout, stderr = proc.communicate(timeout=3)
        (output/'child_stderr.log').write_bytes(stderr)
        assert not stdout
        return reached | dict(returncode=proc.returncode, worker_stop_wait_ns=elapsed)
    finally:
        if proc.poll() is None: proc.kill(); proc.wait(timeout=3)
        # Only this freshly created harness process group is owned here.
        try: os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError: pass


async def recover(output, anchor):
    row = json.loads((output/'external_anchor.json').read_text())['budget']
    budget = ReservedStorageBudget.resume(output/'capture', **{k:v for k,v in row.items() if k!='version'})
    try:
        result = await recover_admitted_work(budget, anchor=anchor)
        assert budget.snapshot()['reserved_bytes']==0
        return result
    finally: budget.close()


async def run_case(output, stage):
    output.mkdir()
    interruption = kill_at_stage(output, stage)
    root = output/'capture'
    before = hashes(root)
    save(output/'before_recovery_hashes.json', before)
    cp = root/'epoch-00/replay-state/checkpoint.json'
    before_cp = decoded(cp.read_bytes())
    save(output/'before_recovery_checkpoint.json', before_cp)
    first = await recover(output, json.loads((output/'external_anchor.json').read_text())['anchor'])
    save(output/'recovery.json', first)
    after = hashes(root)
    changed = [p for p,h in before.items() if after.get(p)!=h]
    assert all(p.endswith('/replay-state/checkpoint.json') for p in changed), changed
    second = await recover(output, first['work_ledger_anchor'])
    final = hashes(root)
    assert first['epochs']==second['epochs'] and all(final.get(p)==h for p,h in after.items())
    added = sorted(set(final)-set(after))
    assert len(added)==1 and added[0].startswith('work-ledger/event-')
    events = [decoded(p.read_bytes()) for p in sorted((root/'work-ledger').glob('event-*.json'))]
    units = [e for e in events if e['kind']=='UNIT']
    receipts = [e['payload']['receipt'] for e in events if e['kind'] in ('AUDIT','FINAL')]
    assert [r['revision'] for r in receipts]==list(range(1,len(receipts)+1))
    assert len(receipts)==len(units)+sum(e['kind']=='FINAL' for e in events)
    if before_cp['revision']:
        assert receipts.count({k:before_cp[k] for k in ('revision','checkpoint_sha256')})==1
    if stage in STAGES[:2]:
        assert not units and first['epochs'][0]['summary']['last_audited_sequence']==0
        assert first['unadmitted_segment_files']
    else: assert units and first['epochs'][0]['summary']['last_audited_sequence']>0
    compared = 0
    if first['work_ledger_complete']:
        contract = next(e['payload']['contract'] for e in events if e['kind']=='EPOCH')
        baseline = audit_epoch(root/'epoch-00/journal', root/'epoch-00/audit',
            **{k:contract[k] for k in ('window_start_ns','window_end_ns','clock_domain','max_intervals')})
        for k in COMPARABLE: assert encoded(first['epochs'][0]['summary'][k])==encoded(baseline[k]), k
        compared = len(COMPARABLE)
    assert not first['full_original_run_certified'] and not first['live_market_state_restored']
    row = dict(passed=True, stage=stage, interruption=interruption,
        durable_units=len(units), receipts=len(receipts), status=first['status'],
        full_replay_fields_compared=compared, preserved_original_files=len(before)-len(changed),
        changed_existing_paths=changed, repeated_recovery_idempotent=True,
        original_window_preserved=True, new_network_requests=0, actual_orders=0,
        original_deletion=False, automatic_live_restart=False)
    save(output/'second_recovery.json', second); save(output/'result.json', row)
    return row


def guardian_parent():
    worker = subprocess.Popen(guarded_command('audit',15), stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr)
    print(json.dumps(dict(parent=os.getpid(), workers=[worker.pid])),flush=True)
    signal.pause()
    raise RuntimeError('unexpected guardian parent resume')


def guardian_case(output):
    output.mkdir()
    proc = spawn(output, 'guardian-parent')
    try:
        reached = signal_line(proc)
        time.sleep(.2)
        assert not stopped(reached['workers'][0])
        proc.kill(); proc.wait(timeout=3)
        # The grandparent keeps stdin open throughout: worker cannot exit due
        # to EOF. Its independent maximum lifetime is 15s; this bound is 3s.
        elapsed = wait_stopped(reached['workers'])
        assert not proc.stdin.closed
        stdout, stderr = proc.communicate(timeout=3)
        assert not stdout and not stderr
        row = dict(passed=True, parent_sigkill=True, stdin_held_open=True,
            worker_stop_wait_ns=elapsed, independent_lifetime_seconds=15,
            parent_death_bound_seconds=3, os_reaping_by_harness_certified=False)
        save(output/'result.json', row); return row
    finally:
        if proc.poll() is None: proc.kill(); proc.wait(timeout=3)
        try: os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError: pass


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--mode', choices=('all','child','guardian-parent'), default='all')
    parser.add_argument('--stage', choices=STAGES)
    args = parser.parse_args(); output=args.output.resolve()
    if args.mode=='child': return await child(output,args.stage)
    if args.mode=='guardian-parent': return guardian_parent()
    output.mkdir()
    save(output/'plan.json', dict(stages=STAGES, synthetic_window_ns=650_000_000,
        fresh_network_requests=0, parent_interrupt='SIGKILL', guardian_parent_death=True))
    rows=[]
    for i, stage in enumerate(STAGES):
        row=await run_case(output/f'case-{i:02d}',stage);rows.append(row)
        print(json.dumps(row),flush=True)
    guardian=guardian_case(output/'guardian-parent-death')
    save(output/'summary.json', dict(passed=True,cases=rows,guardian=guardian))


if __name__=='__main__': asyncio.run(main())
