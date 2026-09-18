import asyncio
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from app.research.data import background_incremental_audit as worker
from app.research.data.background_segment_archive import ArchiveLimits,BackgroundArchives
from app.research.data.durable_capture_log import JournalError,decoded,encoded
from app.research.data.incremental_feed_audit import IncrementalFeedAudit
from app.research.data.incremental_audit_protocol import ReplayProposal,build_request,execute
from app.research.data.sealed_archive_worker import peak_rss_bytes
from app.research.data.sealed_segment_handoff import SealedJournal
from tests import incremental_audit_fixture as fixtures


async def until(predicate):
    async with asyncio.timeout(10):
        while not predicate():await asyncio.sleep(.01)


class BackgroundIncrementalAuditTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name).resolve()
        self.fix=fixtures.fixture(self.base);self.budget=self.fix['budget'];self.root=self.fix['root']
        self.work=fixtures.jobs(self.fix)
        self.owner=IncrementalFeedAudit.create(self.root/'state',budget=self.budget,contract=self.fix['contract'])
        self.managers=[]

    async def asyncTearDown(self):
        for manager in self.managers:await manager.close()
        self.owner.close();self.budget.close();self.temp.cleanup()

    def manager(self,mode=None,hook=lambda stage:None,**limits):
        command=None if mode is None else [sys.executable,'-m','tests.incremental_audit_fixture_worker',mode,str(self.base/'release')]
        manager=worker.BackgroundIncrementalAudits(self.owner,limits=ArchiveLimits(**limits),_command=command,_hook=hook)
        self.managers.append(manager);return manager

    async def complete(self,compressed=False):
        work=fixtures.jobs(self.fix,compressed=compressed) if compressed else self.work
        manager=self.manager()
        for a,r in work:
            await until(lambda:manager.pending<2 or manager.failed.is_set())
            manager.submit(a,r)
        await until(lambda:manager.pending<2 or manager.failed.is_set())
        manager.submit_finalize(raw_cursor=self.fix['raw_cursor'],audit_cursor=self.fix['audit_cursor'])
        await manager.finish()
        result=self.owner.summary()
        for k in fixtures.COMPARABLE:self.assertEqual(result[k],self.fix['expected'][k],k)
        self.assertEqual(self.budget.snapshot()['reserved_bytes'],0)
        self.assertTrue(manager.snapshot()['child_reaped']);self.assertFalse(self.owner.closed)
        return manager

    async def failure(self,mode,**limits):
        before=self.owner.path.read_bytes();manager=self.manager(mode,**limits);manager.submit(*self.work[0])
        with self.assertRaises(JournalError):await manager.finish()
        self.assertTrue(manager.failed.is_set());self.assertTrue(self.owner.failed);self.assertTrue(self.budget.failed)
        self.assertEqual(self.owner.path.read_bytes(),before);self.assertFalse(manager.results)
        self.assertTrue(manager.snapshot()['child_reaped']);self.assertEqual(manager.pending,0)
        self.assertEqual(self.budget.snapshot()['reserved_bytes'],0)
        for job in manager.jobs:
            if 'pid' in job:
                with self.assertRaises(ProcessLookupError):os.kill(job['pid'],0)
        return manager

    async def test_real_raw_worker_matches_full_replay(self):await self.complete()
    async def test_real_gzip_worker_matches_full_replay(self):await self.complete(compressed=True)

    async def test_worker_proposal_cannot_write_while_parent_holds_locks(self):
        before=self.owner.path.read_bytes();manager=self.manager('gate');manager.submit(*self.work[0])
        await until(lambda:manager.process is not None)
        self.assertEqual(self.owner.path.read_bytes(),before)
        active=SealedJournal.create(self.root/'active',budget=self.budget,run_id=self.budget.contract['run_id'])
        try:
            active.append(dict(while_auditor_waits=True));active.commit()
            self.assertEqual(active.publication_fence().sequence,1)
        finally:active.close()
        (self.base/'release').write_text('go');await manager.finish()
        self.assertEqual(self.owner.receipt()['revision'],1)

    async def test_archive_and_audit_share_two_reservation_slots(self):
        auditor=self.manager('gate');auditor.submit(*self.work[0])
        await until(lambda:auditor.process is not None)
        compressor=BackgroundArchives(self.root/'parallel-archives',budget=self.budget,
            cursor=worker.restore_cursor(self.fix['contract']['raw_initial']),
            _command=[sys.executable,'-m','tests.sealed_archive_fixture_worker','gate',str(self.base/'release')])
        self.managers.append(compressor);compressor.submit(self.fix['raw_tickets'][0])
        await until(lambda:compressor.process is not None)
        self.assertEqual(self.budget.snapshot()['pending_reservations'],2)
        (self.base/'release').write_text('go');await asyncio.gather(auditor.finish(),compressor.finish())
        self.assertEqual(self.budget.snapshot()['reserved_bytes'],0)
        self.assertFalse(self.budget.failed)

    async def test_backlog_counts_running_and_queued_jobs(self):
        manager=self.manager('hang');manager.submit(*self.work[0]);await until(lambda:manager.process is not None)
        manager.submit(*self.work[1])
        with self.assertRaisesRegex(JournalError,'BACKLOG'):manager.submit(*self.work[2])
        await manager.close();self.assertEqual(manager.pending,0);self.assertTrue(manager.snapshot()['child_reaped'])

    async def test_total_jobs_bound_includes_completed(self):
        manager=self.manager(max_jobs=1);manager.submit(*self.work[0]);await until(lambda:len(manager.results)==1)
        with self.assertRaisesRegex(JournalError,'BACKLOG'):manager.submit(*self.work[1])
        await manager.close()

    async def test_duplicate_ticket_rejected_before_second_spawn(self):
        manager=self.manager('hang');manager.submit(*self.work[0])
        with self.assertRaises(JournalError):manager.submit(*self.work[0])
        await manager.close();self.assertEqual(len(manager.jobs),1)

    async def test_space_reserved_before_worker_dispatch(self):
        manager=self.manager();self.budget.contract['max_bytes']=self.budget.used+1
        with self.assertRaises(JournalError):manager.submit(*self.work[0])
        self.assertIsNone(manager.process);self.assertFalse(manager.jobs)

    async def test_caller_cannot_mutate_queued_input(self):
        a,r=self.work[0];manager=self.manager('gate');manager.submit(a,r)
        await until(lambda:manager.process is not None)
        a['certificate']='broken';r.clear();(self.base/'release').write_text('go')
        await manager.finish();self.assertEqual(self.owner.receipt()['revision'],1)

    async def test_stale_base_cannot_overwrite_parent_progress(self):
        manager=self.manager('gate');manager.submit(*self.work[0]);await until(lambda:manager.process is not None)
        self.owner.advance(*self.work[0]);before=self.owner.path.read_bytes()
        (self.base/'release').write_text('go')
        with self.assertRaises(JournalError):await manager.finish()
        self.assertEqual(self.owner.path.read_bytes(),before)

    async def test_external_checkpoint_change_not_silently_overwritten(self):
        manager=self.manager('gate');manager.submit(*self.work[0]);await until(lambda:manager.process is not None)
        before=self.owner.path.read_bytes()+b' ';self.owner.path.write_bytes(before)
        (self.base/'release').write_text('go')
        with self.assertRaises(JournalError):await manager.finish()
        self.assertEqual(self.owner.path.read_bytes(),before)

    async def test_worker_crash(self):await self.failure('crash')
    async def test_invalid_json(self):await self.failure('invalid')
    async def test_duplicate_json_key(self):await self.failure('duplicate-key')
    async def test_wrong_job(self):await self.failure('wrong-job')
    async def test_wrong_request(self):await self.failure('wrong-request')
    async def test_wrong_base(self):await self.failure('wrong-base')
    async def test_bad_checkpoint_checksum(self):await self.failure('bad-checksum')
    async def test_wrong_successor_hash(self):await self.failure('wrong-successor')
    async def test_bad_saved_cursor(self):await self.failure('bad-cursor')
    async def test_unknown_state_type(self):await self.failure('bad-state')
    async def test_changed_raw_source(self):await self.failure('raw-source-change')
    async def test_reported_rss_over_limit(self):await self.failure('rss')
    async def test_real_worker_tiny_rss_budget(self):await self.failure(None,rss_limit_bytes=1)
    async def test_stdout_overflow(self):await self.failure('stdout')
    async def test_stderr_overflow(self):await self.failure('stderr')
    async def test_job_timeout(self):await self.failure('hang',job_seconds=.1)
    async def test_drain_timeout(self):await self.failure('hang',drain_seconds=.1)

    async def test_parent_commit_fault_keeps_previous_receipt_and_temp(self):
        before=self.owner.path.read_bytes()
        def fail(stage):
            if stage=='after_audit_checkpoint_fsync':raise OSError('storage fault')
        manager=self.manager(hook=fail);manager.submit(*self.work[0])
        with self.assertRaises(JournalError):await manager.finish()
        self.assertEqual(self.owner.path.read_bytes(),before)
        self.assertTrue(list(self.owner.directory.glob('.checkpoint.json.*.tmp')))

    async def test_late_parent_fsync_never_returns_success_receipt(self):
        def delay(stage):
            if stage=='after_audit_checkpoint_directory_fsync':time.sleep(.6)
        manager=self.manager(hook=delay,job_seconds=.5);manager.submit(*self.work[0])
        with self.assertRaises(JournalError):await manager.finish()
        self.assertFalse(manager.results);self.assertEqual(decoded(self.owner.path.read_bytes())['revision'],1)

    async def test_finalization_requires_submitted_terminal_cursor(self):
        manager=self.manager()
        with self.assertRaises(JournalError):manager.submit_finalize(raw_cursor=self.fix['raw_cursor'],audit_cursor=self.fix['audit_cursor'])
        self.assertFalse(manager.jobs)

    async def test_forged_finalize_state_rejected(self):
        for a,r in self.work:self.owner.advance(a,r)
        before=self.owner.path.read_bytes();manager=self.manager('final-state-change')
        manager.submit_finalize(raw_cursor=self.fix['raw_cursor'],audit_cursor=self.fix['audit_cursor'])
        with self.assertRaises(JournalError):await manager.finish()
        self.assertEqual(self.owner.path.read_bytes(),before)

    async def test_close_during_spawn_reaps_and_clears_queued_work(self):
        original=asyncio.create_subprocess_exec;created=asyncio.Event();release=asyncio.Event();children=[]
        async def delayed(*args,**kwargs):
            proc=await original(*args,**kwargs);children.append(proc);created.set();await release.wait();return proc
        manager=self.manager('hang')
        with patch.object(worker.asyncio,'create_subprocess_exec',delayed):
            manager.submit(*self.work[0]);manager.submit(*self.work[1]);await created.wait()
            closing=asyncio.create_task(manager.close());await asyncio.sleep(.01);closing.cancel();release.set()
            with self.assertRaises(asyncio.CancelledError):await closing
        self.assertTrue(all(p.returncode is not None for p in children));self.assertIsNone(manager.process)
        self.assertEqual(manager.pending,0);self.assertEqual(self.budget.snapshot()['reserved_bytes'],0)

    async def test_finish_cancellation_reaps_child(self):
        manager=self.manager('hang');manager.submit(*self.work[0]);await until(lambda:manager.process is not None)
        task=asyncio.create_task(manager.finish());await asyncio.sleep(.01);task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertIsNone(manager.process);self.assertEqual(self.budget.snapshot()['reserved_bytes'],0)

    async def test_repeated_close_does_not_cancel_reap_again(self):
        manager=self.manager('hang');manager.submit(*self.work[0]);await until(lambda:manager.process is not None)
        await asyncio.gather(manager.close(),manager.close());self.assertIsNone(manager.process)

    def test_in_memory_proposal_has_no_write_capability(self):
        proposal=ReplayProposal(self.owner._doc);before=self.owner.path.read_bytes()
        self.assertFalse(hasattr(proposal.budget,'atomic_json'));self.assertFalse(hasattr(proposal.budget,'append'))
        proposal.advance(*self.work[0]);self.assertEqual(self.owner.path.read_bytes(),before)
        self.assertEqual(proposal.receipt()['revision'],1)

    def test_request_source_binding_is_checked_inside_worker(self):
        a,r=self.work[0];request=build_request(0,self.owner._doc,'advance',dict(audit_ref=a,raw_refs=r),384*1024**2)
        request['worker_sources']['incremental_audit_protocol.py']='0'*64
        with self.assertRaisesRegex(JournalError,'source or checksum'):execute(request,peak_rss_bytes)
