"""Eight actual process kills and closed-public-segment archive equivalence."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import select
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.research.data.durable_capture_log import decoded, file_hash, sync_directory
from app.research.data.segment_archive import SegmentArchive
from app.research.data.shared_feed_storage import SharedStorageBudget, BudgetedJournal

STAGES = ('after_archive_chunk', 'after_archive_fsync', 'after_archive_verify',
          'after_archive_rename', 'after_archive_directory_fsync',
          'after_manifest_fsync', 'after_manifest_replace', 'after_manifest_directory_fsync')
CONTRACT = dict(run_id='archive-crash-fixture', max_bytes=4*1024**2, min_free_bytes=0)
SOURCES = ['app/research/data/segment_archive.py', 'app/research/data/shared_feed_storage.py',
           'app/research/data/durable_capture_log.py', 'app/research/data/verified_journal_view.py',
           'tests/test_segment_archive.py', 'scripts/drill_segment_archive.py']


def save(path, row):
    data = json.dumps(row, indent=2)+'\n'
    if len(data) > 2*1024**2: raise ValueError('harness artifact bound')
    with path.open('x') as stream: stream.write(data)


def files(root):
    return {str(p.relative_to(root)):file_hash(p) for p in root.rglob('*') if p.is_file()}


def child(root, stage):
    disk = SharedStorageBudget.create(root, **CONTRACT)
    raw = BudgetedJournal.create(root/'raw', budget=disk, run_id=CONTRACT['run_id'],
                                rotation_bytes=1024**2, max_record_bytes=2048)
    rng = random.Random(19)
    for i in range(300): raw.append(dict(index=i, text=rng.randbytes(200).hex()))
    raw.commit(); raw.close()
    archive = SegmentArchive(root/'archives', budget=disk)
    def stop(actual):
        if actual == stage:
            print('READY', flush=True)
            while True: time.sleep(1)
    archive.publish(root/'raw', 'segment-0000000.jsonl', hook=stop)
    raise AssertionError('stage not reached')


def crash_case(directory, stage):
    directory.mkdir()
    root = directory/'capture'
    proc = subprocess.Popen([sys.executable, __file__, '--child', str(root), '--stage', stage],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        if not select.select([proc.stdout], [], [], 15)[0]: raise TimeoutError('crash stage readiness')
        ready = proc.stdout.readline()
        if ready.strip() != 'READY': raise RuntimeError('child failed before hook')
        proc.kill()
        stdout, stderr = proc.communicate(timeout=5)
    finally:
        if proc.poll() is None: proc.kill(); proc.wait(timeout=5)
    (directory/'child.log').write_text(ready+stdout+stderr)
    assert proc.returncode == -signal.SIGKILL
    before = files(root)
    disk = SharedStorageBudget.resume(root, **CONTRACT)
    archive = SegmentArchive(root/'archives', budget=disk)
    recovery = archive.recover()
    expected = int(stage in ('after_manifest_replace', 'after_manifest_directory_fsync'))
    assert len(recovery['registered']) == expected
    assert before == files(root)  # Recovery fsyncs; never rewrites/adopts/deletes.
    inventory = sum(p.stat().st_size for p in root.rglob('*') if p.is_file())
    assert disk.used == inventory
    if expected:
        row = recovery['registered'][0]
        restored = b''.join(archive.read_chunks(row['archive_id']))
        assert hashlib.sha256(restored).hexdigest() == file_hash(root/'raw/segment-0000000.jsonl')
    old_unregistered = recovery['unregistered_files']
    published = archive.publish(root/'raw', 'segment-0000000.jsonl')
    recovered_again = archive.recover()
    assert len(recovered_again['registered']) == 1
    assert recovered_again['unregistered_files'] == old_unregistered
    assert all(file_hash(root/p) == h for p,h in before.items())
    assert hashlib.sha256(b''.join(archive.read_chunks(published['archive_id']))).hexdigest() == published['identity']['raw_sha256']
    row = dict(stage=stage, exit_code=proc.returncode, recovered_registered=expected,
        first_recovery=recovery, after_explicit_retry=recovered_again,
        all_precrash_files_preserved=True, budget_counts_uncertain_files=True,
        retry_verified=True, live_market_state_restored=False)
    disk.close()
    save(directory/'result.json', row)
    return row


def copy_budgeted(source, target, budget):
    target.mkdir(parents=True)
    for path in sorted(source.iterdir()):
        if not path.is_file() or path.is_symlink(): raise ValueError('regular source files required')
        destination = target/path.name
        with path.open('rb') as reader, destination.open('xb', buffering=0) as writer:
            while data := reader.read(64*1024): budget.append(writer, data)
            os.fsync(writer.fileno())
    sync_directory(target)


def public_case(directory):
    directory.mkdir()
    source = ROOT/'reports/validation/feed_scale_20260918/public_60s/capture'
    source_hashes = files(source)
    plan = json.loads((source/'plan.json').read_text())
    disk = SharedStorageBudget.create(directory/'capture', run_id=plan['run_id'],
                                     max_bytes=64*1024**2, min_free_bytes=0)
    archive = SegmentArchive(disk.root/'archives', budget=disk)
    rows = []
    for epoch in sorted(source.glob('epoch-*')):
        for kind in ('journal', 'audit'):
            target = disk.root/epoch.name/kind
            copy_budgeted(epoch/kind, target, disk)
            for segment in sorted(target.glob('segment-*.jsonl')):
                row = archive.publish(target, segment.name)
                restored = b''.join(archive.read_chunks(row['archive_id']))
                assert restored == segment.read_bytes()
                records = [decoded(line) for line in restored.splitlines()[1:]]
                assert records[0]['sequence'] == row['witness']['first_sequence']
                assert records[-1]['sequence'] == row['witness']['last_sequence']
                assert records[-1]['sha256'] == row['witness']['last_record_sha256']
                rows.append(dict(journal=str(target.relative_to(disk.root)), archive=row,
                    restored_record_count=len(records), all_bytes_equal=True))
    recovery = archive.recover()
    assert recovery['catalog_complete']
    assert source_hashes == files(source)
    assert disk.used == sum(p.stat().st_size for p in disk.root.rglob('*') if p.is_file())
    storage = disk.snapshot(); disk.close()
    result = dict(status='ARCHIVE_REGISTRATION_AND_VERIFIED_READ_EQUAL', source=str(source.relative_to(ROOT)),
        source_hashes=source_hashes, rows=rows, recovery=recovery, storage=storage,
        originals_preserved=True, new_market_capture=False, actual_orders=0)
    save(directory/'result.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--child', type=Path)
    parser.add_argument('--stage', choices=STAGES)
    args = parser.parse_args()
    if args.child:
        child(args.child.resolve(), args.stage)
        return
    if not args.output: parser.error('--output required')
    output = args.output.resolve(); output.mkdir(parents=True, exist_ok=False)
    save(output/'plan.json', dict(stages=STAGES, source_hashes={p:file_hash(ROOT/p) for p in SOURCES},
        crash_fixture_contract=CONTRACT, maximum_archive_segment_bytes=8*1024**2,
        original_deletion_implemented=False, actual_orders=0, network_requests=0))
    cases = [crash_case(output/stage, stage) for stage in STAGES]
    public = public_case(output/'public_archive')
    summary = dict(status='PASS_PROCESS_CRASH_ARCHIVE_REGISTRATION', crash_cases=len(cases),
        actual_sigkill_count=len(cases), public_segments=len(public['rows']),
        public_records=sum(r['restored_record_count'] for r in public['rows']),
        all_source_bytes_preserved=True, new_market_capture=False, live_collector_integration=False,
        original_deletion_implemented=False, disk_space_reclaimed_bytes=0,
        full_day_ready=False, actual_orders=0, network_requests=0)
    save(output/'summary.json', summary)
    print(json.dumps(summary))


if __name__ == '__main__': main()
