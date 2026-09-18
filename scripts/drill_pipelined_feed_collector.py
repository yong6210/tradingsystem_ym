"""Fixed offline V6 collector load: independent producers and real worker/fsync."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.research.data.durable_capture_log import file_hash, iter_committed
from app.research.data.pipelined_feed_collector import run_bounded
from app.research.data.sealed_feed_pipeline import PipelineLimits
from app.research.data.queued_feed_fixture import QueuedTransport
from app.research.data.reserved_feed_storage import ReservedStorageBudget
from app.research.data.snapshot_feed_audit import audit_epoch
from app.research.foundation.forward_data_contract import load_contract
from tests.incremental_audit_fixture import COMPARABLE
from tests.test_pipelined_feed_collector import fault_factory

CASES = {
    'large_book_200': dict(per_tick=20, capacity=1024, seconds=4, expected='ORIGINAL_DEADLINE'),
    'burst_2000': dict(per_tick=200, capacity=1024, seconds=4, expected='ORIGINAL_DEADLINE'),
    'reconnect_200': dict(per_tick=20, capacity=1024, seconds=4, expected='ORIGINAL_DEADLINE'),
    'overlap_200': dict(per_tick=20, capacity=1024, seconds=4, expected='ORIGINAL_DEADLINE'),
    'archive_failure': dict(per_tick=20, capacity=1024, seconds=3, expected='FATAL_FAILURE'),
    'audit_failure': dict(per_tick=20, capacity=1024, seconds=3, expected='FATAL_FAILURE'),
    'external_queue_overflow': dict(per_tick=2048, capacity=128, seconds=3, expected='FATAL_FAILURE'),
    'parent_commit_stall_650ms': dict(per_tick=20, capacity=1024, seconds=3, expected='FATAL_FAILURE'),
}
NEW_SOURCES = ['app/research/data/sealed_feed_pipeline.py', 'app/research/data/pipelined_feed_collector.py',
               'tests/test_pipelined_feed_collector.py', 'scripts/drill_pipelined_feed_collector.py']
# Bind every local data module, the policy and fixture helpers used by this
# harness; no dependency download, market requests or source rewriting.
SOURCES = sorted(set(NEW_SOURCES + [str(p.relative_to(ROOT)) for p in (ROOT/'app/research/data').glob('*.py')] + [
    'app/research/foundation/forward_data_contract.py', 'configs/research/forward_data_policy_v1.json',
    'tests/incremental_audit_fixture.py', 'tests/sealed_archive_fixture_worker.py',
    'tests/incremental_audit_fixture_worker.py', 'tests/test_bounded_feed_collector.py',
    'tests/test_local_order_book.py', 'tests/test_durable_market_feed.py']))


def save(path, value):
    raw = json.dumps(value, indent=2)+'\n'
    if len(raw) > 4*1024**2:
        raise ValueError('harness result bound')
    with path.open('x') as f:
        f.write(raw)


async def run_case(output, name):
    spec = CASES[name]
    output.mkdir()
    hashes = {p:file_hash(ROOT/p) for p in SOURCES}
    save(output/'plan.json', dict(case=name, spec=spec, source_hashes=hashes,
        snapshot_levels_per_side=1000, capture_cap_bytes=512*1024**2,
        pipeline_limits=dict(seal_seconds=.5), actual_network_requests=0))
    transport = QueuedTransport(per_tick=spec['per_tick'], capacity=spec['capacity'])
    managers, injections, overlap_releases = [], [], []
    release = output/'release'
    def hook(stage):
        if name == 'parent_commit_stall_650ms' and stage == 'after_audit_checkpoint_directory_fsync' and not injections:
            row = dict(started_ns=time.monotonic_ns(), produced_before=sum(s.produced for s in transport.sockets))
            injections.append(row)
            time.sleep(.65)
            row.update(ended_ns=time.monotonic_ns(), produced_after=sum(s.produced for s in transport.sockets))
    def factory(budget, **kwargs):
        manager = fault_factory(archive='crash' if name == 'archive_failure' else None,
            audit='crash' if name == 'audit_failure' else 'gate' if name == 'overlap_200' else None,
            release=release, hook=hook)(budget, **kwargs)
        managers.append(manager)
        return manager
    async def release_overlap():
        async with asyncio.timeout(10):
            while not managers or not managers[0].audit_archive_overlap_samples:
                if managers and managers[0].failed.is_set():
                    return
                await asyncio.sleep(.005)
            overlap_releases.append(dict(released_ns=time.monotonic_ns(),
                produced=sum(s.produced for s in transport.sockets),
                pending_reservations=managers[0].budget.snapshot()['pending_reservations']))
            release.touch()
    original_create = ReservedStorageBudget.create.__func__
    def cap(cls, root, **kwargs):
        return original_create(cls, root, **(kwargs | dict(max_bytes=512*1024**2)))
    unlock = asyncio.create_task(release_overlap()) if name == 'overlap_200' else None
    started, cpu = time.monotonic_ns(), time.process_time_ns()
    try:
        with patch.object(ReservedStorageBudget, 'create', classmethod(cap)):
            result = await run_bounded(output/'capture', duration_ns=spec['seconds']*1_000_000_000,
                transport=transport, policy=load_contract(ROOT/'configs/research/forward_data_policy_v1.json'),
                source_hashes=hashes, pipeline_limits=PipelineLimits(seal_seconds=.5), _pipeline_factory=factory,
                disconnect_once_after_ns=600_000_000 if name == 'reconnect_200' else None)
        if unlock is not None:
            await unlock
    finally:
        if unlock is not None:
            unlock.cancel()
            await asyncio.gather(unlock, return_exceptions=True)
        for socket in transport.sockets:
            if socket.thread.is_alive():
                await socket.close()
    sockets = [s.summary() for s in transport.sockets]
    pipeline = result['pipeline']
    checks = dict(expected_stop=result['stop_reason'] == spec['expected'],
        threads_joined=all(s['producer_thread_joined'] for s in sockets),
        workers_reaped=all(m.process is None and not m.pending for m in managers[0].managers()),
        all_reservations_released=result['storage_after_result']['reserved_bytes'] == 0,
        max_two_reservations=pipeline['peak_reservations'] <= 2,
        original_calendar=result['combined']['quality']['calendar_ns'] == spec['seconds']*1_000_000_000)
    comparisons = []
    raw_frames = 0
    if spec['expected'] == 'ORIGINAL_DEADLINE':
        for e, actual in zip(result['epochs'], result['audits']):
            directory = output/'capture'/e['directory']
            baseline = audit_epoch(directory/'journal', directory/'audit', **result['original_window'], max_intervals=10000)
            comparisons.append({k:actual[k] == baseline[k] for k in COMPARABLE})
            raw_frames += sum(r['payload']['kind'] in ('WS','CLOSING_WS') for r in iter_committed(directory/'journal'))
        checks.update(result_persisted=result['result_persisted'],
            all_epochs_finalized=len(result['epochs']) == len(result['audits']) and not result['errors'],
            full_replay_equal=bool(comparisons) and all(all(r.values()) for r in comparisons),
            large_book_observed=all(e['diagnostics']['sampled_book_levels_peak'] == 2000 for e in result['epochs']),
            no_queue_overflow=all(not s['overflow'] for s in sockets),
            producer_not_throttled=all(s['produced'] >= s['scheduled_by_stop']*.9 for s in sockets),
            frame_accounting=raw_frames == sum(s['received'] for s in sockets),
            produced_accounting=all(s['produced'] == s['received']+s['queued_at_stop'] for s in sockets),
            active_epoch_audit=any(j['completed_ns'] < c['closed_ns'] for c in pipeline['channels'] for j in c['auditor']['jobs']),
            originals_retained=bool(list((output/'capture').glob('epoch-*/journal/segment-*.jsonl'))))
    else:
        checks['quality_rejected'] = result['combined']['quality']['status'] == 'QUALITY_INPUTS_REJECTED'
    if name == 'reconnect_200':
        checks['two_epochs_audited'] = len(result['audits']) == 2 and result['retries_used'] == 1
    if name == 'overlap_200':
        checks['archive_audit_process_overlap'] = bool(overlap_releases and pipeline['audit_archive_overlap_samples'])
        checks['shared_slots_during_overlap'] = bool(overlap_releases and overlap_releases[0]['pending_reservations'] == 2)
    if name == 'external_queue_overflow':
        checks['overflow_detected'] = any(s['overflow'] for s in sockets)
    if name == 'parent_commit_stall_650ms':
        checks['producer_continued_during_parent_stall'] = bool(injections and injections[0]['produced_after'] > injections[0]['produced_before'])
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    row = dict(case=name, passed=all(checks.values()), checks=checks, result=result, sockets=sockets,
        comparisons=comparisons, received_frames_in_raw=raw_frames, injections=injections, overlap_releases=overlap_releases,
        wall_ns=time.monotonic_ns()-started, cpu_ns=time.process_time_ns()-cpu,
        parent_peak_rss_bytes=rss if sys.platform == 'darwin' else rss*1024,
        source_hashes_unchanged=all(file_hash(ROOT/p) == h for p,h in hashes.items()),
        actual_network_requests=0, actual_orders=0, input_rate_certified=False, full_day_ready=False)
    assert row['source_hashes_unchanged']
    save(output/'result.json', row)
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--case', choices=CASES)
    args = parser.parse_args()
    output = args.output.resolve()
    if args.case:
        row = asyncio.run(run_case(output, args.case))
        print(json.dumps(dict(case=args.case, passed=row['passed'], checks=row['checks'])))
        return 0 if row['passed'] else 1
    output.mkdir(parents=True, exist_ok=False)
    save(output/'plan.json', dict(cases=CASES, source_hashes={p:file_hash(ROOT/p) for p in SOURCES},
        case_timeout_seconds=45, run_sequentially=True, real_journal_fsync=True,
        arrival_model='INDEPENDENT_PRODUCER_THREADS_WITH_BOUNDED_QUEUES',
        actual_network_requests=0, actual_orders=0, full_day_ready=False))
    summaries = []
    for name in CASES:
        with (output/(name+'.log')).open('x') as log:
            child = subprocess.Popen([sys.executable, __file__, '--output', str(output/name), '--case', name],
                stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                code = child.wait(timeout=45)
            except BaseException as exc:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.wait()
                if not isinstance(exc, subprocess.TimeoutExpired):
                    raise
                code = 'TIMEOUT'
        path = output/name/'result.json'
        result = json.loads(path.read_text()) if path.exists() else None
        summaries.append(dict(case=name, returncode=code, passed=bool(result and result['passed'] and code == 0),
            checks=result['checks'] if result else None))
    summary = dict(passed=all(r['passed'] for r in summaries), cases=summaries,
        actual_network_requests=0, actual_orders=0, full_day_ready=False)
    save(output/'summary.json', summary)
    print(json.dumps(summary))
    return 0 if summary['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
