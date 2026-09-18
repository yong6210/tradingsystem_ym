"""SIGKILL an active mixed-source journal, recover and append a new epoch."""
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
from app.research.data.archive_segment_reader import SegmentReader, segment_ref
from app.research.data.background_segment_archive import BackgroundArchives
from app.research.data.durable_capture_log import file_hash, sync_directory
from app.research.data.reserved_feed_storage import ReservedStorageBudget
from app.research.data.retained_sealed_journal import RetainedSealedJournal
from app.research.data.sealed_segment_handoff import certificate, sha

STAGES = ('custody_intent:after_checkpoint_fsync', 'custody_after_unlink',
          'custody_after_source_directory_fsync', 'custody_done:after_checkpoint_fsync')
CONTRACT = dict(run_id='active-journal-drill', max_bytes=16*1024**2, min_free_bytes=0)


def save(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    sync_directory(path.parent)


def inventory(root):
    return {str(p.relative_to(root)): dict(bytes=p.stat().st_size, sha256=file_hash(p))
            for p in sorted(root.rglob('*')) if p.is_file()}


async def child(output, stage):
    budget = ReservedStorageBudget.create(output/'run', **CONTRACT)
    writer = RetainedSealedJournal.create(budget.root/'raw', budget=budget, run_id=CONTRACT['run_id'],
                                         rotation_bytes=256*1024, max_record_bytes=128*1024)
    try:
        cursor = writer.initial_cursor()
        writer.append(dict(number=1, data='x'*65536))
        ticket, = writer.seal()
        manager = BackgroundArchives(budget.root/'archives', budget=budget, cursor=cursor)
        manager.submit(ticket); rows = await manager.finish()
        ref = segment_ref(ticket, archive_directory='archives', archive_id=rows[0]['archive_id'])
        save(output/'before_admission_hashes.json', inventory(budget.root))
        decision = writer.admit_archive(ticket, ref)
        assert decision['admitted']
        # This segment remains OPEN at the exact instant the earlier source is
        # removed. It is committed but unsealed, exercising mixed recovery.
        writer.append(dict(number=2, data='still writing the next file'))
        writer.commit()
        save(output/'external_handle.json', dict(contract=CONTRACT, handle=writer.handle(), decision=decision))
        save(output/'before_crash_hashes.json', inventory(budget.root))
        def hook(current):
            if current == stage:
                assert writer.active is not None and not writer.active.closed
                assert Path(writer.active.name).name == 'segment-0000001.jsonl'
                print(json.dumps(dict(stage=current, pid=os.getpid(), writer_active=True)), flush=True)
                signal.pause()
                raise RuntimeError('expected SIGKILL')
        writer.hook = hook
        writer.finish_retirement()
        raise RuntimeError('crash stage not reached')
    finally:
        writer.close(); budget.close()


def read_all(writer):
    cursor = writer.initial_cursor(); records = []; sources = []
    for ticket in writer.recovered_tickets:
        name = certificate(ticket.certificate)['segment']['name']
        ref = writer._load(name)['ref'] if name in writer.custody_anchors else segment_ref(ticket)
        result = SegmentReader(budget=writer.budget).read(ref, cursor)
        records.extend(result.records()); cursor = result.cursor
        sources.append('GZIP' if ref['archive'] else 'RAW')
    return records, sources


def recover(output):
    root = output/'run'; stored = json.loads((output/'external_handle.json').read_text())
    crash = inventory(root); save(output/'after_crash_hashes.json', crash)
    budget = ReservedStorageBudget.resume(root, **CONTRACT)
    writer = RetainedSealedJournal.resume(root/'raw', budget=budget, handle=stored['handle'])
    try:
        records, sources = read_all(writer)
        assert [r['sequence'] for r in records] == [1, 2]
        assert [r['payload']['number'] for r in records] == [1, 2]
        assert records[0]['payload']['data'] == 'x'*65536
        assert sources == ['GZIP', 'RAW']
        recovered_prefix = [r['sha256'] for r in records]
        writer.finish_retirement()
        settled = inventory(root)
        assert writer.finish_retirement()['raw_bytes_removed_this_call'] == 0
        assert settled == inventory(root)
        writer.append(dict(number=3, data='continued after process restart'))
        new_ticket, = writer.seal()
        assert certificate(new_ticket.certificate)['segment']['name'] == 'segment-0000002.jsonl'
        handle = writer.handle()
        save(output/'continued_handle.json', dict(contract=CONTRACT, handle=handle))
    finally:
        writer.close(); budget.close()
    before_reopen = inventory(root)
    budget = ReservedStorageBudget.resume(root, **CONTRACT)
    writer = RetainedSealedJournal.resume(root/'raw', budget=budget, handle=handle)
    try:
        records, sources = read_all(writer)
        assert [r['sequence'] for r in records] == [1, 2, 3]
        assert [r['payload']['number'] for r in records] == [1, 2, 3]
        assert [r['sha256'] for r in records[:2]] == recovered_prefix
        assert len({records[0]['epoch'], records[2]['epoch']}) == 2
        assert sources == ['GZIP', 'RAW', 'RAW']
        assert not (root/'raw/segment-0000000.jsonl').exists()
        assert before_reopen == inventory(root)
    finally:
        writer.close(); budget.close()
    before = json.loads((output/'before_crash_hashes.json').read_text()); after = inventory(root)
    removed = sorted(set(before)-set(after))
    assert removed == ['raw/segment-0000000.jsonl']
    # The journal checkpoint legitimately advances for the new record. Every
    # pre-crash source/archive/custody file besides that checkpoint is pinned.
    changed = sorted(p for p in before if p in after and before[p] != after[p])
    assert changed == ['raw/checkpoint.json']
    temps = [p for p in crash if p.endswith('.tmp')]
    assert all(after[p] == crash[p] for p in temps)
    save(output/'after_hashes.json', after)
    save(output/'replay.json', dict(record_hashes=[r['sha256'] for r in records], sources=sources,
                                  sequences=[r['sequence'] for r in records], live_market_state_restored=False))
    return dict(passed=True, active_writer_at_kill=True, mixed_source_recovery=True,
        raw_removed_bytes=before[removed[0]]['bytes'], removed_sources=removed, changed_files=changed,
        preserved_files=len(before)-len(removed)-len(changed), preserved_crash_temporaries=temps,
        recovered_prefix_hashes_unchanged=True, continued_record_sequence=3, new_segment_index=2,
        new_epoch_after_recovery=True, repeated_retirement_no_growth=True, repeated_resume_no_growth=True,
        live_collector_integrated=False, historical_sources_changed=False, actual_orders=0)


def run_case(output, stage):
    output.mkdir()
    child_process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--output', str(output), '--stage', stage],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True, cwd=ROOT,
        env=os.environ | {'PYTHONDONTWRITEBYTECODE': '1'})
    try:
        with selectors.DefaultSelector() as watch:
            watch.register(child_process.stdout, selectors.EVENT_READ)
            if not watch.select(20): raise RuntimeError('crash stage timeout')
            line = child_process.stdout.readline(4097)
        if not line or len(line) > 4096:
            raise RuntimeError('missing crash stage: '+child_process.stderr.read(8192).decode())
        assert json.loads(line) == dict(stage=stage, pid=child_process.pid, writer_active=True)
        child_process.kill(); child_process.wait(timeout=3)
        assert child_process.returncode == -9
        stdout, stderr = child_process.communicate(timeout=3); assert not stdout
        (output/'child_stderr.log').write_bytes(stderr)
    finally:
        if child_process.poll() is None: child_process.kill(); child_process.wait(timeout=3)
        try: os.killpg(child_process.pid, signal.SIGKILL)
        except ProcessLookupError: pass
    row = recover(output) | dict(stage=stage, parent_sigkill_returncode=child_process.returncode)
    save(output/'verification.json', row); print(json.dumps(row), flush=True)
    return row


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--stage', choices=STAGES); args = parser.parse_args(); output = args.output.resolve()
    if args.stage: asyncio.run(child(output, args.stage))
    else:
        output.mkdir()
        save(output/'plan.json', dict(stages=STAGES, contract=CONTRACT, synthetic_only=True,
            live_collector_integrated=False, public_requests=0, source_hashes={p:file_hash(ROOT/p) for p in (
                'app/research/data/retained_sealed_journal.py', 'scripts/drill_retained_sealed_journal.py')}))
        rows = [run_case(output/f'case-{i:02d}', stage) for i,stage in enumerate(STAGES)]
        save(output/'summary.json', dict(passed=True, cases=rows))
