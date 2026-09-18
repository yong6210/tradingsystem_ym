"""Fixed offline large-book/independent-producer cases, real journal fsync."""
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
from app.research.data.background_feed_audit import BackgroundAudits
from app.research.data.background_feed_collector import run_bounded
from app.research.data.durable_capture_log import file_hash
from app.research.data.queued_feed_fixture import QueuedTransport
from app.research.data.shared_feed_storage import BudgetedJournal, SharedStorageBudget
from app.research.data.feed_storage_envelope import capture_sample
from app.research.foundation.forward_data_contract import load_contract
from scripts.probe_background_feed import SOURCES as COLLECTOR_SOURCES

CASES = {
    'large_book_200': dict(per_tick=20, capacity=1024, seconds=4, expected='ORIGINAL_DEADLINE'),
    'concurrent_audit_200': dict(per_tick=20, capacity=1024, seconds=8, expected='ORIGINAL_DEADLINE'),
    'burst_2000': dict(per_tick=200, capacity=1024, seconds=4, expected='ORIGINAL_DEADLINE'),
    'external_queue_overflow': dict(per_tick=2048, capacity=128, seconds=4, expected='FATAL_FAILURE'),
    'commit_stall_650ms': dict(per_tick=20, capacity=1024, seconds=4, expected='FATAL_FAILURE'),
}
SOURCES = [*COLLECTOR_SOURCES, 'app/research/data/queued_feed_fixture.py',
    'app/research/data/feed_storage_envelope.py', 'scripts/drill_queued_feed_load.py',
    'scripts/load_audit_fixture_worker.py']


def save(path, value):
    data = json.dumps(value, indent=2)+'\n'
    if len(data) > 2*1024**2: raise ValueError('bounded harness result')
    with path.open('x') as stream: stream.write(data)


async def run_case(output, name):
    spec = CASES[name]
    output.mkdir()
    hashes = {name:file_hash(ROOT/name) for name in SOURCES}
    save(output/'plan.json', dict(case=name, spec=spec, source_hashes=hashes,
        snapshot_levels_per_side=1000, depth_tick_ns=100_000_000,
        capture_cap_bytes=512*1024**2, actual_network_requests=0))
    managers, gate_observations, injections = [], [], []
    def release():
        if name == 'concurrent_audit_200':
            gate_observations.append(dict(released_ns=time.monotonic_ns(),
                previous_job_status=managers[0].jobs[0]['status']))
            (output/'release').touch()
    transport = QueuedTransport(per_tick=spec['per_tick'], capacity=spec['capacity'], on_second_snapshot=release)
    def factory(**kwargs):
        def command(request):
            if name == 'concurrent_audit_200' and request['job_id'] == 0:
                return [sys.executable, str(ROOT/'scripts/load_audit_fixture_worker.py'),
                        json.dumps(request), str(output/'release')]
            return [sys.executable, '-m', 'app.research.data.background_audit_worker', json.dumps(request)]
        obj = BackgroundAudits(**kwargs, _command=command)
        managers.append(obj)
        return obj
    original_commit = BudgetedJournal.commit
    original_create = SharedStorageBudget.create.__func__
    def cap(cls, root, **kwargs):
        kwargs['max_bytes'] = 512*1024**2
        return original_create(cls, root, **kwargs)
    def commit(writer):
        if name == 'commit_stall_650ms' and not injections and writer.directory.name == 'journal' and writer.sequence > 100:
            row = dict(started_ns=time.monotonic_ns(), produced_before=sum(s.produced for s in transport.sockets))
            injections.append(row)
            time.sleep(.65)
            row.update(ended_ns=time.monotonic_ns(), produced_after=sum(s.produced for s in transport.sockets))
        return original_commit(writer)
    start, cpu = time.monotonic_ns(), time.process_time_ns()
    try:
        with patch.object(SharedStorageBudget, 'create', classmethod(cap)), patch.object(BudgetedJournal, 'commit', commit):
            result = await run_bounded(output/'capture', duration_ns=spec['seconds']*1_000_000_000,
                transport=transport, policy=load_contract(ROOT/'configs/research/forward_data_policy_v1.json'),
                source_hashes=hashes, _audit_factory=factory,
                disconnect_once_after_ns=2_000_000_000 if name == 'concurrent_audit_200' else None)
    finally:
        for socket in transport.sockets:
            if socket.thread.is_alive(): await socket.close()
    sockets = [s.summary() for s in transport.sockets]
    checks = dict(expected_stop=result['stop_reason'] == spec['expected'],
        threads_joined=all(s['producer_thread_joined'] for s in sockets),
        auditor_reaped=result['background_audit']['child_reaped'], result_persisted=result['result_persisted'],
        calendar_preserved=result['original_window']['window_end_ns']-result['original_window']['window_start_ns'] == spec['seconds']*1_000_000_000)
    if spec['expected'] == 'ORIGINAL_DEADLINE':
        checks.update(audits_complete=len(result['audits']) == len(result['epochs']) and not result['errors'],
            large_book_observed=all(e['diagnostics']['sampled_book_levels_peak'] == 2000 for e in result['epochs']),
            queues_not_overflowed=all(not s['overflow'] for s in sockets),
            producer_not_throttled=all(s['produced'] >= s['scheduled_by_stop']*.9 for s in sockets),
            positive_observations=all(e['eligible_point_observations'] > 0 for e in result['epochs']))
    else:
        checks['quality_rejected'] = result['combined'] is None or result['combined']['quality']['status'] == 'QUALITY_INPUTS_REJECTED'
    if name == 'concurrent_audit_200':
        checks['audit_released_in_second_epoch'] = bool(gate_observations and
            gate_observations[0]['previous_job_status'] == 'RUNNING' and
            result['background_audit']['jobs'][0]['completed_ns'] > gate_observations[0]['released_ns'])
    if name == 'external_queue_overflow': checks['overflow_detected'] = any(s['overflow'] for s in sockets)
    if name == 'commit_stall_650ms':
        checks['producer_continued_during_stall'] = bool(injections and injections[0]['produced_after'] > injections[0]['produced_before'])
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    sample = capture_sample(output/'capture', result) if spec['expected'] == 'ORIGINAL_DEADLINE' and all(checks.values()) else None
    row = dict(case=name, passed=all(checks.values()), checks=checks, result=result, sockets=sockets,
        gate_observations=gate_observations, injections=injections, storage_sample=sample,
        wall_ns=time.monotonic_ns()-start, cpu_ns=time.process_time_ns()-cpu,
        parent_peak_rss_bytes=rss if sys.platform=='darwin' else rss*1024,
        actual_network_requests=0, actual_orders=0, input_rate_certified=False, full_day_ready=False)
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
    save(output/'plan.json', dict(cases=CASES, source_hashes={name:file_hash(ROOT/name) for name in SOURCES},
        worker_deadline_seconds=45, run_sequentially=True, real_journal_fsync=True,
        queue_arrival_model='INDEPENDENT_THREAD_FIXED_SCHEDULE_CATCH_UP_OVERFLOW_FATAL',
        actual_network_requests=0, actual_orders=0, full_day_ready=False))
    summaries = []
    for name in CASES:
        with (output/(name+'.log')).open('x') as log:
            with subprocess.Popen([sys.executable, __file__, '--output', str(output/name), '--case', name],
                    stdout=log, stderr=subprocess.STDOUT, start_new_session=True) as child:
                try:
                    code = child.wait(timeout=45)
                except BaseException as exc:
                    try: os.killpg(child.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                    child.wait()
                    if not isinstance(exc, subprocess.TimeoutExpired): raise
                    code = 'TIMEOUT'
        path = output/name/'result.json'
        result = json.loads(path.read_text()) if path.exists() else None
        summaries.append(dict(case=name, returncode=code, passed=bool(result and result['passed'] and code == 0),
                              checks=result['checks'] if result else None))
    save(output/'summary.json', dict(passed=all(row['passed'] for row in summaries), cases=summaries,
                                    actual_network_requests=0, full_day_ready=False))
    print(json.dumps(summaries))
    return 0 if all(row['passed'] for row in summaries) else 1


if __name__ == '__main__': raise SystemExit(main())
