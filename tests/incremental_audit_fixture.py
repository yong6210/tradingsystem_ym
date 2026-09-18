"""Offline resegmentation of a tiny synthetic fixture, preserving raw hash chain."""
from pathlib import Path

from app.research.data.archive_segment_reader import segment_ref
from app.research.data.background_segment_archive import advance_cursor
from app.research.data.durable_capture_log import decoded
from app.research.data.durable_market_feed import MarketFeedProcessor
from app.research.data.reserved_feed_storage import ReservedStorageBudget
from app.research.data.sealed_segment_handoff import SealedJournal, certificate
from app.research.data.segment_archive import SegmentArchive
from app.research.data.synthetic_feed_fixture import build_fixture
from app.research.data.verified_journal_view import VerifiedJournalView
from app.research.data.snapshot_feed_audit import audit_epoch
from app.research.data.incremental_feed_audit import make_contract


def fixture(base,*,per_record=False,buffered=False,raw_step=5,audit_step=2,seconds=1,
            source=None,scope=None,audit_mutation=None):
    base=Path(base)
    if source is None:
        source=base/'source';plan=build_fixture(source,seconds,min_free_bytes=0)
    else:
        source=Path(source)
        plan=dict(scope,run_id=decoded((source/'journal/metadata.json').read_bytes())['run_id'])
    with VerifiedJournalView(source/'journal') as view: rows=list(view.records())
    with VerifiedJournalView(source/'audit') as view: audits=list(view.records())
    root=base/'capture'
    budget=ReservedStorageBudget.create(root,run_id=plan['run_id'],max_bytes=64*1024**2,min_free_bytes=0)
    raw=SealedJournal.create(root/'raw',budget=budget,run_id=plan['run_id'],rotation_bytes=8*1024**2,max_record_bytes=4*1024**2)
    audit=SealedJournal.create(root/'audit',budget=budget,run_id=plan['run_id'],rotation_bytes=8*1024**2,max_record_bytes=4*1024**2)
    raw.epoch=rows[0]['epoch'];audit.epoch=audits[0]['epoch']
    initial_raw,initial_audit=raw.initial_cursor(),audit.initial_cursor()
    payloads=[r['payload'] for r in rows]
    if buffered:
        payloads[4],payloads[5]=payloads[5],payloads[4]
        per_record=True
    raw_tickets=[];audit_tickets=[];new_audits=[];processor=MarketFeedProcessor()
    try:
        for index,payload in enumerate(payloads,1):
            raw.append(payload)
            if per_record:
                at=payload['received_ns'];processor.apply(index,payload,processed_ns=at)
                new_audits.append(dict(first_sequence=index,last_sequence=index,record_sha256=raw.record_hash,
                    committed_ns=at,observation=processor.observe(now_ns=at,committed_ns=at,committed_sequence=index)))
            if index%raw_step==0:raw_tickets.extend(raw.seal())
        raw_tickets.extend(raw.seal())
        for index,batch in enumerate(new_audits if per_record else [r['payload'] for r in audits],1):
            if audit_mutation is not None:batch=audit_mutation(index,batch)
            audit.append(batch)
            if index%audit_step==0:audit_tickets.extend(audit.seal())
        audit_tickets.extend(audit.seal())
    finally:
        raw.close();audit.close()
    scope={k:plan[k] for k in ('window_start_ns','window_end_ns','clock_domain')}
    expected=audit_epoch(root/'raw',root/'audit',**scope,max_intervals=10000)
    if audit_mutation is None:assert expected['status']=='AUDIT_PREFIX_COMPLETE',expected['errors']
    contract=make_contract(initial_raw,initial_audit,**scope)
    final_raw,final_audit=initial_raw,initial_audit
    for t in raw_tickets:final_raw=advance_cursor(certificate(t.certificate),final_raw)
    for t in audit_tickets:final_audit=advance_cursor(certificate(t.certificate),final_audit)
    return dict(root=root,budget=budget,contract=contract,scope=scope,raw_tickets=raw_tickets,
                audit_tickets=audit_tickets,raw_cursor=final_raw,audit_cursor=final_audit,expected=expected)


def jobs(fix,*,compressed=False):
    refs={}
    for kind in ('raw','audit'):
        store=SegmentArchive(fix['root']/(kind+'-archives'),budget=fix['budget']) if compressed else None
        refs[kind]=[]
        for ticket in fix[kind+'_tickets']:
            if store:
                row=certificate(ticket.certificate)
                archive=store.publish(fix['root']/kind,row['segment']['name'])
                ref=segment_ref(ticket,archive_directory=kind+'-archives',archive_id=archive['archive_id'])
            else:ref=segment_ref(ticket)
            refs[kind].append(ref)
    index=0;loaded_end=0;result=[]
    for audit_ref in refs['audit']:
        row=decoded(audit_ref['certificate'])
        # Payload boundary is fixture planning only, never input to the reader.
        path=fix['root']/'audit'/row['segment']['name']
        last=decoded(path.read_bytes().splitlines()[-1])['payload']['last_sequence']
        raw_refs=[]
        while loaded_end<last:
            ref=refs['raw'][index];index+=1;raw_refs.append(ref)
            loaded_end=decoded(ref['certificate'])['last_sequence']
        result.append((audit_ref,raw_refs))
    assert index==len(refs['raw'])
    return result


COMPARABLE=('status','clock_domain','epoch','window_start_ns','window_end_ns','intervals','exclusions',
    'valid_batches','last_audited_sequence','first_audited_publication_ns','last_audited_publication_ns',
    'valid_audit_bytes','errors','processor_errors','clean_stop_audited','continuous_runtime_coverage_certified','interval_reduction')
