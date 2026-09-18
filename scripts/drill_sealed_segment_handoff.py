"""Offline active-writer/read-only-worker overlap and nine actual SIGKILLs."""
import argparse
import dataclasses
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.research.data.durable_capture_log import decoded, file_hash
from app.research.data.shared_feed_storage import SharedStorageBudget
from app.research.data.sealed_segment_handoff import SealedJournal, SealTicket, SegmentCursor, read_segment

STAGES = ('after_seal_close', 'after_raw_fsync', 'after_checkpoint_fsync',
          'after_checkpoint_replace', 'after_directory_fsync', 'after_seal_commit',
          'after_seal_fsync', 'after_seal_replace', 'after_seal_directory_fsync')
CONTRACT = dict(run_id='sealed-drill', max_bytes=8*1024**2, min_free_bytes=0)
SOURCES = ['app/research/data/sealed_segment_handoff.py',
           'app/research/data/shared_feed_storage.py', 'app/research/data/durable_capture_log.py',
           'tests/test_sealed_segment_handoff.py', 'scripts/drill_sealed_segment_handoff.py']


def save(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2); stream.write('\n')


def inventory(root):
    return {str(p.relative_to(root)):file_hash(p) for p in root.rglob('*') if p.is_file()}


def receive(proc):
    if not select.select([proc.stdout], [], [], 10)[0]:
        raise RuntimeError('worker reply deadline')
    line = proc.stdout.readline(16385)
    if len(line) > 16384 or not line.endswith(b'\n'):
        raise RuntimeError('worker reply boundary')
    return json.loads(line)


def send(proc, row):
    data = (json.dumps(row)+'\n').encode()
    if len(data) > 16384: raise RuntimeError('worker request bound')
    proc.stdin.write(data); proc.stdin.flush()


def emit(row):
    print(json.dumps(row), flush=True)


def writer(root):
    disk = SharedStorageBudget.create(root, **CONTRACT)
    log = SealedJournal.create(root/'raw', budget=disk, run_id=CONTRACT['run_id'],
                              rotation_bytes=64*1024, max_record_bytes=2048)
    return disk, log


def crash_child(root, stage):
    disk, log = writer(root)
    for i in range(20): log.append(dict(i=i, data='x'*200))
    def pause(current):
        if current == stage:
            emit(dict(stage=current, pid=os.getpid()))
            while True: signal.pause()
    log.hook = pause
    log.seal()
    raise RuntimeError('crash hook not reached')


def reader_child():
    init = json.loads(sys.stdin.buffer.readline(16385))
    cursor = SegmentCursor(**(init | dict(root=Path(init['root']))))
    emit(dict(ready=True))
    for line in sys.stdin.buffer:
        if len(line) > 16384: raise RuntimeError('request overflow')
        request = json.loads(line)
        if request.get('stop'): break
        ticket = SealTicket(request['certificate'].encode())
        emit(dict(accepted=True))
        gate = json.loads(sys.stdin.buffer.readline(16385))
        if gate != {'go':True}: raise RuntimeError('bad gate')
        before = time.monotonic_ns()
        result = read_segment(ticket, cursor)
        cursor = result.cursor
        emit(dict(sequence=cursor.sequence, count=sum(1 for _ in result.records()),
                  raw_bytes=len(result.raw), verification_ns=time.monotonic_ns()-before))


def reap(proc):
    if proc.poll() is None: proc.kill()
    proc.communicate(timeout=5)


def crashes(output):
    rows = []
    for stage in STAGES:
        case = output/stage; case.mkdir()
        root = case/'capture'
        proc = subprocess.Popen([sys.executable, __file__, '--child-crash', str(root), '--stage', stage],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
        try:
            reached = receive(proc)
            if reached['stage'] != stage: raise RuntimeError('wrong stage')
            proc.kill(); _, stderr = proc.communicate(timeout=5)
            if proc.returncode != -signal.SIGKILL or stderr: raise RuntimeError('unexpected child result')
        finally:
            reap(proc)
        before = inventory(root)
        disk = SharedStorageBudget.resume(root, **CONTRACT)
        log = None
        try:
            log = SealedJournal.resume(root/'raw', budget=disk)
            preserved = all((root/p).is_file() and file_hash(root/p) == h for p,h in before.items())
            if not preserved: raise RuntimeError('recovery altered precrash files')
            cursor = log.initial_cursor()
            for ticket in log.recovered_tickets: cursor = read_segment(ticket, cursor).cursor
            expected = 0 if stage in STAGES[:3] else 20
            if cursor.sequence != expected: raise RuntimeError('recovery committed boundary mismatch')
            log.append(dict(after_restart=True))
            for ticket in log.seal(): cursor = read_segment(ticket, cursor).cursor
            if cursor.sequence != expected+1: raise RuntimeError('restart chain mismatch')
            row = dict(stage=stage, actual_sigkill=True, recovered_sequence=expected,
                recovered_tickets=len(log.recovered_tickets), resumed_sequence=cursor.sequence,
                all_precrash_files_preserved=True, before=before, after=inventory(root), storage=disk.snapshot())
            save(case/'result.json', row); rows.append(row)
        finally:
            if log is not None: log.close()
            disk.close()
    return rows


def overlap(output):
    case = output/'active_writer_worker'; case.mkdir()
    disk, log = writer(case/'capture')
    proc = None
    try:
        for i in range(50): log.append(dict(i=i, phase=1))
        first, = log.seal()
        init = dataclasses.asdict(log.initial_cursor()); init['root'] = str(init['root'])
        proc = subprocess.Popen([sys.executable, __file__, '--reader'], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
        send(proc, init)
        if receive(proc) != {'ready':True}: raise RuntimeError('reader not ready')
        send(proc, dict(certificate=first.certificate.decode()))
        if receive(proc) != {'accepted':True}: raise RuntimeError('ticket not accepted')
        old_path = log.directory/decoded(first.certificate)['segment']['name']
        before = file_hash(old_path)
        # Deterministic overlap: a separate reader owns job 1 while the writer
        # commits/seals job 2. The gate proves there is no journal lock dependency.
        for i in range(50): log.append(dict(i=i, phase=2))
        second, = log.seal()
        writer_sequence_while_reader_pending = log.sequence
        send(proc, dict(go=True)); first_result = receive(proc)
        send(proc, dict(certificate=second.certificate.decode()))
        if receive(proc) != {'accepted':True}: raise RuntimeError('second ticket not accepted')
        log.append(dict(phase=3)); log.commit()  # Journal remains open and mutable.
        send(proc, dict(go=True)); second_result = receive(proc)
        send(proc, dict(stop=True))
        _, stderr = proc.communicate(timeout=5)
        if proc.returncode or stderr: raise RuntimeError('reader failed')
        if first_result['sequence'] != 50 or second_result['sequence'] != 100:
            raise RuntimeError('worker cursor mismatch')
        if before != file_hash(old_path): raise RuntimeError('sealed raw changed')
        row = dict(status='PASS', separate_reader_process=True, reader_exit_code=proc.returncode,
            writer_open_during_both_reads=not log.closed,
            writer_sequence_while_first_reader_pending=writer_sequence_while_reader_pending,
            final_writer_committed_sequence=log.publication_fence().sequence,
            worker_results=[first_result, second_result], first_raw_preserved=True,
            storage=disk.snapshot(), market_collector_integrated=False)
        save(case/'result.json', row)
        return row
    finally:
        if proc is not None: reap(proc)
        log.close(); disk.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path)
    parser.add_argument('--child-crash', type=Path)
    parser.add_argument('--stage', choices=STAGES)
    parser.add_argument('--reader', action='store_true')
    args = parser.parse_args()
    if args.child_crash: return crash_child(args.child_crash, args.stage)
    if args.reader: return reader_child()
    output = args.output.resolve(); output.mkdir(parents=True, exist_ok=False)
    save(output/'plan.json', dict(stages=STAGES, contract=CONTRACT,
        source_hashes={p:file_hash(ROOT/p) for p in SOURCES}, network_requests=0,
        fixture_records=20, overlap_records_per_segment=50,
        child_reply_timeout_seconds=10, child_reply_max_bytes=16384,
        expected_recovery_sequences={s:(0 if s in STAGES[:3] else 20) for s in STAGES}))
    cases = crashes(output)
    concurrent = overlap(output)
    row = dict(status='PASS_SEALED_HANDOFF_PROCESS_CRASH_AND_ACTIVE_WRITER_WORKER',
        actual_sigkill_cases=len(cases), all_precrash_files_preserved=True,
        independent_worker_read_segments=len(concurrent['worker_results']),
        network_requests=0, actual_orders=0, original_deletion=False,
        live_collector_integration=False, full_day_ready=False)
    save(output/'summary.json', row); emit(row)


if __name__ == '__main__': main()
