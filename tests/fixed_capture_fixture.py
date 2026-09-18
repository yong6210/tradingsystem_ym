"""Offline, count-driven capture evidence; never a live-duration benchmark.

Exactly 152 raw records and 81 audit batches model four seconds of input. The
supervisor's original window is preserved; unused modeled time remains a gap.
No transport, sleeps, adaptive input size, fee or storage-threshold tuning.
"""
from pathlib import Path

from app.research.data.durable_capture_log import decoded
from app.research.data.durable_market_feed import MarketFeedProcessor
from app.research.data.durable_sealed_pipeline import DurableSealedPipeline
from app.research.data.scoped_feed_budget import ScopedFeedBudget
from app.research.data.sealed_segment_handoff import SealedJournal
from app.research.data.synthetic_feed_fixture import build_fixture
from app.research.data.verified_journal_view import VerifiedJournalView


async def populate_closed_attempt(owner):
    source = owner.budget.root.parent/'offline-source'
    model = build_fixture(source, 4, min_free_bytes=0)
    assert (model['raw_records'], model['audit_batches']) == (152, 81)
    start, end = owner.plan['window_start_ns'], owner.plan['window_end_ns']
    assert end-start > 4*10**9
    owner.log.append('ATTEMPT', dict(index=0, admitted_ns=start, wake_ns=start))
    root = owner.capture_root(0)
    with owner.budget.mutation():
        root.mkdir()
    view = ScopedFeedBudget(owner.budget, root)
    owner._initialize_capture_retention(view)
    pipeline = DurableSealedPipeline(view, _hook=owner._receipt_hook(0))
    directory = root/'epoch-00'
    directory.mkdir()
    raw = audit = None
    try:
        raw = SealedJournal.create(directory/'journal', budget=view, run_id=owner.plan['run_id'],
                                  rotation_bytes=8*1024**2, max_record_bytes=4*1024**2)
        audit = SealedJournal.create(directory/'audit', budget=view, run_id=owner.plan['run_id'],
                                    rotation_bytes=8*1024**2, max_record_bytes=4*1024**2)
        pipeline.add_epoch(directory, raw.initial_cursor(), audit.initial_cursor(), owner.scope())
        with VerifiedJournalView(source/'journal') as source_raw, VerifiedJournalView(source/'audit') as source_audit:
            rows = iter(source_raw.records())
            processor = MarketFeedProcessor()
            for source_batch in source_audit.records():
                batch = source_batch['payload']
                at = end if batch['committed_ns'] == 4*10**9 else start+batch['committed_ns']
                for _ in range(batch['last_sequence']-batch['first_sequence']+1):
                    row = next(rows)
                    payload = dict(row['payload'])
                    payload['received_ns'] = at
                    payload['received_utc_ns'] = 1_600_000_000_000_000_000+at-start
                    if 'started_ns' in payload: payload['started_ns'] = start
                    if 'deadline_ns' in payload: payload['deadline_ns'] = end
                    if 'expected_ns' in payload: payload['expected_ns'] += start
                    if 'request_started_ns' in payload: payload['request_started_ns'] += start
                    raw.epoch = row['epoch']
                    sequence = raw.append(payload)
                    processor.apply(sequence, payload, processed_ns=at)
                audit.append(dict(first_sequence=batch['first_sequence'], last_sequence=sequence,
                    record_sha256=raw.record_hash, committed_ns=at,
                    observation=processor.observe(now_ns=at, committed_ns=at, committed_sequence=sequence)))
            assert next(rows, None) is None and not processor.errors
        pipeline.submit(0, raw.seal(), audit.seal())
        pipeline.end_epoch(0)
        raw.close(); audit.close()
        await pipeline.drain()
        result = dict(index=0, outcome='ORIGINAL_DEADLINE', interrupted=False,
                      audits=[channel['result'] for channel in pipeline.channels],
                      pipeline=pipeline.snapshot(), offline_fixture=True,
                      actual_transport_requests=0, modeled_raw_records=152, modeled_audit_batches=81)
    finally:
        if raw is not None: raw.close()
        if audit is not None: audit.close()
        await pipeline.close()
    result['pipeline'] = pipeline.snapshot()
    owner._end(0, 'ORIGINAL_DEADLINE', result)
    owner.log.append('FINISH', dict(reason='ORIGINAL_DEADLINE'))
    return owner.summary()
