"""Fixed same-session qualification and actual parent SIGKILL, offline only."""
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
from app.research.data.continuous_generation_capture import run_synthetic_capture
from app.research.data.durable_capture_log import decoded, encoded, file_hash, sync_directory
from app.research.data.feed_coverage_audit import combine_epochs
from app.research.data.queued_feed_fixture import QueuedTransport
from app.research.data.read_generation_capture import replay_capture
from tests.incremental_audit_fixture import COMPARABLE
from tests.test_continuous_generation_capture import reference_replay
from tests.test_retained_feed_collector import inventory

STAGES = ('end:after_checkpoint_fsync', 'end:after_checkpoint_replace',
          'seed:after_checkpoint_fsync', 'start:after_checkpoint_replace',
          'handoff:after_checkpoint_replace', 'handoff:acknowledged')


def save(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2); stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    sync_directory(path.parent)


async def capacity(output):
    output.mkdir()
    root = output/'run'
    save(output/'plan.json', dict(duration_seconds=40, rotation_seconds=8, seal_seconds=.5,
        per_tick=20, levels_per_side=1000, target_sealed_units_above=62,
        normal_rotation_reconnects=0, extra_snapshot_requests=0, no_cadence_search=True,
        synthetic_only=True, compression_integrated=False, full_day_ready=False))
    closed = {}
    def hook(stage):
        if stage == 'handoff:acknowledged':
            for name, hashes in closed.items(): assert inventory(root/name) == hashes
            for directory in root.glob('generation-*'):
                if directory.is_dir() and (directory/'handoff.json').exists():
                    closed[directory.name] = inventory(directory)
    transport = QueuedTransport(per_tick=20)
    result = await run_synthetic_capture(root, duration_ns=40*10**9, rotation_ns=8*10**9,
                                         transport=transport, hook=hook)
    save(output/'result.json', result)
    assert result['outcome'] == 'ORIGINAL_DEADLINE', result
    assert result['total_units'] > 62 and result['peak_units_per_generation'] <= 18
    assert len(transport.connections) == 2 and transport.snapshots == 1
    assert result['handoffs'] == 4 and result['generations'] == 5
    assert result['max_handoff_ns'] <= 500_000_000
    counts = result['counts']
    assert counts['OPEN'] == 2 and counts['SNAPSHOT'] == counts['RUN_WINDOW'] == counts['STOP'] == 1
    before = inventory(root)
    actual, expected = reference_replay(root, output/'reference')
    assert actual['status'] == 'COMPLETE' and actual['audit'] == result['audit']
    for field in COMPARABLE: assert encoded(actual['audit'][field]) == encoded(expected[field]), field
    repeated = replay_capture(root, plan_sha256=file_hash(root/'generation-plan.json'))
    assert actual == repeated and inventory(root) == before
    for name, hashes in closed.items(): assert inventory(root/name) == hashes
    persisted = dict(public=0, market=0)
    publication_times = []
    def count(row):
        payload = row['payload']
        if payload['kind'] in ('WS','CLOSING_WS'): persisted[payload['channel']] += 1
    replay_capture(root, plan_sha256=file_hash(root/'generation-plan.json'), raw_sink=count,
                   audit_sink=lambda batch: publication_times.append(batch['observation']['published_ns']))
    producer = [s.summary() for s in transport.sockets]
    for row in producer:
        assert row['producer_thread_joined'] and not row['overflow']
        assert row['received'] == persisted[row['channel']]
        assert row['produced'] == row['received']+row['queued_at_stop']
    owned_bytes = sum(size for size, _ in before.values())
    assert owned_bytes == result['storage']['used_bytes']
    costs = dict(raw_jsonl=0, audit_jsonl=0, metadata_and_temporary=0)
    for name, (size, _) in before.items():
        category = 'raw_jsonl' if '/raw/' in name and name.endswith('.jsonl') else 'audit_jsonl' if '/audit/' in name and name.endswith('.jsonl') else 'metadata_and_temporary'
        costs[category] += size
    scope = {k:result['audit'][k] for k in ('window_start_ns','window_end_ns','clock_domain')}
    policy = decoded((ROOT/'configs/research/forward_data_policy_v1.json').read_bytes())
    combined = combine_epochs(policy, [actual['audit']], **scope)
    save(output/'quality.json', combined)
    save(output/'recovered.json', actual); save(output/'reference_audit.json', expected)
    save(output/'producer.json', producer); save(output/'costs.json', costs)
    save(output/'completed_generation_hashes.json', closed); save(output/'final_hashes.json', before)
    result = dict(passed=True, generations=result['generations'], sealed_units=result['total_units'],
        peak_units_per_generation=result['peak_units_per_generation'], handoffs=result['handoffs'],
        max_handoff_ns=result['max_handoff_ns'], max_publication_spacing_ns=max(b-a for a,b in zip(publication_times,publication_times[1:])),
        synthetic_connections=2, synthetic_snapshots=1, rotation_reconnects=0, additional_snapshots=0,
        semantic_fields_compared=17, dequeued_frames_equal_persisted_frames=True,
        immutable_completed_generations=True, repeated_recovery_no_growth=True, shared_capture_bytes=owned_bytes,
        original_calendar_preserved=True, continuous_runtime_coverage_certified=False,
        actual_quality=combined['quality'], full_day_ready=False, public_requests=0, actual_orders=0)
    save(output/'summary.json', result)
    return result


async def child(output, stage):
    root = output/'run'
    ended = False
    def hook(current):
        nonlocal ended
        if current == 'end:after_directory_fsync': ended = True
        if current != stage or (stage.startswith(('seed:', 'start:')) and not ended): return
        save(output/'plan_anchor.json', dict(plan_sha256=file_hash(root/'generation-plan.json')))
        save(output/'before_crash_hashes.json', inventory(root))
        print(json.dumps(dict(stage=stage, pid=os.getpid())), flush=True)
        signal.pause()
        raise RuntimeError('expected SIGKILL')
    await run_synthetic_capture(root, duration_ns=3*10**9, rotation_ns=10**9,
                                transport=QueuedTransport(), hook=hook)
    raise RuntimeError('crash stage not reached')


def recover(output, repeat):
    root = output/'run'
    before = inventory(root)
    anchor = decoded((output/'plan_anchor.json').read_bytes())
    result = replay_capture(root, **anchor)
    assert result['status'] == 'INTERRUPTED_PREFIX_PRESERVED'
    assert inventory(root) == before and result['public_requests'] == 0
    save(output/('repeat.json' if repeat else 'recovery.json'), result)


def crash_case(output, stage):
    output.mkdir()
    command = [sys.executable, str(Path(__file__).resolve()), '--output', str(output)]
    process = subprocess.Popen(command+['--child', stage], cwd=ROOT, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, start_new_session=True)
    try:
        with selectors.DefaultSelector() as watch:
            watch.register(process.stdout, selectors.EVENT_READ)
            if not watch.select(20): raise RuntimeError('generation crash stage timeout')
            line = process.stdout.readline(4097)
        if not line or len(line) > 4096: raise RuntimeError(process.stderr.read().decode())
        ready = json.loads(line); assert ready['stage'] == stage
        os.kill(process.pid, signal.SIGKILL); process.wait(timeout=10)
        assert process.returncode == -9
        save(output/'signal.json', ready | dict(returncode=process.returncode))
    finally:
        if process.poll() is None: os.killpg(process.pid, signal.SIGKILL); process.wait(timeout=10)
        process.stdout.close(); process.stderr.close()
    before = inventory(output/'run')
    for flag in ('--recover', '--repeat'):
        p = subprocess.run(command+[flag], cwd=ROOT, capture_output=True, text=True, timeout=30)
        save(output/(flag[2:]+'_process.json'), dict(returncode=p.returncode, stdout=p.stdout, stderr=p.stderr))
        assert p.returncode == 0, p.stderr
        assert inventory(output/'run') == before
    first = decoded((output/'recovery.json').read_bytes()); second = decoded((output/'repeat.json').read_bytes())
    assert first == second
    save(output/'final_hashes.json', before)
    return dict(passed=True, stage=stage, parent_sigkill_returncode=-9, recovery_no_growth=True,
                repeated_recovery_identical=True, recovered_generations=len(first['generations']),
                original_window_preserved=True, public_requests=0, live_market_state_restored=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--child', choices=STAGES); parser.add_argument('--recover', action='store_true')
    parser.add_argument('--repeat', action='store_true'); args = parser.parse_args()
    if args.child: asyncio.run(child(args.output, args.child))
    elif args.recover or args.repeat: recover(args.output, args.repeat)
    else:
        args.output.mkdir()
        normal = asyncio.run(capacity(args.output/'capacity')); print(json.dumps(normal), flush=True)
        cases = []
        for i, stage in enumerate(STAGES):
            row = crash_case(args.output/f'crash-{i:02d}', stage); cases.append(row); print(json.dumps(row), flush=True)
        save(args.output/'summary.json', dict(passed=True, capacity=normal, crashes=cases,
            public_requests=0, private_requests=0, actual_orders=0, full_day_ready=False))
