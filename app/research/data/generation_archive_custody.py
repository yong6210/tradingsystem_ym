"""Explicit per-generation raw/gzip selection and crash-preserving custody.

Registration precedes deletion. Missing archives never fall back to raw, and
missing raw requires a matching durable intent. All readers validate the same
v1 seal bytes and the original, unchanged journal checkpoint.
"""
from pathlib import Path

from .archive_segment_reader import SegmentReader, segment_ref
from .continuous_generation_capture import implementation_hashes
from .durable_capture_log import JournalError, decoded, encoded, file_hash, keys, load_state, lock_directory
from .generation_feed_replay import sha
from .incremental_audit_protocol import ReadOnlyBudget
from .read_generation_capture import document
from .sealed_segment_handoff import SegmentCursor, SealTicket, certificate
from .verified_journal_view import VerifiedJournalView

MAX_SOURCES = 128


def policy():
    return dict(version=1, mode='CLOSED_GENERATION_VERIFIED_GZIP_RETIREMENT',
                max_pending_generations=2, max_sources_per_generation=MAX_SOURCES,
                job_seconds=15, drain_seconds=15, source_hashes=implementation_hashes())


def register_policy(budget):
    if set(p.name for p in budget.root.iterdir())-{'storage.json','.writer.lock'}:
        raise JournalError('retention opt-in requires a new empty capture')
    budget.atomic_json(budget.root/'generation-retention-policy.json', policy())
    return file_hash(budget.root/'generation-retention-policy.json')


class ArchiveSources:
    def __init__(self, root, *, plan_hash, policy_hash, candidate=None):
        self.root = Path(root)
        self.plan_hash, self.policy_hash = plan_hash, policy_hash
        if (file_hash(self.root/'generation-retention-policy.json') != policy_hash or
                document(self.root/'generation-retention-policy.json') != policy()):
            raise JournalError('generation retention policy differs')
        plan = document(self.root/'generation-plan.json')
        if sha(plan) != plan_hash:
            raise JournalError('generation plan differs')
        self.budget = ReadOnlyBudget(dict(raw_initial=dict(root=str(self.root), run_id=plan['run_id'])))
        self.candidate = candidate
        self.cache = {}
        self.read_counts = dict(RAW=0, GZIP=0)

    def selection(self, index):
        if index in self.cache: return self.cache[index]
        directory = self.root/f'generation-{index:04d}'
        registration_path = directory/'retention.json'
        override = self.candidate is not None and self.candidate['index'] == index
        if not registration_path.exists() and not override:
            if (directory/'retire-intent.json').exists() or (directory/'retire-done.json').exists():
                raise JournalError('retirement without registration')
            self.cache[index] = {}
            return {}
        candidate = document(directory/'archive-candidate.json')
        keys(candidate, 'version index plan_sha256 policy_sha256 end_sha256 refs')
        if (candidate['version'] != 1 or candidate['index'] != index or candidate['plan_sha256'] != self.plan_hash or
                candidate['policy_sha256'] != self.policy_hash or
                candidate['end_sha256'] != file_hash(directory/'end.json') or
                not 1 <= len(candidate['refs']) <= MAX_SOURCES):
            raise JournalError('archive candidate binding or bound')
        intent = done = None
        if override:
            if registration_path.exists() or sha(candidate) != self.candidate['sha256']:
                raise JournalError('candidate audit scope differs')
        else:
            registration = document(registration_path)
            keys(registration, 'version candidate_sha256 proof_sha256 logical_savings_bytes')
            proof = document(directory/'archive-proof.json')
            if (registration['version'] != 1 or registration['candidate_sha256'] != sha(candidate) or
                    registration['proof_sha256'] != sha(proof) or type(registration['logical_savings_bytes']) is not int or
                    registration['logical_savings_bytes'] <= 0):
                raise JournalError('retention registration differs')
            if (proof['plan_sha256'] != self.plan_hash or proof['candidate_sha256'] != sha(candidate) or
                    proof['end_seed_sha256'] != document(directory/'end.json')['seed_sha256'] or
                    proof['raw_audit'] != proof['gzip_audit']):
                raise JournalError('retention replay proof differs')
            intent_path, done_path = directory/'retire-intent.json', directory/'retire-done.json'
            if intent_path.exists():
                intent = document(intent_path)
                if intent != dict(version=1, registration_sha256=sha(registration), candidate_sha256=sha(candidate)):
                    raise JournalError('retirement intent differs')
            if done_path.exists():
                done = document(done_path)
                if intent is None or done != dict(version=1, intent_sha256=sha(intent)):
                    raise JournalError('retirement done differs')
        selected = {}
        for ref in candidate['refs']:
            row = certificate(ref['certificate'].encode())
            name = row['journal']+'/'+row['segment']['name']
            if (row['journal'] not in (f'generation-{index:04d}/raw',f'generation-{index:04d}/audit') or
                    name in selected or ref['archive'] is None or
                    ref['archive']['directory'] != row['journal']+'-archives'):
                raise JournalError('archive source outside generation or duplicated')
            if (self.root/row['journal']/'seals'/(row['segment']['name']+'.seal.json')).read_bytes() != ref['certificate'].encode():
                raise JournalError('archive source differs from durable seal')
            source = self.budget.path(self.root/name)
            if source.exists():
                if done is not None or source.stat().st_size != row['segment']['bytes'] or file_hash(source) != row['segment']['sha256']:
                    raise JournalError('retirement raw changed or reappeared')
            elif intent is None:
                raise JournalError('missing raw without retirement intent')
            selected[name] = ref
        self.cache[index] = selected
        return selected

    def ref(self, ticket, cursor):
        row = certificate(ticket.certificate)
        index = int(row['journal'].split('/')[0][11:])
        selected = self.selection(index)
        name = row['journal']+'/'+row['segment']['name']
        if selected:
            if name not in selected or selected[name]['certificate'] != ticket.certificate.decode():
                raise JournalError('registered source missing or seal differs')
            return selected[name]
        return segment_ref(ticket)

    def read(self, ticket, cursor):
        reader = SegmentReader(budget=self.budget)
        result = reader.read(self.ref(ticket, cursor), cursor)
        self.read_counts[reader.reads[0]['source']] += 1
        return result

    def view(self, directory):
        index = int(directory.parent.name[11:])
        return ArchivedJournalView(directory, self) if self.selection(index) else VerifiedJournalView(directory)


class ArchivedJournalView:
    """Locked gzip-backed checkpoint view, bounded to one physical segment."""
    def __init__(self, directory, sources):
        self.directory, self.sources = directory, sources
        self.lock = None

    def __enter__(self):
        self.lock = lock_directory(self.directory)
        try:
            self.meta, self.cp = load_state(self.directory)
            if len(self.cp['segments']) > 64:
                raise JournalError('archived generation journal segment bound')
            for _ in self.records(): pass
            self.recovery = dict(last_sequence=self.cp['last_sequence'], last_record_sha256=self.cp['last_record_sha256'],
                uncommitted_suffixes=[], pending_checkpoint_files=sorted(p.name for p in self.directory.glob('.checkpoint.json.*.tmp')))
            return self
        except BaseException:
            self.__exit__()
            raise

    def records(self):
        if self.lock is None: raise JournalError('archived view closed')
        journal = str(self.directory.relative_to(self.sources.root))
        cursor = SegmentCursor(self.sources.root, journal, self.meta['run_id'], self.cp['metadata_sha256'])
        selected = self.sources.selection(int(self.directory.parent.name[11:]))
        expected = {journal+'/'+e['name'] for e in self.cp['segments']}
        if expected != {p for p in selected if p.startswith(journal+'/')}:
            raise JournalError('archive registry differs from checkpoint entries')
        known = {e['name'] for e in self.cp['segments']}
        if any(p.name not in known for p in self.directory.glob('segment-*.jsonl')):
            raise JournalError('extra raw file in retired closed generation')
        for entry in self.cp['segments']:
            ref = selected[journal+'/'+entry['name']]
            ticket = SealTicket(ref['certificate'].encode())
            if certificate(ticket.certificate)['segment'] != entry:
                raise JournalError('archive checkpoint entry differs')
            segment = self.sources.read(ticket, cursor)
            yield from segment.records()
            cursor = segment.cursor
        if cursor.sequence != self.cp['last_sequence'] or cursor.record_sha256 != self.cp['last_record_sha256']:
            raise JournalError('archive checkpoint terminal differs')

    def __exit__(self, *args):
        if self.lock is not None: self.lock.close(); self.lock = None
