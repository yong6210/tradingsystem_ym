"""Read-only, byte-exact clean-path admission for frozen closed retirement v1.

This gate adds no deletion protocol. It admits preparation only when the entire
closed capture will shrink after preparation, all receipts, and a second durable
replay. Crash leftovers are preserved and are NOT covered by this clean-path
forecast. This is offline work, never a live collector callback.
"""
from contextlib import ExitStack
from pathlib import Path

from . import closed_capture_retirement as retirement
from .archive_segment_reader import cursor_dict, restore_cursor, segment_ref
from .compact_feed_intervals import CompactIntervals
from .durable_capture_log import JournalError, ZERO, decoded, encoded, file_hash, integer
from .durable_market_feed import MarketFeedProcessor
from .feed_audit_state_codec import pack
from .incremental_audit_protocol import ReplayProposal
from .incremental_feed_audit import IncrementalFeedAudit
from .recover_sealed_pipeline import archive_identity
from .sealed_segment_handoff import SealTicket, certificate, read_segment, sha
from .verified_journal_view import VerifiedJournalView
from .work_receipt_ledger import WorkReceiptLedger


class SizingReplay(ReplayProposal):
    """Frozen audit logic with only in-memory checkpoint writes."""

    @classmethod
    def cold(cls, contract):
        reducer = CompactIntervals(contract['window_start_ns'], contract['window_end_ns'],
                                   max_intervals=contract['max_intervals'])
        state = dict(replay=pack(MarketFeedProcessor(), reducer),
                     raw_position=dict(cursor=contract['raw_initial'], ref=None, consumed=0),
                     audit_cursor=contract['audit_initial'], valid_batches=0, valid_audit_bytes=0,
                     previous_published=-1, audit_payload_chain_sha256=ZERO, finalized=False)
        body = dict(version=1, contract=contract, revision=0,
                    previous_checkpoint_sha256=ZERO, state=state)
        obj = cls(body | dict(checkpoint_sha256=sha(encoded(body))))
        obj.peak_checkpoint_bytes = len(encoded(obj._doc))
        return obj

    def _write(self, state, *, revision, previous):
        super()._write(state, revision=revision, previous=previous)
        self.peak_checkpoint_bytes = max(self.peak_checkpoint_bytes, len(encoded(self._doc)))


def _unprepared(budget):
    budget.reconcile()
    retirement.policy(budget)
    if budget.snapshot()['reserved_bytes']:
        raise JournalError('active workers prohibit retirement admission')
    if (budget.root/'retirement').exists() or list(budget.root.glob('retirement-replay-*')):
        raise JournalError('existing retirement evidence requires recovery, not fresh admission')
    # Locks must already exist: the read-only gate must not create missing files.
    if not (budget.root/'work-ledger/.writer.lock').is_file():
        raise JournalError('existing work ledger lock required')


def _plan(budget, work_anchor, stack):
    """Reconstruct the frozen plan under the same source and writer checks."""
    ledger = WorkReceiptLedger.resume(budget.root/'work-ledger', budget=budget, anchor=work_anchor)
    stack.callback(ledger.close)
    if not ledger.model['complete']:
        raise JournalError('retirement requires completed work ledger')
    entries, epochs, journals, seen = [], [], {}, set()
    for channel in ledger.model['epochs']:
        views = {}
        for kind in ('raw', 'audit'):
            cursor = restore_cursor(channel['contract'][kind+'_initial'])
            directory = budget.path(budget.root/cursor.journal)
            if not (directory/'.writer.lock').is_file():
                raise JournalError('existing journal lock required')
            view = stack.enter_context(VerifiedJournalView(directory))
            if view.recovery['uncommitted_suffixes'] or view.recovery['pending_checkpoint_files']:
                raise JournalError('uncertain journal tail prohibits retirement')
            if view.cp['last_sequence'] != channel[kind+'_cursor']['sequence']:
                raise JournalError('unadmitted journal endpoint')
            views[kind] = view
            journals[cursor.journal] = {name: file_hash(directory/name)
                                       for name in ('metadata.json', 'checkpoint.json')}
        state_dir = budget.path(budget.root/channel['directory']/'replay-state')
        if not (state_dir/'.writer.lock').is_file():
            raise JournalError('existing replay lock required')
        owner = IncrementalFeedAudit.resume(state_dir, budget=budget,
                    contract=channel['contract'], anchor=channel['receipt'])
        try:
            expected = retirement.semantic(owner.summary())
        finally:
            owner.close()
        if expected['errors'] or expected['processor_errors'] or not expected['clean_stop_audited']:
            raise JournalError('invalid audit cannot authorize retirement')
        cursors = {kind: restore_cursor(channel['contract'][kind+'_initial']) for kind in ('raw', 'audit')}
        units = []
        for unit_id in channel['unit_ids']:
            unit = ledger.model['units'][unit_id]
            ids = dict(raw=[], audit=[])
            for kind in ('raw', 'audit'):
                for text in unit[kind+'_tickets']:
                    ticket = SealTicket(text.encode())
                    row = certificate(ticket.certificate)
                    raw = read_segment(ticket, cursors[kind])
                    source = str(Path(row['journal'])/row['segment']['name'])
                    if source in seen:
                        raise JournalError('duplicate retirement source')
                    seen.add(source)
                    archive_dir = str(Path(channel['directory'])/(kind+'-archives'))
                    archive_id = sha(encoded(archive_identity(row)))
                    entry = dict(source=source, bytes=row['segment']['bytes'], sha256=row['segment']['sha256'],
                        ref=segment_ref(ticket, archive_directory=archive_dir, archive_id=archive_id),
                        cursor=cursor_dict(cursors[kind]), next_cursor=cursor_dict(raw.cursor),
                        descriptor_sha256=file_hash(budget.path(budget.root/archive_dir/(archive_id+'.json'))))
                    if retirement.verify_archive(budget, entry) != raw.raw:
                        raise JournalError('raw and gzip bytes differ')
                    ids[kind].append(len(entries))
                    entries.append(entry)
                    cursors[kind] = raw.cursor
                    if len(entries) > retirement.MAX_ENTRIES:
                        raise JournalError('retirement entry bound')
            units.append(dict(raw=ids['raw'], audit=ids['audit'][0]))
        for kind, view in views.items():
            admitted = {Path(e['source']).name for e in entries
                        if str(Path(e['source']).parent) == str(view.directory.relative_to(budget.root))}
            if admitted != {e['name'] for e in view.cp['segments']}:
                raise JournalError('journal segment set differs')
        epochs.append(dict(contract=channel['contract'], raw_cursor=channel['raw_cursor'],
                           audit_cursor=channel['audit_cursor'], expected=expected, units=units))
    return dict(version=1, root=str(budget.root), run_id=budget.contract['run_id'],
                policy_sha256=retirement.policy(budget), source_hashes=retirement.sources(),
                work_anchor=ledger.anchor(), journals=journals, entries=entries, epochs=epochs)


def _replay_size(plan):
    summaries, final_bytes, peak_bytes = [], 0, 0
    for epoch in plan['epochs']:
        owner = SizingReplay.cold(epoch['contract'])
        try:
            for unit in epoch['units']:
                owner.advance(plan['entries'][unit['audit']]['ref'],
                              [plan['entries'][i]['ref'] for i in unit['raw']])
            summary = owner.finalize(raw_cursor=restore_cursor(epoch['raw_cursor']),
                                     audit_cursor=restore_cursor(epoch['audit_cursor']))
            if retirement.semantic(summary) != epoch['expected']:
                raise JournalError('gzip replay differs from completed capture')
            summaries.append(summary)
            final_bytes += len(encoded(owner._doc))
            peak_bytes = max(peak_bytes, owner.peak_checkpoint_bytes)
        finally:
            owner.close()
    proof = dict(summaries=summaries, semantic_fields=list(retirement.SEMANTIC_FIELDS),
                 explicit_source='GZIP_ONLY', live_market_state_restored=False)
    return proof, final_bytes, peak_bytes


def forecast_retirement(budget, *, work_anchor, minimum_net_savings_bytes=1):
    """No new files, no source deletion. Exact final bytes for two clean replays.

    The peak bound deliberately assumes all final metadata plus two temporary
    checkpoints coexist before any raw unlink. It is conservative, not an RSS
    or physical allocation prediction. Errors fail closed through frozen readers.
    """
    integer(minimum_net_savings_bytes, 1)
    _unprepared(budget)
    with ExitStack() as stack:
        plan = _plan(budget, work_anchor, stack)
        proof, checkpoint_bytes, peak_checkpoint = _replay_size(plan)
        # The frozen writer chooses a UUID; every possible value has 32 ASCII
        # bytes. Hashes also have fixed width. No timing/rounding extrapolation.
        plan['proof'] = dict(path='retirement-replay-'+'0'*32+'/proof.json',
                             sha256=sha(encoded(proof)), epochs=len(plan['epochs']), fields_each=17)
        plan_bytes = len(encoded(plan))
        if plan_bytes > retirement.MAX_PLAN_BYTES:
            raise JournalError('retirement plan size')
        receipt_bytes = sum(2*len(encoded(dict(plan_sha256=ZERO, entry=i, source=e['source'],
                                             bytes=e['bytes'], sha256=e['sha256'])))
                            for i, e in enumerate(plan['entries']))
        replay_bytes = checkpoint_bytes+len(encoded(proof))
        metadata = plan_bytes+receipt_bytes+2*replay_bytes
        raw_bytes = sum(e['bytes'] for e in plan['entries'])
        savings = raw_bytes-metadata
        admitted = savings >= minimum_net_savings_bytes
        return dict(version=1, status='ADMIT_CLOSED_RETIREMENT' if admitted else 'KEEP_RAW_NOT_ECONOMIC',
                    admitted=admitted, minimum_net_savings_bytes=minimum_net_savings_bytes,
                    closed_capture_bytes=budget.snapshot()['used_bytes'], raw_bytes=raw_bytes,
                    plan_bytes=plan_bytes, receipt_bytes=receipt_bytes, bytes_per_durable_replay=replay_bytes,
                    durable_replay_count=2, added_metadata_bytes=metadata,
                    projected_net_savings_bytes=savings,
                    projected_final_bytes=budget.snapshot()['used_bytes']-savings,
                    conservative_peak_growth_bytes=metadata+2*peak_checkpoint,
                    normalized_plan_sha256=sha(encoded(plan)), proof_sha256=sha(encoded(proof)),
                    implementation_sha256=file_hash(Path(__file__)), work_anchor=work_anchor,
                    crash_leftovers_included=False, physical_reclamation_certified=False,
                    active_collection_integrated=False)


def prepare_if_economic(budget, *, work_anchor, minimum_net_savings_bytes=1, hook=lambda stage: None):
    """Fresh preparation only. Persist the returned anchor outside the capture.

    On rejection nothing is written. Before any deletion callers must retain
    this result, then use frozen retire_raw and one replay_retired_capture. A
    crash goes to frozen recovery, never another fresh economic preparation.
    """
    estimate = forecast_retirement(budget, work_anchor=work_anchor,
                                   minimum_net_savings_bytes=minimum_net_savings_bytes)
    if not estimate['admitted']:
        return dict(estimate=estimate, anchor=None)
    budget.check(estimate['conservative_peak_growth_bytes'])
    anchor = retirement.prepare_retirement(budget, work_anchor=work_anchor, hook=hook)
    plan = retirement.load_plan(budget, anchor)
    plan['proof']['path'] = 'retirement-replay-'+'0'*32+'/proof.json'
    if sha(encoded(plan)) != estimate['normalized_plan_sha256']:
        raise JournalError('prepared plan differs from economic forecast; preserve raw and inspect')
    budget.reconcile()
    if budget.snapshot()['used_bytes']-estimate['closed_capture_bytes'] != (
            estimate['plan_bytes']+estimate['bytes_per_durable_replay']):
        raise JournalError('prepared footprint differs from forecast; preserve raw and inspect')
    return dict(estimate=estimate, anchor=anchor)
