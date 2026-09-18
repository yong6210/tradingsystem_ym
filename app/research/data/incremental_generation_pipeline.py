"""Incremental audits inside the frozen bounded archive/retirement lifecycle.

No writable resume and no increased capture limits. The parent retains just the
last completed proof hash; all cold recovery still replays original history.
"""
import asyncio
import os
from pathlib import Path
import sys
import time
import uuid

from .durable_capture_log import JournalError, ZERO, decoded, encoded, file_hash
from .generation_archive_pipeline import GenerationArchives
from .generation_archive_custody import MAX_SOURCES
from .generation_audit_anchor import make_receipt
from .generation_feed_replay import sha
from .read_generation_capture import document


class IncrementalGenerationArchives(GenerationArchives):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.previous_proof_hash = ZERO
        self.next_index = 0
        self.audit_work = []  # <= 2 passes * unchanged 16-generation limit.

    async def _compress(self, index):
        try:
            return await super()._compress(index)
        finally:
            # The frozen implementation closes managers sequentially. If the
            # caller is cancelled during the first close, its finally block
            # exits before closing the second. Finish every remaining owner
            # in a shielded task, then propagate the original cancellation.
            remaining = tuple(self.managers)
            if remaining:
                async def cleanup():
                    results = await asyncio.gather(*(m.close() for m in remaining), return_exceptions=True)
                    for manager, result in zip(remaining, results, strict=True):
                        if result is None and manager in self.managers:
                            self.managers.remove(manager)
                    if self.managers:
                        raise JournalError('incremental archive manager cleanup incomplete')
                task = asyncio.create_task(cleanup(), name='incremental-archive-cleanup')
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    await task
                    raise

    async def _audit(self, index, candidate):
        self.check()
        if index != self.next_index:
            raise JournalError("incremental parent anchor sequence differs")
        started_ns = time.monotonic_ns()
        key = 'generation-audit:'+uuid.uuid4().hex
        self.budget.reserve(key, 8*1024**2)
        request = encoded(dict(root=str(self.budget.root), plan_sha256=self.plan_hash,
            policy_sha256=self.policy_hash, index=index, previous_proof_sha256=self.previous_proof_hash, candidate=candidate))
        tasks, spawn = [], None
        try:
            spawn = asyncio.create_task(asyncio.create_subprocess_exec(sys.executable, '-m',
                'app.research.data.incremental_generation_worker', '--parent',str(os.getpid()),
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
            start = document(self.budget.root/f'generation-{index:04d}'/'start.json')
            expected = make_receipt(index, self.plan_hash, self.policy_hash,
                                    self.previous_proof_hash, end, result['audit'])
            if (result['audit_receipt'] != expected or result['audited_generations'] != 1 or
                    result['processed_records'] != end['global_sequence']-start['global_sequence'] or
                    result['processed_batches'] != end['global_audit_batches']-start['global_audit_batches']):
                raise JournalError('incremental worker scope or receipt differs')
            self.audit_work.append(dict(index=index, candidate=candidate is not None,
                audited_generations=1, processed_records=result['processed_records'],
                processed_batches=result['processed_batches'], source_reads=result['source_reads'],
                elapsed_ns=time.monotonic_ns()-started_ns))
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

    async def _one(self, index):
        directory = self.budget.root/f'generation-{index:04d}'
        raw = await self._audit(index, None)
        refs = await self._compress(index)
        if not 1 <= len(refs) <= MAX_SOURCES: raise JournalError('archive candidate count bound')
        candidate = dict(version=1, index=index, plan_sha256=self.plan_hash, policy_sha256=self.policy_hash,
                         end_sha256=file_hash(directory/'end.json'), refs=refs)
        self._save(directory/'archive-candidate.json', candidate, 'candidate')
        gzip = await self._audit(index, dict(index=index, sha256=sha(candidate)))
        if raw['audit'] != gzip['audit'] or raw['end_seed_sha256'] != gzip['end_seed_sha256'] or raw['audit_receipt'] != gzip['audit_receipt']:
            raise JournalError('raw and gzip generation audit differ')
        proof = dict(version=1, plan_sha256=self.plan_hash, candidate_sha256=sha(candidate),
                     end_seed_sha256=gzip['end_seed_sha256'], raw_audit=raw['audit'], gzip_audit=gzip['audit'],
                     audit_receipt=gzip['audit_receipt'])
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

        # Promote only after durable proof and successful retention processing.
        # A crash loses this trust; cold recovery must replay from the origin.
        self.hook('incremental_anchor:before_promote')
        self.previous_proof_hash = sha(proof)
        self.next_index += 1
        self.hook('incremental_anchor:after_promote')

    def snapshot(self):
        return super().snapshot() | dict(
            history_replay='ONE_GENERATION_PER_PASS_PARENT_HELD_ANCHOR',
            trusted_completed_generations=self.next_index,
            latest_proof_sha256=self.previous_proof_hash,
            audit_work=list(self.audit_work),
            incremental_generation_audit=True, long_history_index_bounded=False)
