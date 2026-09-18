"""Offline, opt-in retirement of closed captures after full gzip replay.

The policy must be registered before capture files exist. Historical captures
without that policy are never eligible. Old raw-dependent recovery APIs are not
used after retirement; the pinned manifest is the archive-only replay route.
"""
from contextlib import ExitStack
import os
from pathlib import Path
import uuid

from .archive_segment_reader import SegmentReader, cursor_dict, restore_cursor, segment_ref
from .durable_capture_log import JournalError, decoded, encoded, file_hash, keys, lock_directory, sync_directory
from .incremental_feed_audit import IncrementalFeedAudit
from .recover_sealed_pipeline import archive_identity
from .sealed_segment_handoff import SealTicket, certificate, read_segment, sha
from .segment_archive import SegmentArchive
from .verified_journal_view import VerifiedJournalView
from .work_receipt_ledger import WorkReceiptLedger, implementation_hashes

MAX_PLAN_BYTES=4*1024**2
MAX_ENTRIES=1024
SEMANTIC_FIELDS=('status','clock_domain','epoch','window_start_ns','window_end_ns','intervals','exclusions',
    'valid_batches','last_audited_sequence','first_audited_publication_ns','last_audited_publication_ns',
    'valid_audit_bytes','errors','processor_errors','clean_stop_audited',
    'continuous_runtime_coverage_certified','interval_reduction')


def sources():
    return implementation_hashes() | {'closed_capture_retirement.py':file_hash(Path(__file__))}


def register_retention_policy(budget):
    """Opt in on an empty owned run only; no retrofit onto retained evidence."""
    with budget.mutation():
        if {p.name for p in budget.root.iterdir()}!={'storage.json','.writer.lock'}:
            raise JournalError('retention policy must precede all capture data')
        policy=dict(version=1,root=str(budget.root),run_id=budget.contract['run_id'],
            mode='CLOSED_CAPTURE_GZIP_REPLAY_BEFORE_RAW_RETIREMENT',source_hashes=sources())
        budget.atomic_json(budget.root/'raw_retention_policy.json',policy)
        return file_hash(budget.root/'raw_retention_policy.json')


def policy(budget):
    path=budget.path(budget.root/'raw_retention_policy.json')
    if not path.is_file() or path.stat().st_size>32768: raise JournalError('prior retention policy missing or oversized')
    row=decoded(path.read_bytes())
    expected=dict(version=1,root=str(budget.root),run_id=budget.contract['run_id'],
        mode='CLOSED_CAPTURE_GZIP_REPLAY_BEFORE_RAW_RETIREMENT',source_hashes=sources())
    if row!=expected: raise JournalError('retention policy or implementation binding')
    return file_hash(path)


def semantic(summary):
    return decoded(encoded({k:summary[k] for k in SEMANTIC_FIELDS}))


def archive_store(budget,entry):
    ref=entry['ref']; store=object.__new__(SegmentArchive)
    store.budget=budget; store.directory=budget.path(budget.root/ref['archive']['directory'])
    row=store._descriptor(ref['archive']['archive_id'])
    if file_hash(store.directory/(row['archive_id']+'.json'))!=entry['descriptor_sha256']:
        raise JournalError('retirement descriptor changed')
    return store,row


def verify_archive(budget,entry):
    store,row=archive_store(budget,entry)
    reader=SegmentReader(budget=budget)
    value=reader.read(entry['ref'],restore_cursor(entry['cursor']))
    if cursor_dict(value.cursor)!=entry['next_cursor']: raise JournalError('retirement archive endpoint differs')
    store._sync_registered(row)
    return value.raw


def replay_plan(budget,plan):
    """Cold state, explicit gzip refs only. Preserve replay evidence and orphans."""
    if len(list(budget.root.glob('retirement-replay-*')))>=16:
        raise JournalError('retirement replay attempt bound')
    directory=budget.path(budget.root/('retirement-replay-'+uuid.uuid4().hex))
    with budget.mutation(): directory.mkdir(); sync_directory(budget.root)
    summaries=[]
    for index,epoch in enumerate(plan['epochs']):
        owner=IncrementalFeedAudit.create(directory/f'epoch-{index:02d}',budget=budget,contract=epoch['contract'])
        try:
            for unit in epoch['units']:
                owner.advance(plan['entries'][unit['audit']]['ref'],[plan['entries'][i]['ref'] for i in unit['raw']])
            summary=owner.finalize(raw_cursor=restore_cursor(epoch['raw_cursor']),
                                   audit_cursor=restore_cursor(epoch['audit_cursor']))
            if semantic(summary)!=epoch['expected']: raise JournalError('gzip replay differs from completed capture')
            summaries.append(summary)
        finally: owner.close()
    proof=dict(summaries=summaries,semantic_fields=list(SEMANTIC_FIELDS),explicit_source='GZIP_ONLY',
               live_market_state_restored=False)
    budget.atomic_json(directory/'proof.json',proof)
    return dict(path=str((directory/'proof.json').relative_to(budget.root)),sha256=file_hash(directory/'proof.json'),
                epochs=len(summaries),fields_each=len(SEMANTIC_FIELDS))


def prepare_retirement(budget,*,work_anchor,hook=lambda stage:None):
    policy_hash=policy(budget)
    if budget.snapshot()['reserved_bytes']: raise JournalError('active workers prohibit retirement')
    target=budget.path(budget.root/'retirement')
    with budget.mutation():
        if target.exists(): raise JournalError('retirement directory already exists; inspect or resume existing plan')
        target.mkdir();sync_directory(budget.root)
    with ExitStack() as stack:
        stack.callback(lock_directory(target).close)
        ledger=WorkReceiptLedger.resume(budget.root/'work-ledger',budget=budget,anchor=work_anchor)
        stack.callback(ledger.close)
        if not ledger.model['complete']: raise JournalError('retirement requires completed work ledger')
        entries=[];epochs=[];journals={};seen=set()
        for c in ledger.model['epochs']:
            views={}
            for kind in ('raw','audit'):
                cursor=restore_cursor(c['contract'][kind+'_initial'])
                view=stack.enter_context(VerifiedJournalView(budget.path(budget.root/cursor.journal)))
                if view.recovery['uncommitted_suffixes'] or view.recovery['pending_checkpoint_files']:
                    raise JournalError('uncertain journal tail prohibits retirement')
                if view.cp['last_sequence']!=c[kind+'_cursor']['sequence']:
                    raise JournalError('unadmitted journal endpoint')
                views[kind]=view
                journals[cursor.journal]={name:file_hash(view.directory/name) for name in ('metadata.json','checkpoint.json')}
            owner=IncrementalFeedAudit.resume(budget.root/c['directory']/'replay-state',budget=budget,
                                              contract=c['contract'],anchor=c['receipt'])
            try: expected=semantic(owner.summary())
            finally: owner.close()
            if expected['errors'] or expected['processor_errors'] or not expected['clean_stop_audited']:
                raise JournalError('invalid audit cannot authorize retirement')
            cursors={k:restore_cursor(c['contract'][k+'_initial']) for k in ('raw','audit')}
            units=[]
            for index in c['unit_ids']:
                u=ledger.model['units'][index]; ids={'raw':[],'audit':[]}
                for kind in ('raw','audit'):
                    for text in u[kind+'_tickets']:
                        ticket=SealTicket(text.encode());row=certificate(ticket.certificate)
                        raw=read_segment(ticket,cursors[kind]);source=str(Path(row['journal'])/row['segment']['name'])
                        if source in seen: raise JournalError('duplicate retirement source')
                        seen.add(source)
                        archive_dir=str(Path(c['directory'])/('raw-archives' if kind=='raw' else 'audit-archives'))
                        archive_id=sha(encoded(archive_identity(row)))
                        entry=dict(source=source,bytes=row['segment']['bytes'],sha256=row['segment']['sha256'],
                            ref=segment_ref(ticket,archive_directory=archive_dir,archive_id=archive_id),
                            cursor=cursor_dict(cursors[kind]),next_cursor=cursor_dict(raw.cursor),
                            descriptor_sha256=file_hash(budget.root/archive_dir/(archive_id+'.json')))
                        if verify_archive(budget,entry)!=raw.raw: raise JournalError('raw and gzip bytes differ')
                        ids[kind].append(len(entries));entries.append(entry);cursors[kind]=raw.cursor
                        if len(entries)>MAX_ENTRIES: raise JournalError('retirement entry bound')
                units.append(dict(raw=ids['raw'],audit=ids['audit'][0]))
            for kind,view in views.items():
                admitted={Path(e['source']).name for e in entries if str(Path(e['source']).parent)==str(view.directory.relative_to(budget.root))}
                if admitted!={e['name'] for e in view.cp['segments']}: raise JournalError('journal segment set differs')
            epochs.append(dict(contract=c['contract'],raw_cursor=c['raw_cursor'],audit_cursor=c['audit_cursor'],
                               expected=expected,units=units))
        plan=dict(version=1,root=str(budget.root),run_id=budget.contract['run_id'],policy_sha256=policy_hash,
                  source_hashes=sources(),work_anchor=ledger.anchor(),journals=journals,entries=entries,epochs=epochs)
        proof=replay_plan(budget,plan);plan['proof']=proof
        if len(encoded(plan))>MAX_PLAN_BYTES: raise JournalError('retirement plan size')
        hook('before_plan')
        budget.atomic_json(target/'plan.json',plan,lambda s:hook('plan:'+s))
        return dict(plan_sha256=file_hash(target/'plan.json'))


def load_plan(budget,anchor):
    keys(anchor,'plan_sha256')
    path=budget.path(budget.root/'retirement/plan.json')
    if not path.is_file() or path.stat().st_size>MAX_PLAN_BYTES or file_hash(path)!=anchor['plan_sha256']:
        raise JournalError('retirement plan missing, oversized or differs from external anchor')
    plan=decoded(path.read_bytes())
    keys(plan,'version root run_id policy_sha256 source_hashes work_anchor journals entries epochs proof')
    if (plan['version']!=1 or plan['root']!=str(budget.root) or plan['run_id']!=budget.contract['run_id'] or
            plan['policy_sha256']!=policy(budget) or plan['source_hashes']!=sources()):
        raise JournalError('retirement plan binding')
    proof=budget.path(budget.root/plan['proof']['path'])
    if file_hash(proof)!=plan['proof']['sha256']: raise JournalError('pre-retirement replay proof differs')
    if not 1<=len(plan['entries'])<=MAX_ENTRIES: raise JournalError('retirement entry count')
    return plan


def locked_sources(stack,budget,plan):
    for name,bindings in sorted(plan['journals'].items()):
        directory=budget.path(budget.root/name)
        stack.callback(lock_directory(directory).close)
        for file,expected in bindings.items():
            if file_hash(directory/file)!=expected: raise JournalError('journal metadata changed after preparation')


def retire_raw(budget,*,anchor,hook=lambda stage:None):
    """Recover or finish intended unlinks; only manifest-listed raw files qualify.

    Every registered gzip is reverified before any deletion and again before its
    unlink. Existing intent plus valid archive is required for an absent source.
    """
    with budget.mutation(),ExitStack() as stack:
        plan=load_plan(budget,anchor);directory=budget.root/'retirement'
        stack.callback(lock_directory(directory).close)
        locked_sources(stack,budget,plan)
        if budget.snapshot()['reserved_bytes']: raise JournalError('active worker reservations')
        for entry in plan['entries']: verify_archive(budget,entry)
        # Reject damaged/unexplained source state before retiring even the first
        # entry. Repeat the per-entry check below at the actual mutation boundary.
        for index,entry in enumerate(plan['entries']):
            source=budget.path(budget.root/entry['source'])
            intent=budget.path(directory/f'intent-{index:04d}.json')
            done=budget.path(directory/f'done-{index:04d}.json')
            binding=dict(plan_sha256=anchor['plan_sha256'],entry=index,source=entry['source'],
                         bytes=entry['bytes'],sha256=entry['sha256'])
            for path in (intent,done):
                if path.exists() and (path.stat().st_size>4096 or decoded(path.read_bytes())!=binding):
                    raise JournalError('retirement receipt binding')
                if path.exists():
                    with path.open('rb') as stream: os.fsync(stream.fileno())
            if done.exists() and (not intent.exists() or source.exists()):
                raise JournalError('completed retirement source reappeared or intent lost')
            if not source.exists() and not intent.exists(): raise JournalError('missing raw without durable retirement intent')
            if source.exists() and (source.stat().st_size!=entry['bytes'] or file_hash(source)!=entry['sha256']):
                raise JournalError('raw source changed before retirement')
        sync_directory(directory)
        before=budget.snapshot()['used_bytes'];removed_now=0
        for index,entry in enumerate(plan['entries']):
            source=budget.path(budget.root/entry['source'])
            intent=budget.path(directory/f'intent-{index:04d}.json');done=budget.path(directory/f'done-{index:04d}.json')
            binding=dict(plan_sha256=anchor['plan_sha256'],entry=index,source=entry['source'],
                         bytes=entry['bytes'],sha256=entry['sha256'])
            for path in (intent,done):
                if path.exists() and (path.stat().st_size>4096 or decoded(path.read_bytes())!=binding):
                    raise JournalError('retirement receipt binding')
            if done.exists():
                if not intent.exists() or source.exists(): raise JournalError('completed retirement source reappeared or intent lost')
                continue
            if not intent.exists():
                if not source.is_file(): raise JournalError('missing raw without durable retirement intent')
                if source.stat().st_size!=entry['bytes'] or file_hash(source)!=entry['sha256']:
                    raise JournalError('raw source changed before retirement')
                budget.atomic_json(intent,binding,lambda s:hook('intent:'+s))
            with intent.open('rb') as f: os.fsync(f.fileno())
            sync_directory(directory)
            verify_archive(budget,entry)
            if source.exists():
                if source.stat().st_size!=entry['bytes'] or file_hash(source)!=entry['sha256']:
                    raise JournalError('raw source changed after retirement intent')
                hook('before_unlink')
                source.unlink();budget._refresh(source);removed_now+=entry['bytes']
                hook('after_unlink')
            sync_directory(source.parent)
            hook('after_source_directory_fsync')
            budget.atomic_json(done,binding,lambda s:hook('done:'+s))
        budget.reconcile()
        return dict(status='CLOSED_CAPTURE_RAW_RETIRED',entries=len(plan['entries']),
            logical_raw_bytes=sum(e['bytes'] for e in plan['entries']),logical_raw_bytes_removed_this_call=removed_now,
            net_logical_reduction_this_call=before-budget.snapshot()['used_bytes'],
            physical_disk_reclamation_certified=False,raw_deletion_performed=removed_now>0,
            live_collector_retirement_integrated=False,live_market_state_restored=False)


def replay_retired_capture(budget,*,anchor):
    with ExitStack() as stack:
        plan=load_plan(budget,anchor)
        stack.callback(lock_directory(budget.root/'retirement').close)
        locked_sources(stack,budget,plan)
        for entry in plan['entries']: verify_archive(budget,entry)
        return replay_plan(budget,plan)
