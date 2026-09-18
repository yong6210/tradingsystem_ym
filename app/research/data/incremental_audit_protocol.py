"""Read-only replay proposals and bounded parent validation, no dynamic loading.

The worker is trusted pinned code, not an adversarial prover. Parent checks
bindings/structure/continuity, but intentionally does not repeat market replay.
"""
from contextlib import contextmanager
from pathlib import Path

from .archive_segment_reader import SegmentReader,cursor_dict,restore_cursor
from .background_segment_archive import advance_cursor
from .durable_capture_log import JournalError,decoded,digest,encoded,file_hash,integer,keys
from .incremental_feed_audit import IncrementalFeedAudit,MAX_CHECKPOINT_BYTES,make_contract
from .sealed_segment_handoff import certificate,sha

MAX_REQUEST=10*1024**2
MAX_INPUTS=512*1024
MAX_REPLY=MAX_CHECKPOINT_BYTES+65536
SOURCES=('incremental_audit_protocol.py','incremental_audit_worker.py','background_incremental_audit.py',
         'background_segment_archive.py','sealed_archive_worker.py')


def worker_sources():
    return {name:file_hash(Path(__file__).parent/name) for name in SOURCES}


def check_document(doc):
    keys(doc,'version contract revision previous_checkpoint_sha256 state checkpoint_sha256')
    if type(doc['version']) is not int or doc['version']!=1:raise JournalError('proposal version')
    integer(doc['revision']);digest(doc['previous_checkpoint_sha256'])
    if len(encoded(doc))>MAX_CHECKPOINT_BYTES:raise JournalError('proposal checkpoint bound')
    if digest(doc['checkpoint_sha256'])!=sha(encoded({k:v for k,v in doc.items() if k!='checkpoint_sha256'})):
        raise JournalError('proposal checkpoint checksum')


def validate_inputs(operation,inputs):
    if len(encoded(inputs))>MAX_INPUTS:raise JournalError('audit request inputs bound')
    if operation=='advance':
        keys(inputs,'audit_ref raw_refs')
        if type(inputs['raw_refs']) is not list or len(inputs['raw_refs'])>16:raise JournalError('audit raw reference bound')
        for ref in [inputs['audit_ref'],*inputs['raw_refs']]:
            keys(ref,'certificate archive')
            if type(ref['certificate']) is not str:raise JournalError('audit ticket text')
            certificate(ref['certificate'].encode())
            if ref['archive'] is not None:
                keys(ref['archive'],'directory archive_id');digest(ref['archive']['archive_id'])
                value=ref['archive']['directory']
                if type(value) is not str or not value or len(value)>4096 or Path(value).is_absolute() or '..' in Path(value).parts:
                    raise JournalError('relative archive path required')
    elif operation=='finalize':
        keys(inputs,'raw_cursor audit_cursor')
        restore_cursor(inputs['raw_cursor']);restore_cursor(inputs['audit_cursor'])
    else:raise JournalError('audit operation unsupported')


class ReadOnlyBudget:
    """Filesystem reads only; deliberately has no append/atomic_json methods."""
    def __init__(self,contract):
        self.root=Path(contract['raw_initial']['root'])
        if self.root.resolve()!=self.root:raise JournalError('canonical audit root required')
        self.contract=dict(run_id=contract['raw_initial']['run_id'])
        self.failed=False

    def check(self,growth):
        if growth!=0 or self.failed:raise JournalError('read-only audit capability')

    def path(self,path):
        path=Path(path).absolute()
        if not path.is_relative_to(self.root) or path.resolve()!=path:raise JournalError('audit source path outside root')
        return path

    @contextmanager
    def mutation(self):
        # Frozen advance mutates only its private in-memory state. _write below
        # captures the proposed document; this capability cannot persist it.
        self.check(0)
        try:yield
        except BaseException:
            self.failed=True
            raise


class ReplayProposal(IncrementalFeedAudit):
    def __init__(self,document):
        check_document(document)
        self._doc=decoded(encoded(document));self.contract=self._doc['contract']
        contract=self.contract
        expected=make_contract(restore_cursor(contract['raw_initial']),restore_cursor(contract['audit_initial']),
            **{k:contract[k] for k in ('window_start_ns','window_end_ns','clock_domain','max_intervals')})
        if contract!=expected:raise JournalError('proposal implementation binding')
        self.budget=ReadOnlyBudget(contract);self.reader=SegmentReader(budget=self.budget)
        self.failed=self.closed=False;self.lock=None;self.hook=lambda stage:None
        self._validate_state(self._doc['state'])

    def _write(self,state,*,revision,previous):
        body=dict(version=1,contract=self.contract,revision=revision,previous_checkpoint_sha256=previous,state=state)
        doc=body|dict(checkpoint_sha256=sha(encoded(body)))
        check_document(doc);self._doc=decoded(encoded(doc))


def build_request(job_id,document,operation,inputs,rss_limit_bytes):
    check_document(document);validate_inputs(operation,inputs)
    body=dict(version=1,job_id=job_id,base_document=document,operation=operation,inputs=inputs,
              worker_sources=worker_sources(),rss_limit_bytes=rss_limit_bytes)
    request=body|dict(request_sha256=sha(encoded(body)))
    if len(encoded(request))>MAX_REQUEST:raise JournalError('audit request byte bound')
    return decoded(encoded(request))


def execute(request,peak_rss):
    keys(request,'version job_id base_document operation inputs worker_sources rss_limit_bytes request_sha256')
    if type(request['version']) is not int or request['version']!=1:raise JournalError('audit request version')
    integer(request['job_id']);integer(request['rss_limit_bytes'],1)
    if request['rss_limit_bytes']>384*1024**2:raise JournalError('audit RSS limit')
    if (request['worker_sources']!=worker_sources() or digest(request['request_sha256'])!=
            sha(encoded({k:v for k,v in request.items() if k!='request_sha256'}))):
        raise JournalError('audit request source or checksum binding')
    validate_inputs(request['operation'],request['inputs'])
    proposal=ReplayProposal(request['base_document'])
    if request['operation']=='advance':proposal.advance(**request['inputs'])
    else:proposal.finalize(**{k:restore_cursor(v) for k,v in request['inputs'].items()})
    rss=integer(peak_rss(),1)
    if rss>request['rss_limit_bytes']:raise MemoryError('audit worker RSS limit')
    reply=dict(version=1,job_id=request['job_id'],request_sha256=request['request_sha256'],
        base_receipt={k:request['base_document'][k] for k in ('revision','checkpoint_sha256')},
        proposed_document=proposal._doc,peak_rss_bytes=rss)
    raw=encoded(reply)
    if len(raw)>MAX_REPLY:raise JournalError('audit reply byte bound')
    return raw


def validate_reply(raw,request,owner):
    if len(raw)>MAX_REPLY:raise JournalError('audit reply byte bound')
    reply=decoded(raw)
    keys(reply,'version job_id request_sha256 base_receipt proposed_document peak_rss_bytes')
    base=request['base_document'];old=base['state'];doc=reply['proposed_document']
    receipt={k:base[k] for k in ('revision','checkpoint_sha256')}
    if (type(reply['version']) is not int or reply['version']!=1 or integer(reply['job_id'])!=request['job_id'] or
            reply['request_sha256']!=request['request_sha256'] or reply['base_receipt']!=receipt or owner.receipt()!=receipt):
        raise JournalError('audit reply request or stale base binding')
    if not 0<integer(reply['peak_rss_bytes'],1)<=request['rss_limit_bytes']:raise JournalError('audit reply RSS limit')
    check_document(doc)
    if (doc['contract']!=base['contract'] or doc['revision']!=base['revision']+1 or
            doc['previous_checkpoint_sha256']!=base['checkpoint_sha256']):
        raise JournalError('audit proposed checkpoint successor differs')
    processor,reducer=owner._validate_state(doc['state']);before,_=owner._validate_state(old)
    state=doc['state'];inputs=request['inputs']
    if request['operation']=='finalize':
        if state!=(old|dict(finalized=True)):raise JournalError('finalize changed replay state')
        if (state['raw_position']!=dict(cursor=inputs['raw_cursor'],ref=None,consumed=0) or
                state['audit_cursor']!=inputs['audit_cursor'] or not processor.closed or processor.sequence==0):
            raise JournalError('audit final source anchors differ')
    else:
        audit_row=certificate(inputs['audit_ref']['certificate'].encode())
        expected=advance_cursor(audit_row,restore_cursor(old['audit_cursor']))
        if state['audit_cursor']!=cursor_dict(expected) or state['finalized'] or old['finalized']:
            raise JournalError('audit result cursor differs from submitted ticket')
        if (processor.sequence<=before.sequence or processor.processed_ns<before.processed_ns or
                state['valid_audit_bytes']<=old['valid_audit_bytes'] or state['previous_published']<old['previous_published'] or
                (before.epoch is not None and processor.epoch!=before.epoch) or
                any(processor.counts[k]<v for k,v in before.counts.items()) or
                not before.used_sessions.issubset(processor.used_sessions) or
                not before.ended_sessions.issubset(processor.ended_sessions)):
            raise JournalError('audit state progress regressed')
        raw_before=restore_cursor(old['raw_position']['cursor'])
        refs=([old['raw_position']['ref']] if old['raw_position']['ref'] is not None else [])+inputs['raw_refs']
        if not refs:raise JournalError('audit proposed progress without raw input')
        for ref in refs:
            prior=raw_before
            raw_before=advance_cursor(certificate(ref['certificate'].encode()),raw_before)
        position=state['raw_position']
        if position['ref'] is None:
            if position!=dict(cursor=cursor_dict(raw_before),ref=None,consumed=0):
                raise JournalError('audit raw terminal cursor differs from submitted inputs')
        elif position['ref']!=refs[-1] or position['cursor']!=cursor_dict(prior):
            raise JournalError('audit partial raw source differs from submitted inputs')
        if reducer.first is not None and old['valid_batches'] and reducer.first!=owner._validate_state(old)[1].first:
            raise JournalError('audit first observation changed')
    # Finish can expose exclusion-fragmentation overflow without replaying raw.
    reducer.finish()
    return doc,reply['peak_rss_bytes']
