"""Offline SIGKILL boundary drills and archived-capture storage roundtrip."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.research.data.durable_capture_log import DurableCaptureLog, inspect_journal, iter_committed
from app.research.data.depth_capture import DepthCaptureProcessor

STAGES = ('after_append', 'after_raw_fsync', 'after_checkpoint_fsync',
          'after_checkpoint_replace', 'after_directory_fsync', 'after_commit_return', 'torn_append')


def dump(path, value):
    path.write_text(json.dumps(value, indent=2)+'\n')


def kill_worker(directory, stage, rotated):
    armed = False
    def stop(point):
        if armed and point == stage:
            dump(directory.parent/'kill_marker.json', dict(stage=stage, rotated=rotated,
                 acknowledged_sequence=writer.receipt.sequence, attempted_sequence=writer.sequence))
            os.kill(os.getpid(), signal.SIGKILL)
    with DurableCaptureLog.create(directory, run_id='synthetic-crash', rotation_bytes=1024,
            max_record_bytes=700, max_total_bytes=100_000, min_free_bytes=0, hook=stop) as writer:
        padding = 'x'*280 if rotated else ''
        writer.append(dict(label='first', padding=padding))
        writer.commit()
        armed = True
        if stage == 'torn_append':
            # A deliberately torn, uncommitted append; no production parser sees it.
            writer.active.write(b'{"sequence":2,"payload":')
            os.fsync(writer.active.fileno())
            stop('torn_append')
        writer.append(dict(label='second', padding=padding))
        writer.commit()
        stop('after_commit_return')
    raise AssertionError('kill stage was not reached')


def crash_case(output, stage, rotated):
    case = output/(stage+('_rotated' if rotated else '_same_segment'))
    case.mkdir()
    journal = case/'journal'
    command = [sys.executable, str(Path(__file__).resolve()), '--worker', str(journal), '--stage', stage]
    if rotated:
        command.append('--rotated')
    child = subprocess.run(command, capture_output=True, text=True, timeout=10)
    if child.returncode != -signal.SIGKILL:
        raise AssertionError(f'child did not die at requested boundary: {child.returncode} {child.stderr}')
    marker = json.loads((case/'kill_marker.json').read_text())
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in journal.glob('segment-*.jsonl')}
    recovery = inspect_journal(journal)
    expected = 2 if stage in ('after_checkpoint_replace', 'after_directory_fsync', 'after_commit_return') else 1
    assert recovery['last_sequence'] == expected
    assert marker['acknowledged_sequence'] == (2 if stage == 'after_commit_return' else 1)
    assert bool(recovery['uncommitted_suffixes']) == (expected == 1)
    if stage == 'after_checkpoint_fsync':
        assert recovery['pending_checkpoint_files']
    rows = list(iter_committed(journal))
    assert [r['payload']['label'] for r in rows] == ['first', 'second'][:expected]
    with DurableCaptureLog.resume(journal) as writer:
        assert writer.publication_fence().sequence == expected
        writer.append(dict(label='resumed'))
        writer.commit()
    rows_after = list(iter_committed(journal))
    assert [r['sequence'] for r in rows_after] == list(range(1, expected+2))
    assert rows_after[-1]['payload']['label'] == 'resumed'
    assert all(hashlib.sha256((journal/name).read_bytes()).hexdigest() == h for name, h in before.items())
    result = dict(stage=stage, rotation_requested=rotated, child_exit_code=child.returncode,
                  acknowledged_before_crash=marker['acknowledged_sequence'],
                  recovered_sequence=expected, sequence_after_resume=expected+1,
                  original_raw_files_unchanged=True, recovery=recovery,
                  status='PASS_LOCAL_PROCESS_CRASH')
    dump(case/'result.json', result)
    return result


def archive_roundtrip(output):
    source = ROOT/'reports/validation/public_depth_reconnect_v2_20260917'
    capture = source/'capture.jsonl'
    expected_digest = '351ffbac9315bbaa3e710a4f3b4887c7211e093db4de212c62786fd58e0054bc'
    assert hashlib.sha256(capture.read_bytes()).hexdigest() == expected_digest
    directory = output/'archive_roundtrip'
    with DurableCaptureLog.create(directory, run_id='archived-depth-roundtrip', rotation_bytes=128*1024,
            max_record_bytes=120*1024, max_total_bytes=16*1024**2, min_free_bytes=0) as writer:
        with capture.open() as stream:
            for count, line in enumerate(stream, 1):
                writer.append(json.loads(line))
                if count % 100 == 0:
                    writer.commit()
        writer.commit()
    processor = DepthCaptureProcessor()
    for record in iter_committed(directory):
        processor.apply(record['payload'])
    expected_quotes = [json.loads(line) for line in (source/'online_quotes.jsonl').read_text().splitlines()]
    expected_results = [json.loads(line) for line in (source/'processing_results.jsonl').read_text().splitlines()]
    expected_summary = json.loads((source/'session_summary.json').read_text())
    assert processor.quotes == expected_quotes
    assert processor.results == expected_results
    assert processor.summary() == expected_summary
    state = inspect_journal(directory)
    assert not state['uncommitted_suffixes']
    result = dict(status='PASS_ARCHIVED_STORAGE_ROUNDTRIP', original_raw_sha256=expected_digest,
                  records=count, quotes=len(processor.quotes), committed_segments=state['committed_segments'],
                  exact_payload_replay=True, live_timing_calibration=False, new_market_capture=False)
    dump(output/'archive_roundtrip.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--worker', type=Path)
    parser.add_argument('--stage', choices=STAGES)
    parser.add_argument('--rotated', action='store_true')
    args = parser.parse_args()
    if args.worker:
        kill_worker(args.worker, args.stage, args.rotated)
        return
    if args.output is None:
        parser.error('--output required')
    args.output.mkdir(parents=True, exist_ok=False)
    cases = [crash_case(args.output, stage, rotated) for rotated in (False, True) for stage in STAGES]
    archive = archive_roundtrip(args.output)
    result = dict(status='PASS_OFFLINE_DURABLE_CAPTURE_DRILLS', killed_child_processes=len(cases),
                  crash_cases=cases, archive=archive, actual_orders=0, private_requests=0, network_requests=0,
                  limitations=['Local process SIGKILL, not a power-cut/filesystem/controller durability test.',
                               'Recovered rename-visible commit may exceed last acknowledged sequence.',
                               'No live collector integration, watchdog cadence or timing guarantee.'])
    dump(args.output/'drill_summary.json', result)
    print(json.dumps(dict(status=result['status'], killed_child_processes=len(cases), archive=archive), indent=2))


if __name__ == '__main__':
    main()
