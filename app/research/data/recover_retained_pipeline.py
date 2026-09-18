"""Offline mixed-source recovery of admitted collector work; no live eligibility.

One exclusive storage owner and external ledger receipt are required. Unknown
raw tails, unadmitted seals, archive orphans and temporary events are preserved.
"""
import asyncio
import time

from .archive_segment_reader import SegmentReader, restore_cursor, segment_ref
from .collector_custody_ledger import CustodyLedger, validate_work
from .recovery_custody_journal import RecoveryCustodyJournal
from .background_segment_archive import ArchiveLimits
from .durable_capture_log import JournalError, encoded, keys
from .durable_sealed_pipeline import archive_factory, audit_factory
from .incremental_feed_audit import IncrementalFeedAudit
from .sealed_segment_handoff import SealTicket, certificate, read_segment, sha
from .work_receipt_ledger import WorkReceiptLedger
from .recover_sealed_pipeline import archive_identity, wait_result, check_position


async def recover_retained_work(budget, *, handle, hook=lambda stage: None):
    """Bounded historical continuation; caller owns budget lock and closes it.

    Revalidates all admitted source/archive bytes offline. It does not silently
    adopt seals that lack a UNIT event, or certify clean end for an open epoch.
    """
    keys(handle, 'work_anchor custody_anchor')
    ledger = WorkReceiptLedger.resume(budget.root/'work-ledger', budget=budget, anchor=handle['work_anchor'], hook=hook)
    managers, owners, outputs = [], [], []
    registry = None; journals = {}; removed = 0; gzip_reads = raw_reads = 0
    started = time.monotonic_ns()
    try:
        registry = CustodyLedger.resume(budget.root/'collector-custody', budget=budget,
                                       anchor=handle['custody_anchor'], hook=hook)
        validate_work(registry, ledger)
        # Validate the entire mixed prefix before any recovery unlink or work.
        # RecoveryCustodyJournal.open_for_recovery does not restore a market processor.
        for index, handles in enumerate(registry.model['epochs']):
            contract = ledger.model['epochs'][index]['contract']
            for kind, key in [('raw','raw_initial'), ('audit_log','audit_initial')]:
                directory = budget.path(budget.root/contract[key]['journal'])
                journals[(index,kind)] = RecoveryCustodyJournal.open_for_recovery(directory, budget=budget,
                    handle=handles[kind], hook=hook)
        for entry in registry.model['retained'].values():
            for kind, names in entry['names'].items():
                if names:
                    removed += journals[(entry['channel'],kind)].finish_retirement(names=names)['raw_bytes_removed_this_call']
        ledger.append('RECOVERY', dict(attempt=ledger.model['recoveries']+1))
        limits = ArchiveLimits(**ledger.model['contract']['worker_limits'])
        async with asyncio.timeout(120):
            for index in range(len(ledger.model['epochs'])):
                c = ledger.model['epochs'][index]
                directory = budget.root/c['directory']
                owner = IncrementalFeedAudit.resume(directory/'replay-state', budget=budget,
                    contract=c['contract'], anchor=c['receipt'])
                owners.append(owner)
                raw = archive_factory(directory/'raw-archives', budget=budget,
                    cursor=restore_cursor(c['contract']['raw_initial']), limits=limits)
                audit_log = archive_factory(directory/'audit-archives', budget=budget,
                    cursor=restore_cursor(c['contract']['audit_initial']), limits=limits)
                auditor = audit_factory(owner, limits=limits)
                managers.extend([raw, audit_log, auditor])
                units = [ledger.model['units'][i] for i in c['unit_ids']]
                # A checkpoint can be at the last ledger receipt, or one linked
                # successor whose lost receipt is reconstructed from exact inputs.
                advanced = owner.receipt()['revision'] == c['receipt']['revision']+1
                if advanced:
                    if c['done'] < len(units):
                        target = units[c['done']]
                        check_position(owner, target, finalized=False)
                        ledger.append('AUDIT', dict(unit=target['index'], receipt=owner.receipt()))
                    elif c['closed'] and not c['final']:
                        check_position(owner, c, finalized=True)
                        ledger.append('FINAL', dict(channel=index, receipt=owner.receipt()))
                    else: raise JournalError('unrecorded checkpoint has no authorized operation')
                # Matching receipt also has to bind the expected source endpoint.
                current = ledger.model['epochs'][index]
                expected = units[current['done']-1] if current['done'] else dict(
                    raw_cursor=c['contract']['raw_initial'], audit_cursor=c['contract']['audit_initial'])
                check_position(owner, expected, finalized=current['final'])
                for unit in units:
                    refs = []
                    for kind, tickets in [('raw',unit['raw_tickets']),('audit_log',unit['audit_tickets'])]:
                        manager = raw if kind == 'raw' else audit_log
                        for text in tickets:
                            ticket = SealTicket(text.encode()); row = certificate(ticket.certificate)
                            journal = journals[(index,kind)]
                            name = row['segment']['name']
                            if name in journal.custody_anchors:
                                ref = journal._load(name)['ref']
                                if ref['certificate'] != text:
                                    raise JournalError('custody certificate differs from admitted work')
                                verified = SegmentReader(budget=budget).read(ref, manager.cursor)
                                gzip_reads += 1
                            else:
                                verified = read_segment(ticket, manager.cursor)
                                raw_reads += 1
                            identity = archive_identity(row); archive_id = sha(encoded(identity))
                            path = manager.store.directory/(archive_id+'.json')
                            if path.exists():
                                descriptor = manager.store._descriptor(archive_id)
                                if descriptor['identity'] != identity or any(descriptor['witness'][k]!=row[k]
                                    for k in ('first_sequence','last_sequence','last_record_sha256')):
                                    raise JournalError('registered archive differs from admitted ticket')
                                manager.store._sync_registered(descriptor)
                                manager.cursor = verified.cursor
                            else:
                                if name in journal.custody_anchors:
                                    raise JournalError('retired archive registration missing')
                                job = manager.submit(ticket)
                                descriptor = await wait_result(manager, job)
                            refs.append(segment_ref(ticket, archive_directory=str(manager.store.directory.relative_to(budget.root)),
                                                    archive_id=descriptor['archive_id']))
                    if ledger.model['units'][unit['index']]['receipt'] is None:
                        job = auditor.submit(refs[-1], refs[:-1])
                        receipt = await wait_result(auditor, job)
                        hook('recovery_before_audit_receipt')
                        ledger.append('AUDIT', dict(unit=unit['index'], receipt=receipt))
                current = ledger.model['epochs'][index]
                if current['closed'] and not current['final']:
                    job = auditor.submit_finalize(raw_cursor=restore_cursor(current['raw_cursor']),
                                                   audit_cursor=restore_cursor(current['audit_cursor']))
                    receipt = await wait_result(auditor, job)
                    hook('recovery_before_final_receipt')
                    ledger.append('FINAL', dict(channel=index, receipt=receipt))
                outputs.append(dict(channel=index, closed_was_durable=current['closed'], summary=owner.summary(),
                    raw_cursor=current['raw_cursor'], audit_cursor=current['audit_cursor']))
            if ledger.model['epochs'] and all(c['final'] for c in ledger.model['epochs']) and not ledger.model['complete']:
                ledger.append('COMPLETE', {})
        admitted = {str(budget.root/certificate(t.encode())['journal']/certificate(t.encode())['segment']['name'])
            for u in ledger.model['units'] for t in u['raw_tickets']+u['audit_tickets']}
        # Report, do not adopt or delete. Lists are bounded by the existing run
        # storage inventory and only include raw/audit journal segment paths.
        unadmitted = [str(p.relative_to(budget.root)) for p in sorted(budget.root.rglob('segment-*.jsonl'))
            if str(p) not in admitted and p.parent.name != 'supervisor']
        return dict(status='ADMITTED_CLOSED_EPOCHS_RECOVERED' if ledger.model['complete'] else 'ADMITTED_PREFIX_ONLY_INTERRUPTED_RUN',
            epochs=outputs, work_ledger_anchor=ledger.anchor(), work_ledger_complete=ledger.model['complete'],
            work_ledger_events=len(ledger.events), unadmitted_segment_files=unadmitted,
            elapsed_ns=time.monotonic_ns()-started, original_window_preserved=True,
            full_original_run_certified=False,
            continuous_runtime_coverage_certified=False, live_market_state_restored=False,
            resumed_network_requests=0, actual_orders=0, original_deletion=removed > 0, automatic_live_restart=False,
            retention_handle=dict(work_anchor=ledger.anchor(), custody_anchor=registry.anchor()),
            registered_retired_units=len(registry.model['retained']),
            logical_raw_bytes_removed_this_call=removed, gzip_source_reads=gzip_reads, raw_source_reads=raw_reads,
            mixed_source_recovery_integrated=True,
            preserved_uncommitted_suffixes=[s for j in journals.values() for s in j.preserved_suffixes])
    except BaseException:
        budget.failed = True
        raise
    finally:
        # Own this cleanup independently of cancellation/repeated cancellation.
        async def cleanup():
            try: await asyncio.gather(*(m.close() for m in managers))
            finally:
                for owner in owners: owner.close()
                ledger.close()
                for journal in journals.values(): journal.close()
                if registry is not None: registry.close()
        task = asyncio.create_task(cleanup())
        cancelled = False
        while not task.done():
            try: await asyncio.shield(task)
            except asyncio.CancelledError: cancelled = True
        task.result()
        if cancelled: raise asyncio.CancelledError
