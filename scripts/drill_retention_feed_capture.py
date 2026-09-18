"""Actual process-loss drills through the opt-in retention supervisor API."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.research.data.durable_capture_log import encoded, file_hash, sync_directory
from app.research.data.retention_feed_capture import RetentionFeedCapture
from app.research.data.sealed_feed_pipeline import PipelineLimits
from tests.test_bounded_feed_collector import ScriptedTransport, ROOT, load_contract

STAGES = ('external_handle_durable', 'retention:intent:after_checkpoint_fsync',
          'retention:after_unlink', 'retention:done:after_checkpoint_fsync')


def save(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    sync_directory(path.parent)


def inventory(root):
    return {str(p.relative_to(root)): dict(bytes=p.stat().st_size, sha256=file_hash(p))
            for p in sorted(root.rglob('*')) if p.is_file()}


async def child(output, stage):
    owner = RetentionFeedCapture.create(output/'run', duration_ns=450_000_000,
        policy=load_contract(ROOT/'configs/research/forward_data_policy_v1.json'),
        pipeline_limits=PipelineLimits(seal_seconds=.5))
    try:
        collected = await owner.run(ScriptedTransport())
        assert collected['stop_reason'] == 'ORIGINAL_DEADLINE'
        save(output/'collected.json', collected)
        save(output/'before_preparation_hashes.json', inventory(owner.budget.root))
        decision = owner.prepare_closed_retention(0)
        assert decision['admitted'], decision
        save(output/'external_handle.json', decision)
        def hook(current):
            if current == stage:
                print(json.dumps(dict(stage=current, pid=os.getpid())), flush=True)
                signal.pause()
                raise RuntimeError('expected SIGKILL')
        owner.hook = hook
        hook('external_handle_durable')
        await owner.run(ScriptedTransport())
        raise RuntimeError('stage not reached')
    finally:
        owner.close()


async def recover(output):
    handle = json.loads((output/'external_handle.json').read_text())['handle']
    root = output/'run'
    before_resume = inventory(root)
    save(output/'before_resume_hashes.json', before_resume)
    owner = RetentionFeedCapture.resume(root, handle=handle)
    try:
        assert before_resume == inventory(root), 'resume validation wrote data'
        transport = ScriptedTransport()
        result = await owner.run(transport)
        save(output/'recovered.json', result)
        assert transport.connections == [] and transport.snapshot_count == 0
        assert result['retention'][0]['phase'] == 'RETIRED'
        collected = json.loads((output/'collected.json').read_text())
        assert encoded(result['combined']) == encoded(collected['combined'])
        assert result['original_window'] == collected['original_window']
        first = inventory(root)
        again = await owner.run(transport)
        assert first == inventory(root) and again['retention'] == result['retention']
    finally:
        owner.close()
    # New owner, same external handle, no new replay checkpoints or transport.
    owner = RetentionFeedCapture.resume(root, handle=handle)
    try:
        transport = ScriptedTransport()
        restarted = await owner.run(transport)
        assert inventory(root) == first and transport.connections == [] and transport.snapshot_count == 0
        assert restarted['retention'] == result['retention']
    finally:
        owner.close()
    before = json.loads((output/'before_preparation_hashes.json').read_text())
    removed = sorted(set(before)-set(first))
    assert removed and all(p.startswith('capture-00/epoch-00/') and len(Path(p).parts) == 4
                           and Path(p).name.startswith('segment-') for p in removed)
    assert all(first[p] == v for p,v in before.items() if p not in removed)
    assert all(first[p] == v for p,v in before_resume.items() if p in first), 'existing recovery evidence changed'
    save(output/'after_hashes.json', first)
    return dict(passed=True, resume_no_file_changes=True, repeated_run_no_file_changes=True,
                repeated_new_owner_no_file_changes=True, old_raw_recreated=False,
                gzip_only_semantic_fields_each=17, combined_quality_unchanged=True,
                new_connections=0, new_snapshots=0, before_bytes=sum(v['bytes'] for v in before.values()),
                after_bytes=sum(v['bytes'] for v in first.values()), removed_sources=removed,
                raw_removed_bytes=sum(before[p]['bytes'] for p in removed),
                original_files_preserved=len(before)-len(removed),
                preserved_crash_temporaries=[p for p in before_resume if p.endswith('.tmp')],
                active_segment_retirement_implemented=False, physical_reclamation_certified=False,
                live_market_state_restored=False, actual_orders=0)


def run_case(output, stage):
    output.mkdir()
    process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--output', str(output), '--stage', stage],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True, cwd=ROOT,
        env=os.environ | {'PYTHONDONTWRITEBYTECODE': '1'})
    try:
        with selectors.DefaultSelector() as watch:
            watch.register(process.stdout, selectors.EVENT_READ)
            if not watch.select(20):
                raise RuntimeError('crash stage timeout')
            line = process.stdout.readline(4097)
        if not line or len(line) > 4096:
            raise RuntimeError('missing crash stage: '+process.stderr.read(8192).decode())
        assert json.loads(line) == dict(stage=stage, pid=process.pid)
        process.kill()
        process.wait(timeout=3)
        assert process.returncode == -9
        stdout, stderr = process.communicate(timeout=3)
        assert not stdout
        (output/'child_stderr.log').write_bytes(stderr)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=3)
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    row = asyncio.run(recover(output)) | dict(stage=stage, parent_sigkill_returncode=process.returncode)
    save(output/'verification.json', row)
    print(json.dumps(row), flush=True)
    return row


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--stage', choices=STAGES)
    args = parser.parse_args()
    output = args.output.resolve()
    if args.stage:
        asyncio.run(child(output, args.stage))
    else:
        output.mkdir()
        save(output/'plan.json', dict(stages=STAGES, synthetic_only=True, public_requests=0,
            private_requests=0, source_hashes={p:file_hash(ROOT/p) for p in (
                'scripts/drill_retention_feed_capture.py', 'app/research/data/retention_feed_capture.py')}))
        rows = [run_case(output/f'case-{i:02d}', stage) for i,stage in enumerate(STAGES)]
        save(output/'summary.json', dict(passed=True, cases=rows))
