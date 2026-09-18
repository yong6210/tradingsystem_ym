"""Bounded closed-generation compression, independent replay, and retirement.

Only the parent writes. Compression uses the existing guarded archive workers;
raw/gzip audits run in separate read-only, parent-bound processes. Two pending
generations and two shared reservations are hard bounds, never drop policies.
"""
import asyncio
from dataclasses import replace
import os
from pathlib import Path
import sys
import time
import uuid

from .archive_segment_reader import SegmentReader, segment_ref
from .background_segment_archive import ArchiveLimits
from .durable_capture_log import JournalError, ZERO, decoded, encoded, file_hash, sync_directory
from .durable_sealed_pipeline import archive_factory
from .generation_archive_custody import ArchiveSources, MAX_SOURCES
from .generation_feed_replay import sha
from .read_generation_capture import document
from .sealed_segment_handoff import SegmentCursor, SealTicket, certificate


class GenerationArchives:
    def __init__(self, budget, *, policy_hash, hook=lambda stage:None, factory=archive_factory, job_seconds=15):
        if not 0 < job_seconds <= 15: raise ValueError('job deadline bound')
        self.budget, self.policy_hash, self.hook = budget, policy_hash, hook
        self.factory, self.job_seconds = factory, job_seconds
        self.queue = asyncio.Queue(maxsize=2)
        self.failed = asyncio.Event()
        self.detected = None
        self.error = None
        self.pending = self.peak_pending = 0
        self.submitted = 0
        self.results = []
        self.abandoned = []
        self.task = self.process = None
        self.managers = []
        self.peak_parent_ns = self.raw_bytes_removed = self.removed_while_collecting = 0
        self.collecting = True
        self.closed = False
        self.plan_hash = None
        self.child_runs = 0
        self.peak_audit_rss_bytes = 0

    def fail(self, exc):
        if not self.failed.is_set():
            self.error = (type(exc).__name__+':'+str(exc))[:1000]
            self.detected = (time.monotonic_ns(), time.time_ns())
            self.failed.set()
        self.budget.failed = True

    def check(self):
        for manager in self.managers:
            if manager.failed.is_set(): self.fail(JournalError(manager.errors[0]))
        if self.failed.is_set(): raise JournalError(self.error)
        self.budget.check(0)

    def submit(self, index):
        self.check()
        if self.closed or index != self.submitted or self.pending >= 2 or self.submitted >= 16:
            raise JournalError('GENERATION_ARCHIVE_BACKLOG_OR_SEQUENCE_LIMIT')
        directory = self.budget.root/f'generation-{index:04d}'
        if not (directory/'end.json').is_file(): raise JournalError('only closed generations may be archived')
        self.queue.put_nowait(index)
        self.pending += 1; self.submitted += 1
        self.peak_pending = max(self.peak_pending, self.pending)
        if self.task is None: self.task = asyncio.create_task(self._run(), name='closed-generation-archive')

    def _phase(self, began):
        self.peak_parent_ns = max(self.peak_parent_ns, time.monotonic_ns()-began)
        if self.peak_parent_ns > 500_000_000:
            raise JournalError('generation archive parent stall exceeded 500ms')

    def _save(self, path, value, stage):
        began = time.monotonic_ns()
        if path.exists() or len(encoded(value)) > 8*1024**2:
            raise JournalError('immutable generation archive metadata bound')
        self.budget.atomic_json(path, value, lambda point:self.hook(stage+':'+point))
        self._phase(began)

    async def _read(self, stream, maximum):
        result = bytearray()
        while block := await stream.read(min(65536, maximum-len(result)+1)):
            result.extend(block)
            if len(result) > maximum: raise JournalError('generation audit IPC bound')
        return bytes(result)

    async def _audit(self, index, candidate):
        self.check()
        key = 'generation-audit:'+uuid.uuid4().hex
        self.budget.reserve(key, 8*1024**2)
        request = encoded(dict(root=str(self.budget.root), plan_sha256=self.plan_hash,
            policy_sha256=self.policy_hash, stop_after=index, candidate=candidate))
        tasks, spawn = [], None
        try:
            spawn = asyncio.create_task(asyncio.create_subprocess_exec(sys.executable, '-m',
                'app.research.data.generation_audit_worker', '--parent',str(os.getpid()),
                '--seconds',str(self.job_seconds), cwd=Path(__file__).resolve().parents[3],
                env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'), stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE))
            self.process = await asyncio.shield(spawn)
            self.child_runs += 1
            self.hook('generation_audit:child_active')
            async def write():
                self.process.stdin.write(request); await self.process.stdin.drain(); self.process.stdin.close()
            tasks = [asyncio.create_task(self._read(self.process.stdout, 8*1024**2)),
                     asyncio.create_task(self._read(self.process.stderr, 16384)),
                     asyncio.create_task(self.process.wait()), asyncio.create_task(write())]
            async with asyncio.timeout(self.job_seconds):
                stdout, stderr, code, _ = await asyncio.gather(*tasks)
            if code or stderr: raise JournalError('generation audit worker failed: '+stderr.decode(errors='replace')[-700:])
            began = time.monotonic_ns()
            result = decoded(stdout)
            rss = result.get('peak_rss_bytes')
            if type(rss) is not int or not 0 < rss <= 384*1024**2:
                raise JournalError('generation audit worker RSS bound')
            self.peak_audit_rss_bytes = max(self.peak_audit_rss_bytes,rss)
            end = document(self.budget.root/f'generation-{index:04d}'/'end.json')
            if (result['end_seed_sha256'] != end['seed_sha256'] or
                    result['audit']['last_audited_sequence'] != end['global_sequence'] or
                    result['audit']['valid_batches'] != end['global_audit_batches']):
                raise JournalError('audit worker result differs from original end fence')
            self._phase(began)
            return result
        finally:
            try:
                if self.process is None and spawn is not None:
                    self.process = await spawn
                if self.process is not None:
                    if self.process.returncode is None:
                        try: self.process.kill()
                        except ProcessLookupError: pass
                    if self.process.stdin is not None: self.process.stdin.close()
                    for task in tasks:
                        if not task.done(): task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                    async def discard(stream):
                        while await stream.read(65536): pass
                    await asyncio.gather(discard(self.process.stdout), discard(self.process.stderr))
                    await self.process.wait()
                    self.process = None
            finally:
                self.budget.release(key)

    async def _compress(self, index):
        began = time.monotonic_ns()
        directory = self.budget.root/f'generation-{index:04d}'
        start = document(directory/'start.json')
        units = [document(p) for p in sorted(directory.glob('unit-*.json'))]
        if not 1 <= len(units) <= 62: raise JournalError('closed generation unit bound')
        if any(sum(len(u[k]) for u in units) > 64 for k in ('raw','audit')):
            raise JournalError('per-generation archive job bound')
        managers = {}
        refs = []
        try:
            for kind in ('raw','audit'):
                cursor = SegmentCursor(self.budget.root, f'generation-{index:04d}/'+kind,
                                       self.budget.contract['run_id'], start[kind+'_metadata_sha256'])
                managers[kind] = self.factory(directory/(kind+'-archives'), budget=self.budget, cursor=cursor,
                    limits=ArchiveLimits(job_seconds=self.job_seconds), _hook=self.hook)
                self.managers.append(managers[kind])
            self._phase(began)
            for unit in units:
                # At most one job per stream: exactly two global reservations.
                rows = {kind:list(unit[kind]) for kind in managers}
                while any(rows.values()):
                    current = []
                    for kind, manager in managers.items():
                        if rows[kind]:
                            ticket = SealTicket(rows[kind].pop(0).encode())
                            job = manager.submit(ticket)
                            current.append((kind,manager,job,ticket))
                    while any(job not in manager.results for _,manager,job,_ in current):
                        for _,manager,_,_ in current:
                            if manager.failed.is_set(): raise JournalError(manager.errors[0])
                        await asyncio.sleep(.005)
                    for kind,manager,job,ticket in current:
                        timing = manager.jobs[job]['parent_validation_and_publication_ns']
                        self.peak_parent_ns = max(self.peak_parent_ns, timing)
                        if timing > 500_000_000: raise JournalError('archive parent publication stall')
                        refs.append(segment_ref(ticket,
                            archive_directory=str(manager.store.directory.relative_to(self.budget.root)),
                            archive_id=manager.results[job]['archive_id']))
            for manager in managers.values(): await manager.finish()
            self.child_runs += sum(len(m.jobs) for m in managers.values())
            return refs
        finally:
            for manager in managers.values(): await manager.close()
            for manager in managers.values(): self.managers.remove(manager)

    def _cost(self, directory, candidate, proof):
        archive_bytes = 0
        raw_bytes = 0
        for ref in candidate['refs']:
            row = certificate(ref['certificate'].encode()); raw_bytes += row['segment']['bytes']
            store = self.budget.root/ref['archive']['directory']
            descriptor_path = store/(ref['archive']['archive_id']+'.json')
            descriptor = document(descriptor_path)
            archive_bytes += descriptor_path.stat().st_size+(store/descriptor['compressed_name']).stat().st_size
        fixed = (len(encoded(candidate))+len(encoded(proof))+archive_bytes+
                 (self.budget.root/'generation-retention-policy.json').stat().st_size)
        savings = raw_bytes-fixed
        for _ in range(8):
            registration = dict(version=1, candidate_sha256=sha(candidate), proof_sha256=sha(proof),
                                logical_savings_bytes=savings)
            intent = dict(version=1, registration_sha256=sha(registration), candidate_sha256=sha(candidate))
            done = dict(version=1, intent_sha256=sha(intent))
            next_savings = raw_bytes-fixed-sum(len(encoded(v)) for v in (registration,intent,done))
            if next_savings == savings: return registration,intent,done,raw_bytes,archive_bytes
            savings = next_savings
        raise JournalError('retirement cost calculation did not converge')

    async def _retire(self, index, candidate, registration, intent, done):
        if self.budget.snapshot()['reserved_bytes']: raise JournalError('retirement with outstanding reservations')
        directory = self.budget.root/f'generation-{index:04d}'
        self._save(directory/'retention.json', registration, 'retention')
        # Revalidate policy/registration/proof and all still-present raw sources.
        began = time.monotonic_ns()
        sources = ArchiveSources(self.budget.root, plan_hash=self.plan_hash, policy_hash=self.policy_hash)
        sources.selection(index)
        self._phase(began)
        self._save(directory/'retire-intent.json', intent, 'retire_intent')
        cursors = {}
        for ref in candidate['refs']:
            began = time.monotonic_ns()
            row = certificate(ref['certificate'].encode())
            journal = row['journal']
            cursor = cursors.get(journal) or SegmentCursor(self.budget.root, journal,
                                        row['run_id'], row['metadata_sha256'])
            verified = SegmentReader(budget=self.budget).read(ref, cursor)
            cursors[journal] = verified.cursor
            path = self.budget.path(self.budget.root/journal/row['segment']['name'])
            if path.stat().st_size != row['segment']['bytes'] or file_hash(path) != row['segment']['sha256']:
                raise JournalError('raw changed before retirement')
            self.hook('retire:before_unlink')
            with self.budget.mutation():
                path.unlink()
                self.budget._refresh(path)
                self.raw_bytes_removed += row['segment']['bytes']
                if self.collecting: self.removed_while_collecting += row['segment']['bytes']
                self.hook('retire:after_unlink')
                sync_directory(path.parent)
                self.hook('retire:after_directory_fsync')
            self._phase(began)
            await asyncio.sleep(0)
        self._save(directory/'retire-done.json', done, 'retire_done')

    async def _one(self, index):
        directory = self.budget.root/f'generation-{index:04d}'
        raw = await self._audit(index, None)
        refs = await self._compress(index)
        if not 1 <= len(refs) <= MAX_SOURCES: raise JournalError('archive candidate count bound')
        candidate = dict(version=1, index=index, plan_sha256=self.plan_hash, policy_sha256=self.policy_hash,
                         end_sha256=file_hash(directory/'end.json'), refs=refs)
        self._save(directory/'archive-candidate.json', candidate, 'candidate')
        gzip = await self._audit(index, dict(index=index, sha256=sha(candidate)))
        if raw['audit'] != gzip['audit'] or raw['end_seed_sha256'] != gzip['end_seed_sha256']:
            raise JournalError('raw and gzip generation audit differ')
        proof = dict(version=1, plan_sha256=self.plan_hash, candidate_sha256=sha(candidate),
                     end_seed_sha256=gzip['end_seed_sha256'], raw_audit=raw['audit'], gzip_audit=gzip['audit'])
        self._save(directory/'archive-proof.json', proof, 'archive_proof')
        began = time.monotonic_ns()
        registration,intent,done,raw_bytes,archive_bytes = self._cost(directory,candidate,proof)
        self._phase(began)
        accepted = registration['logical_savings_bytes'] > 0
        if accepted: await self._retire(index,candidate,registration,intent,done)
        else: self._save(directory/'retention-rejected.json', registration, 'retention_rejected')
        self.results.append(dict(index=index, retired=accepted, raw_bytes=raw_bytes, archive_bytes=archive_bytes,
            conservative_net_savings_bytes=registration['logical_savings_bytes'], source_segments=len(refs),
            final_seed_sha256=gzip['end_seed_sha256']))

    async def _run(self):
        while True:
            index = await self.queue.get()
            try:
                async with asyncio.timeout(15): await self._one(index)
            except asyncio.CancelledError:
                self.abandoned.append(index)
                raise
            except BaseException as exc:
                self.abandoned.append(index)
                self.fail(exc)
                return
            finally:
                self.pending -= 1
                self.queue.task_done()

    async def drain(self):
        self.collecting = False
        joined = asyncio.create_task(self.queue.join())
        fault = asyncio.create_task(self.failed.wait())
        try:
            done, _ = await asyncio.wait((joined,fault), timeout=15, return_when=asyncio.FIRST_COMPLETED)
            if not done: self.fail(TimeoutError('generation archive drain deadline'))
            self.check()
            if len(self.results) != self.submitted: raise JournalError('generation archive results incomplete')
        finally:
            joined.cancel(); fault.cancel()
            await asyncio.gather(joined,fault,return_exceptions=True)

    async def close(self):
        if self.closed: return
        self.closed = True
        if self.task is not None:
            if not self.task.done() and not self.task.cancelling(): self.task.cancel()
            completion = asyncio.gather(self.task,return_exceptions=True)
            try: await asyncio.shield(completion)
            except asyncio.CancelledError: await completion; raise
        while not self.queue.empty():
            self.abandoned.append(self.queue.get_nowait())
            self.pending -= 1
            self.queue.task_done()
        if self.managers or self.process is not None or self.budget.snapshot()['reserved_bytes']:
            raise JournalError('generation archive ownership leaked')

    def snapshot(self):
        return dict(submitted=self.submitted, completed=len(self.results), peak_pending_generations=self.peak_pending,
                    error=self.error, closed=self.closed, children_reaped=not self.managers and self.process is None,
                    child_runs=self.child_runs, raw_bytes_removed=self.raw_bytes_removed,
                    peak_audit_rss_bytes=self.peak_audit_rss_bytes,
                    audit_rss_guard='SAMPLED_50MS_HIGH_WATER_NOT_OS_HARD_LIMIT',
                    abandoned_generations=list(self.abandoned), pending_generations=self.pending,
                    raw_bytes_removed_while_collecting=self.removed_while_collecting,
                    peak_parent_work_ns=self.peak_parent_ns, generations=list(self.results),
                    history_replay='FROM_ORIGIN_BOUNDED_16_GENERATIONS_NOT_LONG_HISTORY_INDEX')
