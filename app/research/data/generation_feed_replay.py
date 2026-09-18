"""Continuous audit state for the opt-in generation capture format.

Seeds are evidence, not permission to restore a live market session. The reader
recomputes every seed from the preceding source before accepting a successor.
"""
import hashlib

from .compact_feed_intervals import CompactIntervals
from .durable_capture_log import JournalError, ZERO, encoded, integer, keys
from .durable_market_feed import MarketFeedProcessor
from .feed_audit_state_codec import pack


def sha(value):
    return hashlib.sha256(encoded(value)).hexdigest()


class GenerationReplay:
    def __init__(self, scope):
        self.scope = dict(scope)
        self.processor = MarketFeedProcessor()
        self.reducer = CompactIntervals(scope['window_start_ns'], scope['window_end_ns'], max_intervals=10000)
        self.raw_hash = self.audit_hash = ZERO
        self.batches = self.audit_bytes = 0
        self.previous_published = -1

    def seed(self):
        return dict(version=1, scope=self.scope, replay=pack(self.processor, self.reducer),
                    raw_hash=self.raw_hash, audit_hash=self.audit_hash, batches=self.batches,
                    audit_bytes=self.audit_bytes, previous_published=self.previous_published)

    def accept(self, rows, batch):
        keys(batch, 'first_sequence last_sequence record_sha256 committed_ns observation')
        begin = integer(batch['first_sequence'], 1)
        last = integer(batch['last_sequence'], begin)
        committed = integer(batch['committed_ns'])
        published = integer(batch['observation']['published_ns'])
        if (begin != self.processor.sequence+1 or len(rows) != last-begin+1 or
                len(rows) > 2048 or committed < self.previous_published or published < committed):
            raise JournalError('generation audit sequence, pending bound or clock differs')
        exclusions = []
        for sequence, row in enumerate(rows, begin):
            keys(row, 'sequence epoch previous_record_sha256 payload sha256')
            body = {k:v for k,v in row.items() if k != 'sha256'}
            payload = row['payload']
            if (row['sequence'] != sequence or row['previous_record_sha256'] != self.raw_hash or
                    row['sha256'] != sha(body) or row['epoch'] != payload['process_epoch']):
                raise JournalError('global raw sequence, epoch or hash chain differs')
            if sequence == 1 and (payload['kind'] != 'RUN_WINDOW' or
                    payload['started_ns'] != self.scope['window_start_ns'] or
                    payload['deadline_ns'] != self.scope['window_end_ns']):
                raise JournalError('original run window differs')
            before = len(self.processor.errors)
            self.processor.apply(sequence, payload, processed_ns=committed)
            if payload['kind'] in ('OPEN', 'END', 'FAULT', 'STOP') or len(self.processor.errors) > before:
                exclusions.append([payload['received_ns'], published])
            self.raw_hash = row['sha256']
        if self.raw_hash != batch['record_sha256']:
            raise JournalError('global audit fence differs')
        p = self.processor
        observation = p.observe(now_ns=published, committed_ns=committed, committed_sequence=last)
        if observation != batch['observation']:
            raise JournalError('generation observation differs from raw replay')
        expiries = {}
        if not p.errors and not p.closed and observation['within_window']:
            age = dict(l2=min(p.depth_received_ns+10**9, p.book.available_ns+10**9)
                       if observation['gates']['l2'] else None,
                       market_connection=p.market_received_ns+3*10**9 if observation['gates']['market_connection'] else None,
                       mark=p.mark_received_ns+3*10**9 if observation['gates']['mark'] else None,
                       clock=p.watchdog_ns+500_000_000 if observation['gates']['clock'] else None,
                       durable_log=self.scope['window_end_ns'])
            expiries = {k:v for k,v in age.items() if v is not None}
        self.reducer.add(published, expiries, exclusions)
        self.batches += 1
        self.audit_bytes += len(encoded(batch))
        self.previous_published = published
        self.audit_hash = hashlib.sha256(bytes.fromhex(self.audit_hash)+encoded(batch)).hexdigest()

    def summary(self, *, complete):
        intervals, exclusions = self.reducer.finish()
        r, p = self.reducer, self.processor
        return dict(status='AUDIT_PREFIX_COMPLETE' if complete else 'AUDITED_PREFIX_AWAITING_MORE',
                    **self.scope, epoch=p.epoch, intervals=intervals, exclusions=exclusions,
                    valid_batches=self.batches, last_audited_sequence=p.sequence,
                    first_audited_publication_ns=r.first,
                    last_audited_publication_ns=self.previous_published if r.points else None,
                    valid_audit_bytes=self.audit_bytes, errors=[], processor_errors=list(p.errors),
                    clean_stop_audited=p.closed, continuous_runtime_coverage_certified=False,
                    interval_reduction=dict(points=r.points, peak_merged_intervals=r.peak,
                                            max_intervals=r.limit, failed=r.failed))
