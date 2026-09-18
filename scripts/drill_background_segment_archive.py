"""Offline archive qualification: eight parent kills, a worker kill, and load."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import random
import select
import signal
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.research.data.background_segment_archive import BackgroundArchives, ArchiveLimits
from app.research.data.durable_capture_log import JournalError, file_hash
from app.research.data.reserved_feed_storage import ReservedStorageBudget
from app.research.data.sealed_segment_handoff import SealedJournal, MAX_SEGMENT_BYTES
from app.research.data.segment_archive import SegmentArchive

STAGES=('after_parent_archive_chunk','after_parent_archive_fsync','after_parent_archive_verify',
        'after_parent_archive_rename','after_parent_archive_directory_fsync',
        'after_parent_manifest_fsync','after_parent_manifest_replace','after_parent_manifest_directory_fsync')
CONTRACT=dict(run_id='background-archive-drill',max_bytes=64*1024**2,min_free_bytes=0)
SOURCES=['app/research/data/reserved_feed_storage.py','app/research/data/sealed_archive_worker.py',
         'app/research/data/background_segment_archive.py','app/research/data/sealed_segment_handoff.py',
         'app/research/data/segment_archive.py','app/research/data/shared_feed_storage.py',
         'app/research/data/durable_capture_log.py','app/research/data/verified_journal_view.py',
         'tests/sealed_archive_fixture_worker.py','tests/test_background_segment_archive.py',
         'scripts/drill_background_segment_archive.py']


def save(path,value):
    with path.open('x') as f:json.dump(value,f,indent=2);f.write('\n')


def files(root):return {str(p.relative_to(root)):file_hash(p) for p in root.rglob('*') if p.is_file()}


def create(root):
    disk=ReservedStorageBudget.create(root,**CONTRACT)
    writer=SealedJournal.create(root/'raw',budget=disk,run_id=CONTRACT['run_id'],
                                rotation_bytes=MAX_SEGMENT_BYTES,max_record_bytes=16384)
    return disk,writer


def batch(writer,count=50,width=100,seed=29):
    rng=random.Random(seed)
    for i in range(count):writer.append(dict(i=i,text=rng.randbytes(width).hex()))
    ticket,=writer.seal()
    return ticket


async def until(predicate):
    async with asyncio.timeout(10):
        while not predicate():await asyncio.sleep(.01)


async def crash_child(root,stage):
    disk,writer=create(root);ticket=batch(writer)
    manager=None
    def pause(current):
        if current==stage:
            job=manager.jobs[0]
            print(json.dumps(dict(stage=stage,worker_pid=job['pid'],worker_returncode=job['returncode'],
                                  worker_reaped=manager.process is None)),flush=True)
            while True:signal.pause()
    manager=BackgroundArchives(root/'archives',budget=disk,cursor=writer.initial_cursor(),_hook=pause)
    manager.submit(ticket);await manager.finish()
    raise RuntimeError('kill hook not reached')


async def crash_recover(case,stage,before):
    root=case/'capture';disk=ReservedStorageBudget.resume(root,**CONTRACT)
    writer=None;manager=None
    try:
        store=SegmentArchive(root/'archives',budget=disk)
        recovered=store.recover()
        expected=1 if stage in STAGES[-2:] else 0
        assert len(recovered['registered'])==expected
        assert all(file_hash(root/p)==h for p,h in before.items())
        writer=SealedJournal.resume(root/'raw',budget=disk)
        manager=BackgroundArchives(root/'archives',budget=disk,cursor=writer.initial_cursor())
        assert len(writer.recovered_tickets)==1
        manager.submit(writer.recovered_tickets[0]);results=await manager.finish()
        assert len(results)==1
        row=results[0];raw=root/'raw'/row['identity']['segment_name']
        assert b''.join(manager.store.read_chunks(row['archive_id']))==raw.read_bytes()
        final=manager.store.recover()
        assert len(final['registered'])==1
        assert all(file_hash(root/p)==h for p,h in before.items())
        result=dict(stage=stage,status='PASS',actual_parent_sigkill=True,
            registered_before_retry=expected,registered_after_retry=1,
            all_precrash_files_preserved=True,restored_bytes_equal=True,
            before=before,after=files(root),recovered=recovered,final=final,supervisor=manager.snapshot())
        save(case/'result.json',result)
        return result
    finally:
        if manager is not None:await manager.close()
        if writer is not None:writer.close()
        disk.close()


def crashes(output):
    results=[]
    for stage in STAGES:
        case=output/stage;case.mkdir();root=case/'capture'
        proc=subprocess.Popen([sys.executable,__file__,'--child',str(root),'--stage',stage],
                              stdout=subprocess.PIPE,stderr=subprocess.PIPE,bufsize=0)
        try:
            if not select.select([proc.stdout],[],[],15)[0]:raise RuntimeError('crash stage timeout')
            line=proc.stdout.readline(16385)
            if not line.endswith(b'\n') or len(line)>16384:raise RuntimeError('crash IPC boundary')
            reached=json.loads(line)
            assert reached['stage']==stage and reached['worker_returncode']==0 and reached['worker_reaped']
            try:os.kill(reached['worker_pid'],0)
            except ProcessLookupError:pass
            else:raise RuntimeError('worker still alive at parent kill')
            proc.kill();_,stderr=proc.communicate(timeout=5)
            assert proc.returncode==-signal.SIGKILL and not stderr
        finally:
            if proc.poll() is None:proc.kill()
            proc.communicate(timeout=5)
        save(case/'kill.json',reached|dict(returncode=proc.returncode))
        results.append(asyncio.run(crash_recover(case,stage,files(root))))
    return results


async def load_case(case,large=False):
    case.mkdir();root=case/'capture';disk,writer=create(root);manager=None
    try:
        count,width=(1000,4000) if large else (500,100)
        first=batch(writer,count,width)
        command=None if large else [sys.executable,'-m','tests.sealed_archive_fixture_worker','gate',str(case/'release')]
        manager=BackgroundArchives(root/'archives',budget=disk,cursor=writer.initial_cursor(),_command=command)
        manager.submit(first);await until(lambda:manager.process is not None)
        before=writer.publication_fence().sequence
        if not large:
            second=batch(writer,count,width,seed=31);manager.submit(second)
            assert writer.publication_fence().sequence==before+count and not manager.results
            save(case/'release',dict(go=True))
        else:
            writer.append(dict(while_worker_active=True));writer.commit()
        active_sequence=writer.publication_fence().sequence
        results=await manager.finish()
        restored=0
        for row in results.values():
            raw=root/'raw'/row['identity']['segment_name']
            data=b''.join(manager.store.read_chunks(row['archive_id']))
            assert data==raw.read_bytes();restored+=len(data)
        result=dict(status='PASS',fixture='NEAR_8_MIB_REAL_WORKER' if large else 'GATED_TWO_SEGMENT_OVERLAP',
            writer_open=not writer.closed,writer_sequence_before_overlap=before,
            writer_sequence_after_overlap=active_sequence,segments=len(results),
            restored_bytes=restored,compressed_bytes=sum(r['compressed_bytes'] for r in results.values()),
            every_restored_byte_equal=True,supervisor=manager.snapshot(),files=files(root))
        save(case/'result.json',result);return result
    finally:
        if manager is not None:await manager.close()
        writer.close();disk.close()


async def worker_kill(case):
    case.mkdir();root=case/'capture';disk,writer=create(root);manager=None
    try:
        ticket=batch(writer)
        manager=BackgroundArchives(root/'archives',budget=disk,cursor=writer.initial_cursor(),
            _command=[sys.executable,'-m','tests.sealed_archive_fixture_worker','hang'])
        manager.submit(ticket);await until(lambda:manager.process is not None)
        manager.process.kill()
        try:await manager.finish()
        except JournalError:pass
        else:raise RuntimeError('worker kill accepted')
        assert manager.failed.is_set() and disk.failed and not manager.results
        assert manager.process is None and manager.jobs[0]['returncode']==-signal.SIGKILL
        assert disk.snapshot()['reserved_bytes']==0
        save(case/'result.json',dict(status='EXPECTED_FAILURE_CONFIRMED',actual_worker_sigkill=True,
             supervisor=manager.snapshot(),files=files(root)))
    finally:
        if manager is not None:await manager.close()
        writer.close();disk.close()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path)
    parser.add_argument('--child',type=Path);parser.add_argument('--stage',choices=STAGES)
    args=parser.parse_args()
    if args.child:return asyncio.run(crash_child(args.child,args.stage))
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    save(out/'plan.json',dict(source_hashes={p:file_hash(ROOT/p) for p in SOURCES},stages=STAGES,
        contract=CONTRACT,limits=ArchiveLimits().__dict__,parent_kills=8,worker_kills=1,
        large_fixture=dict(records=1000,random_bytes_per_record=4000,seed=29),
        overlap_fixture=dict(records_per_segment=500,random_bytes_per_record=100,seeds=[29,31]),
        network_requests=0,original_deletion=False))
    crashes(out)
    overlap=asyncio.run(load_case(out/'overlap'))
    large=asyncio.run(load_case(out/'near_limit',large=True))
    asyncio.run(worker_kill(out/'worker_kill'))
    summary=dict(status='PASS_BOUNDED_BACKGROUND_ARCHIVE_COMPONENT',actual_parent_sigkill_cases=8,
        actual_worker_sigkill_cases=1,all_precrash_files_preserved=True,
        overlap_segments=overlap['segments'],large_raw_bytes=large['restored_bytes'],
        large_gzip_bytes=large['compressed_bytes'],network_requests=0,actual_orders=0,
        disk_space_reclaimed_bytes=0,live_collector_integration=False,full_day_ready=False)
    save(out/'summary.json',summary);print(json.dumps(summary))


if __name__=='__main__':main()
