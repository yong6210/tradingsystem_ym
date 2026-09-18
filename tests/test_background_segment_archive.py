import asyncio
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from app.research.data import background_segment_archive as arch
from app.research.data.durable_capture_log import JournalError, file_hash
from app.research.data.reserved_feed_storage import ReservedStorageBudget
from app.research.data.sealed_segment_handoff import SealedJournal
from app.research.data.segment_archive import SegmentArchive


async def until(predicate):
    async with asyncio.timeout(5):
        while not predicate(): await asyncio.sleep(.01)


class ReservationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name).resolve()/'run'
        self.disk=ReservedStorageBudget.create(self.root,run_id='reservation',max_bytes=1000000,min_free_bytes=0)

    def tearDown(self):
        self.disk.close(); self.temp.cleanup()

    def test_reservation_reduces_writer_headroom(self):
        self.disk.reserve('job',10000)
        self.disk.contract['max_bytes']=self.disk.used+10000+100
        with (self.root/'ordinary').open('xb',buffering=0) as f:
            self.disk.append(f,b'x'*100)
            with self.assertRaisesRegex(JournalError,'budget'): self.disk.append(f,b'x')
        self.assertTrue(self.disk.failed)
        self.assertEqual(self.disk.snapshot()['reserved_bytes'],10000)

    def test_spending_consumes_reservation_without_double_counting(self):
        self.disk.reserve('job',1000)
        self.disk.contract['max_bytes']=self.disk.used+1000
        with self.disk.spend('job'):
            with (self.root/'output').open('xb',buffering=0) as f:
                self.disk.append(f,b'x'*700)
                self.assertEqual(self.disk.snapshot()['reserved_bytes'],300)
                self.disk.append(f,b'x'*300)
        self.assertEqual(self.disk.snapshot()['reserved_bytes'],0)
        self.assertEqual(self.disk.used,self.disk.contract['max_bytes'])

    def test_spending_cannot_exceed_reserved_amount(self):
        self.disk.reserve('job',10)
        with self.assertRaisesRegex(JournalError,'reservation exhausted'):
            with self.disk.spend('job'):
                with (self.root/'output').open('xb',buffering=0) as f:
                    self.disk.append(f,b'x'*11)
        self.assertTrue(self.disk.failed)
        self.assertEqual((self.root/'output').stat().st_size,0)

    def test_unused_reservation_released_after_spending(self):
        before=self.disk.used; self.disk.reserve('job',1000)
        with self.disk.spend('job'):
            self.disk.atomic_json(self.root/'small.json',dict(x=1))
        self.assertEqual(self.disk.snapshot()['reserved_bytes'],0)
        self.assertLess(self.disk.used-before,1000)

    def test_free_space_check_includes_reservations(self):
        self.disk.reserve('job',1000)
        usage=shutil.disk_usage(self.root)
        with patch('app.research.data.shared_feed_storage.shutil.disk_usage',
                   return_value=usage._replace(free=65536+999)):
            with self.assertRaisesRegex(JournalError,'free-space'): self.disk.check(0)

    def test_two_reservations_are_aggregate(self):
        self.disk.reserve('a',1000); self.disk.reserve('b',2000)
        self.assertEqual(self.disk.snapshot()['reserved_bytes'],3000)
        with self.assertRaisesRegex(JournalError,'count'): self.disk.reserve('c',1)
        self.assertTrue(self.disk.failed)

    def test_failed_spend_counts_partial_file_and_keeps_latch(self):
        self.disk.reserve('job',100)
        with self.assertRaises(RuntimeError):
            with self.disk.spend('job'):
                with (self.root/'partial').open('xb',buffering=0) as f: self.disk.append(f,b'x'*10)
                raise RuntimeError('fault')
        self.assertTrue(self.disk.failed)
        self.assertEqual(self.disk.used,sum(p.stat().st_size for p in self.root.rglob('*') if p.is_file()))
        self.disk.release('job')
        with self.assertRaises(JournalError): self.disk.check(0)

    def test_resume_does_not_replenish_existing_file_space(self):
        self.disk.reserve('job',1000)
        with self.disk.spend('job'):
            with (self.root/'output').open('xb',buffering=0) as f: self.disk.append(f,b'x'*1000)
        before=self.disk.used; self.disk.close()
        self.disk=ReservedStorageBudget.resume(self.root,run_id='reservation',max_bytes=1000000,min_free_bytes=0)
        self.assertEqual(self.disk.used,before)
        self.assertEqual(self.disk.snapshot()['reserved_bytes'],0)


class ArchiveSupervisorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name).resolve()/'run'
        self.contract=dict(run_id='archive-worker',max_bytes=4*1024**2,min_free_bytes=0)
        self.disk=ReservedStorageBudget.create(self.root,**self.contract)
        self.writer=SealedJournal.create(self.root/'raw',budget=self.disk,run_id=self.contract['run_id'],
                                         rotation_bytes=64*1024,max_record_bytes=2048)
        self.initial=self.writer.initial_cursor()
        self.managers=[]

    async def asyncTearDown(self):
        for manager in self.managers: await manager.close()
        self.writer.close(); self.disk.close(); self.temp.cleanup()

    def ticket(self):
        for i in range(10): self.writer.append(dict(i=i,data='x'*200))
        ticket,=self.writer.seal()
        return ticket

    def manager(self,mode=None,hook=lambda stage:None,**limits):
        command=None if mode is None else [sys.executable,'-m','tests.sealed_archive_fixture_worker',mode,str(self.root/'release')]
        m=arch.BackgroundArchives(self.root/'archives',budget=self.disk,cursor=self.initial,
                                  limits=arch.ArchiveLimits(**limits),_command=command,_hook=hook)
        self.managers.append(m); return m

    async def fail_job(self,mode,**limits):
        ticket=self.ticket(); m=self.manager(mode,**limits); m.submit(ticket)
        with self.assertRaises(JournalError): await m.finish()
        self.assertTrue(m.failed.is_set()); self.assertTrue(self.disk.failed)
        self.assertTrue(m.snapshot()['child_reaped']); self.assertFalse(m.results)
        self.assertEqual(m.pending,0); self.assertEqual(self.disk.snapshot()['reserved_bytes'],0)
        for job in m.jobs:
            if 'pid' in job:
                with self.assertRaises(ProcessLookupError): os.kill(job['pid'],0)
        return m

    async def test_real_worker_archives_two_segments_while_writer_open(self):
        first=self.ticket(); m=self.manager(); m.submit(first)
        second=self.ticket(); m.submit(second)
        self.writer.append(dict(still_active=True)); self.writer.commit()
        results=await m.finish()
        self.assertEqual(len(results),2); self.assertFalse(self.writer.closed)
        self.assertFalse(self.disk.failed); self.assertEqual(m.peak_pending,2)
        self.assertEqual(self.disk.snapshot()['reserved_bytes'],0)
        for row in results.values():
            raw=self.root/'raw'/row['identity']['segment_name']
            self.assertEqual(b''.join(m.store.read_chunks(row['archive_id'])),raw.read_bytes())
        self.assertEqual(self.disk.used,sum(p.stat().st_size for p in self.root.rglob('*') if p.is_file()))

    async def test_reader_gate_does_not_block_next_writer_commit(self):
        first=self.ticket(); m=self.manager('gate'); m.submit(first)
        await until(lambda:m.process is not None)
        before=self.writer.publication_fence().sequence
        second=self.ticket(); m.submit(second)
        self.assertEqual(self.writer.publication_fence().sequence,before+10)
        self.assertEqual(len(m.results),0)
        (self.root/'release').write_text('go'); self.disk.reconcile()
        await m.finish(); self.assertEqual(len(m.results),2)

    async def test_backlog_includes_running_and_queued_then_fails_closed(self):
        first=self.ticket(); second=self.ticket(); third=self.ticket()
        m=self.manager('hang'); m.submit(first)
        await until(lambda:m.process is not None)
        m.submit(second)
        with self.assertRaisesRegex(JournalError,'BACKLOG'):m.submit(third)
        await m.close(); self.assertEqual(m.pending,0)
        self.assertTrue(self.disk.failed); self.assertTrue(m.snapshot()['child_reaped'])

    async def test_total_job_limit_includes_completed_jobs(self):
        first=self.ticket(); second=self.ticket(); m=self.manager(max_jobs=1)
        m.submit(first); await until(lambda:len(m.results)==1)
        with self.assertRaisesRegex(JournalError,'BACKLOG'):m.submit(second)
        await m.close(); self.assertTrue(self.disk.failed)

    async def test_duplicate_or_skipped_ticket_fails_before_spawn(self):
        self.ticket(); second=self.ticket(); m=self.manager()
        with self.assertRaisesRegex(JournalError,'continuity'):m.submit(second)
        self.assertFalse(m.jobs); self.assertIsNone(m.process)

    async def test_writer_cannot_spend_pending_archive_reservation(self):
        ticket=self.ticket(); m=self.manager('hang'); m.submit(ticket)
        await until(lambda:m.process is not None)
        reserved=self.disk.snapshot()['reserved_bytes']
        self.disk.contract['max_bytes']=self.disk.used+reserved+1
        with self.assertRaisesRegex(JournalError,'budget'):self.writer.append(dict(other=True))
        await m.close(); self.assertTrue(self.disk.failed)

    async def test_reservation_failure_never_starts_worker(self):
        ticket=self.ticket(); m=self.manager()
        self.disk.contract['max_bytes']=self.disk.used+10
        with self.assertRaises(JournalError):m.submit(ticket)
        self.assertFalse(m.jobs); self.assertIsNone(m.process)
        self.assertEqual(self.disk.snapshot()['reserved_bytes'],0)

    async def test_worker_crash(self):await self.fail_job('crash')
    async def test_invalid_frame(self):await self.fail_job('invalid')
    async def test_wrong_job_binding(self):await self.fail_job('wrong-job')
    async def test_wrong_ticket_binding(self):await self.fail_job('wrong-ticket')
    async def test_wrong_compressed_hash(self):await self.fail_job('wrong-hash')
    async def test_wrong_compressed_length(self):await self.fail_job('wrong-length')
    async def test_oversized_header(self):await self.fail_job('oversize-header')
    async def test_reported_rss_over_limit(self):await self.fail_job('rss')
    async def test_real_rss_guard_tiny_limit(self):await self.fail_job(None,rss_limit_bytes=1)
    async def test_corrupt_gzip_even_with_matching_compressed_hash(self):await self.fail_job('corrupt-gzip')
    async def test_wrong_restored_raw_hash(self):await self.fail_job('wrong-raw')
    async def test_expansion_past_sealed_size(self):await self.fail_job('expansion')
    async def test_trailing_stdout(self):await self.fail_job('trailing')
    async def test_stdout_overflow(self):await self.fail_job('stdout')
    async def test_stderr_overflow(self):await self.fail_job('stderr')
    async def test_worker_deadline(self):await self.fail_job('hang',job_seconds=.1)
    async def test_final_drain_deadline(self):await self.fail_job('hang',drain_seconds=.1)

    async def test_source_corruption_rejected_by_worker(self):
        ticket=self.ticket(); source=self.root/'raw/segment-0000000.jsonl'
        raw=bytearray(source.read_bytes());raw[-2]^=1;source.write_bytes(raw)
        m=self.manager();m.submit(ticket)
        with self.assertRaises(JournalError):await m.finish()
        self.assertFalse(m.results)
        self.assertFalse(list((self.root/'archives').glob('*.json')))

    async def test_parent_storage_failure_leaves_raw_and_temp(self):
        ticket=self.ticket(); source=self.root/'raw/segment-0000000.jsonl'; before=file_hash(source)
        def fail(stage):
            if stage=='after_parent_archive_chunk':raise OSError('parent disk')
        m=self.manager(hook=fail);m.submit(ticket)
        with self.assertRaises(JournalError):await m.finish()
        self.assertEqual(file_hash(source),before)
        self.assertTrue(list((self.root/'archives').glob('.*.gz.tmp')))
        self.assertFalse(list((self.root/'archives').glob('*.json')))
        self.assertTrue(self.disk.failed)

    async def test_late_synchronous_parent_publication_is_not_success(self):
        ticket=self.ticket()
        def delay(stage):
            if stage=='after_parent_manifest_directory_fsync':time.sleep(.6)
        m=self.manager(hook=delay,job_seconds=.5);m.submit(ticket)
        with self.assertRaises(JournalError):await m.finish()
        self.assertFalse(m.results);self.assertTrue(self.disk.failed)
        self.assertTrue(list((self.root/'archives').glob('*.json')))

    async def test_existing_archive_is_idempotently_reverified(self):
        ticket=self.ticket();m=self.manager();m.submit(ticket);one=await m.finish();used=self.disk.used
        again=self.manager();again.submit(ticket);two=await again.finish()
        self.assertEqual(one,two);self.assertEqual(self.disk.used,used)

    async def test_close_during_spawn_owns_and_reaps_child(self):
        original=asyncio.create_subprocess_exec;created=asyncio.Event();children=[]
        async def delayed(*args,**kwargs):
            proc=await original(*args,**kwargs);children.append(proc);created.set()
            await asyncio.sleep(.05);return proc
        ticket=self.ticket();m=self.manager('hang')
        with patch.object(arch.asyncio,'create_subprocess_exec',delayed):
            m.submit(ticket);await created.wait();await m.close()
        self.assertTrue(self.disk.failed);self.assertIsNone(m.process)
        self.assertTrue(all(p.returncode is not None for p in children))
        self.assertEqual(self.disk.snapshot()['reserved_bytes'],0)

    async def test_finish_cancellation_reaps_and_releases(self):
        ticket=self.ticket();m=self.manager('hang');m.submit(ticket)
        await until(lambda:m.process is not None)
        finish=asyncio.create_task(m.finish());await asyncio.sleep(.01);finish.cancel()
        with self.assertRaises(asyncio.CancelledError):await finish
        self.assertTrue(self.disk.failed);self.assertTrue(m.snapshot()['child_reaped'])
        self.assertEqual(self.disk.snapshot()['reserved_bytes'],0)

    async def test_queued_age_counts_against_deadline(self):
        first=self.ticket();second=self.ticket();m=self.manager('hang',job_seconds=.1)
        m.submit(first);m.submit(second)
        with self.assertRaises(JournalError):await m.finish()
        self.assertEqual(m.jobs[1]['status'],'CANCELLED')
        self.assertNotIn('pid',m.jobs[1])

    def test_invalid_limits_rejected(self):
        for kwargs in (dict(max_pending=3),dict(max_pending=True),dict(job_seconds=float('nan')),
                       dict(job_seconds=float('inf')),dict(drain_seconds=0),dict(max_jobs=65)):
            with self.assertRaises(ValueError):arch.ArchiveLimits(**kwargs)

    async def test_cancelling_close_during_spawn_still_clears_queued_reservation(self):
        original=asyncio.create_subprocess_exec;created=asyncio.Event();release=asyncio.Event();children=[]
        async def delayed(*args,**kwargs):
            proc=await original(*args,**kwargs);children.append(proc);created.set()
            await release.wait();return proc
        first=self.ticket();second=self.ticket();m=self.manager('hang')
        with patch.object(arch.asyncio,'create_subprocess_exec',delayed):
            m.submit(first);m.submit(second);await created.wait()
            closing=asyncio.create_task(m.close());await asyncio.sleep(.01)
            closing.cancel();release.set()
            with self.assertRaises(asyncio.CancelledError):await closing
        self.assertTrue(all(p.returncode is not None for p in children))
        self.assertIsNone(m.process);self.assertEqual(m.pending,0)
        self.assertEqual(self.disk.snapshot()['reserved_bytes'],0)

    async def test_repeated_close_does_not_interrupt_reaping(self):
        ticket=self.ticket();m=self.manager('hang');m.submit(ticket)
        await until(lambda:m.process is not None)
        await asyncio.gather(m.close(),m.close())
        self.assertIsNone(m.process);self.assertEqual(m.pending,0)
        self.assertEqual(self.disk.snapshot()['reserved_bytes'],0)

    async def test_parent_rejects_tampered_persisted_archive_before_registration(self):
        ticket=self.ticket()
        def corrupt(stage):
            if stage=='after_parent_archive_fsync':
                path=next((self.root/'archives').glob('.*.gz.tmp'))
                raw=bytearray(path.read_bytes());raw[-1]^=1;path.write_bytes(raw)
        m=self.manager(hook=corrupt);m.submit(ticket)
        with self.assertRaises(JournalError):await m.finish()
        self.assertFalse(m.results);self.assertFalse(list((self.root/'archives').glob('*.json')))
        self.assertTrue(self.disk.failed)
