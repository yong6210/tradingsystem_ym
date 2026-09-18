"""Compact interval version of the frozen segmented coverage replay.

These intervals describe the recorded input model, never exchange uptime or
absence of unobserved faults. No interval extends beyond the last audited point.
"""
from contextlib import closing, contextmanager
import hashlib
from pathlib import Path

from .durable_capture_log import decoded, iter_committed, inspect_journal, keys, integer, encoded
from .durable_market_feed import MarketFeedProcessor
from ..foundation.forward_data_contract import REQUIREMENTS
from .compact_feed_intervals import CompactIntervals, IntervalLimitError


class AuditLineStream:
    def __init__(self, records):
        self.records = records

    def readline(self, limit):
        row = next(self.records, None)
        return b'' if row is None else encoded(row['payload'])


@contextmanager
def committed_audit_lines(directory):
    with closing(iter_committed(directory)) as records:
        yield AuditLineStream(records)


def audit_summary(directory):
    recovery = inspect_journal(directory)
    size, digest = 0, hashlib.sha256()
    with closing(iter_committed(directory)) as records:
        for row in records:
            line = encoded(row['payload'])
            size += len(line)
            digest.update(line)
    return recovery, size, digest.hexdigest()


def audit_epoch(journal, audit_path, *, window_start_ns, window_end_ns, clock_domain, max_intervals=100_000):
    """Audit one process epoch against an externally fixed original run window.

    Caller must establish a common monotonic clock domain across processes;
    merely giving unrelated boots the same label does not synchronize them.
    Malformed/missing audit tails keep the validated prefix but never become
    invented observations. Committed-raw corruption rejects the whole epoch.
    """
    integer(window_start_ns)
    integer(window_end_ns, 1)
    if window_end_ns <= window_start_ns or type(clock_domain) is not str or not clock_domain:
        raise ValueError('fixed nonempty window and clock domain required')
    journal, audit_path = Path(journal), Path(audit_path)
    intervals = {name: [] for name in REQUIREMENTS}
    processor = MarketFeedProcessor()
    reducer = CompactIntervals(window_start_ns, window_end_ns, max_intervals=max_intervals)
    errors = []
    valid_bytes = valid_batches = 0
    accepted_sequence, previous_published = 0, -1
    epoch = None
    raw_count = 0
    raw_valid = False
    recovery = audit_recovery = None
    audit_size, source_hash = 0, None
    try:
        audit_recovery, audit_size, source_hash = audit_summary(audit_path)
        if (decoded((audit_path/'metadata.json').read_bytes())['run_id'] !=
                decoded((journal/'metadata.json').read_bytes())['run_id']):
            raise ValueError('raw and audit run identities differ')
        recovery = inspect_journal(journal)
        raw_count = recovery['last_sequence']
        if raw_count == 0:
            raise ValueError('no committed RUN_WINDOW')
        raw_valid = True
        with closing(iter_committed(journal)) as records:
            # iter_committed verifies the full prefix before yielding this row.
            first = next(records)
            first_payload = first['payload']
            if (first_payload['kind'] != 'RUN_WINDOW' or
                    first_payload['started_ns'] != window_start_ns or
                    first_payload['deadline_ns'] != window_end_ns):
                raise ValueError('epoch changed the original collection window')
            epoch = first['epoch']
            pending_first = first
            with committed_audit_lines(audit_path) as stream:
                while True:
                    line = stream.readline(4*1024**2+1)
                    if not line:
                        break
                    if len(line) > 4*1024**2 or not line.endswith(b'\n'):
                        raise ValueError('torn or oversized processing audit line')
                    batch = decoded(line)
                    keys(batch, 'first_sequence last_sequence record_sha256 committed_ns observation')
                    begin = integer(batch['first_sequence'], 1)
                    last = integer(batch['last_sequence'], 1)
                    committed = integer(batch['committed_ns'])
                    published = integer(batch['observation']['published_ns'])
                    if begin != accepted_sequence+1 or last < begin or last > raw_count:
                        raise ValueError('audit prefix sequence gap or uncommitted reference')
                    if committed < previous_published or published < committed:
                        raise ValueError('serialized processing clock regressed')
                    batch_exclusions = []
                    for sequence in range(begin, last+1):
                        row = pending_first if pending_first is not None else next(records)
                        pending_first = None
                        if row['sequence'] != sequence or row['epoch'] != epoch or row['payload']['process_epoch'] != epoch:
                            raise ValueError('raw sequence/process epoch mismatch')
                        payload = row['payload']
                        errors_before = len(processor.errors)
                        processor.apply(sequence, payload, processed_ns=committed)
                        # A lifecycle change was known by receipt time, even if
                        # the next fsync/publication happened later. Exclude the
                        # detection-to-processing span conservatively for all gates.
                        if (payload['kind'] in ('OPEN', 'END', 'FAULT', 'STOP') or
                                len(processor.errors) > errors_before):
                            batch_exclusions.append([payload['received_ns'], published])
                    if row['sha256'] != batch['record_sha256']:
                        raise ValueError('processing fence hash differs from raw prefix')
                    observation = processor.observe(now_ns=published, committed_ns=committed, committed_sequence=last)
                    if observation != batch['observation']:
                        raise ValueError('recorded observation differs from raw replay')
                    expiries = {}
                    if not processor.errors and not processor.closed and observation['within_window']:
                        age_deadlines = dict(
                            l2=min(processor.depth_received_ns+1_000_000_000, processor.book.available_ns+1_000_000_000)
                                if observation['gates']['l2'] else None,
                            market_connection=processor.market_received_ns+3_000_000_000
                                if observation['gates']['market_connection'] else None,
                            mark=processor.mark_received_ns+3_000_000_000 if observation['gates']['mark'] else None,
                            clock=processor.watchdog_ns+500_000_000 if observation['gates']['clock'] else None,
                            durable_log=window_end_ns)
                        expiries = {k: v for k, v in age_deadlines.items() if v is not None}
                    reducer.add(published, expiries, batch_exclusions)
                    valid_bytes += len(line)
                    valid_batches += 1
                    accepted_sequence, previous_published = last, published
        if accepted_sequence != raw_count:
            errors.append('COMMITTED_RAW_WITHOUT_AUDIT')
    except Exception as exc:
        errors.append(f'{type(exc).__name__}:{exc}')
    if recovery is not None and recovery['uncommitted_suffixes']:
        errors.append('UNCOMMITTED_RAW_SUFFIX_PRESENT')
    if recovery is not None and recovery['pending_checkpoint_files']:
        errors.append('PENDING_RAW_CHECKPOINT_PRESENT')
    try:
        intervals, excluded = reducer.finish()
    except IntervalLimitError as exc:
        # Resource failure never becomes partially truncated valid coverage.
        intervals, excluded = {name: [] for name in REQUIREMENTS}, []
        errors.append(type(exc).__name__+':'+str(exc))
    if audit_recovery is not None:
        if audit_recovery['uncommitted_suffixes']:
            errors.append('UNCOMMITTED_AUDIT_SUFFIX_PRESENT')
        if audit_recovery['pending_checkpoint_files']:
            errors.append('PENDING_AUDIT_CHECKPOINT_PRESENT')
    return dict(status='AUDIT_PREFIX_COMPLETE' if not errors else 'AUDIT_INCOMPLETE_OR_INVALID',
                clock_domain=clock_domain, epoch=epoch, window_start_ns=window_start_ns, window_end_ns=window_end_ns,
                intervals=intervals, exclusions=excluded, valid_batches=valid_batches,
                last_audited_sequence=accepted_sequence, committed_raw_records=raw_count,
                unaudited_committed_records=raw_count-accepted_sequence,
                last_audited_publication_ns=previous_published if reducer.points else None,
                first_audited_publication_ns=reducer.first,
                valid_audit_bytes=valid_bytes, unaudited_audit_bytes=audit_size-valid_bytes,
                audit_sha256=source_hash, audit_hash_scope="CANONICAL_COMMITTED_PAYLOAD_LINES",
                audit_recovery=audit_recovery, raw_prefix_valid=raw_valid, raw_recovery=recovery,
                errors=errors, processor_errors=list(processor.errors),
                clean_stop_audited=processor.closed and accepted_sequence == processor.sequence,
                continuous_runtime_coverage_certified=False,
                interval_reduction=dict(points=reducer.points, peak_merged_intervals=reducer.peak,
                                        max_intervals=reducer.limit, failed=reducer.failed))

