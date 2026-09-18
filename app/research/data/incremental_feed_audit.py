"""Offline transactional replay across sealed raw/gzip segments.

A checkpoint binds replay state and both input positions. This is never live
market restoration. A caller receipt anchors recovery against stale rollback;
there is no claim of exactly-once external effects or automatic worker resume.
"""
import hashlib
import os
from pathlib import Path

from .archive_segment_reader import SegmentReader, cursor_dict, restore_cursor
from .compact_feed_intervals import CompactIntervals
from .durable_capture_log import JournalError, ZERO, decoded, digest, encoded, file_hash, integer, keys, lock_directory, sync_directory
from .durable_market_feed import MarketFeedProcessor
from .feed_audit_state_codec import pack, unpack
from .sealed_segment_handoff import certificate, sha

MAX_CHECKPOINT_BYTES=8*1024**2
MAX_RAW_SEGMENTS=16
MAX_RAW_RECORDS=50000
MAX_BATCHES=10000
IMPLEMENTATIONS=('incremental_feed_audit.py','archive_segment_reader.py','feed_audit_state_codec.py',
                 'durable_market_feed.py','local_order_book.py','compact_feed_intervals.py',
                 'sealed_segment_handoff.py','segment_archive.py','background_segment_archive.py',
                 'durable_capture_log.py','shared_feed_storage.py','reserved_feed_storage.py',
                 'depth_capture.py','../foundation/forward_data_contract.py')


def implementation_hashes():
    base=Path(__file__).parent
    return {name:file_hash(base/name) for name in IMPLEMENTATIONS}


def make_contract(raw_cursor,audit_cursor,*,window_start_ns,window_end_ns,clock_domain,max_intervals=10000):
    integer(window_start_ns);integer(window_end_ns,window_start_ns+1);integer(max_intervals,1)
    if max_intervals>10000 or type(clock_domain) is not str or not clock_domain or len(clock_domain)>256:
        raise JournalError('audit scope bounds')
    for cursor in (raw_cursor,audit_cursor):
        if cursor.sequence!=0 or cursor.index!=-1 or any(getattr(cursor,k)!=ZERO for k in ('record_sha256','segment_sha256','seal_sha256')):
            raise JournalError('initial audit cursor required')
    if raw_cursor.root!=audit_cursor.root or raw_cursor.run_id!=audit_cursor.run_id or raw_cursor.journal==audit_cursor.journal:
        raise JournalError('raw/audit source identities differ')
    return dict(version=1,raw_initial=cursor_dict(raw_cursor),audit_initial=cursor_dict(audit_cursor),
        window_start_ns=window_start_ns,window_end_ns=window_end_ns,clock_domain=clock_domain,
        max_intervals=max_intervals,implementations=implementation_hashes())


class RawRows:
    def __init__(self,reader,position,refs):
        if type(refs) is not list or len(refs)>MAX_RAW_SEGMENTS:raise JournalError('raw segment batch bound')
        keys(position,'cursor ref consumed')
        self.reader,self.position,self.refs=reader,position,refs
        self.index=self.count=0
        self.rows=self.after=None

    def next(self):
        if self.count>=MAX_RAW_RECORDS:raise JournalError('raw record operation bound')
        if self.rows is None:
            if self.position['ref'] is None:
                if self.index>=len(self.refs):raise JournalError('missing raw segment for audit batch')
                self.position['ref']=self.refs[self.index];self.index+=1
            result=self.reader.read(self.position['ref'],restore_cursor(self.position['cursor']))
            self.rows=iter(result.records());self.after=result.cursor
            skipped=integer(self.position['consumed'])
            for _ in range(skipped):
                if next(self.rows,None) is None:raise JournalError('raw saved offset exceeds segment')
        row=next(self.rows,None)
        if row is None:raise JournalError('raw saved offset points past segment')
        self.count+=1;self.position['consumed']+=1
        if row['sequence']==self.after.sequence:
            self.position.update(cursor=cursor_dict(self.after),ref=None,consumed=0)
            self.rows=self.after=None
        return row


class IncrementalFeedAudit:
    @classmethod
    def create(cls,directory,*,budget,contract,hook=lambda stage:None):
        obj=cls(directory,budget,contract,hook)
        try:
            with budget.mutation():
                obj.directory.mkdir()
                obj.lock=lock_directory(obj.directory)
                sync_directory(obj.directory.parent)
                processor=MarketFeedProcessor()
                reducer=CompactIntervals(contract['window_start_ns'],contract['window_end_ns'],max_intervals=contract['max_intervals'])
                state=dict(replay=pack(processor,reducer),raw_position=dict(cursor=contract['raw_initial'],ref=None,consumed=0),
                    audit_cursor=contract['audit_initial'],valid_batches=0,valid_audit_bytes=0,
                    previous_published=-1,audit_payload_chain_sha256=ZERO,finalized=False)
                obj._write(state,revision=0,previous=ZERO)
        except BaseException:
            obj.close()
            raise
        return obj

    def __init__(self,directory,budget,contract,hook):
        self.budget,self.contract,self.hook=budget,decoded(encoded(contract)),hook
        expected=make_contract(restore_cursor(contract['raw_initial']),restore_cursor(contract['audit_initial']),
            **{k:contract[k] for k in ('window_start_ns','window_end_ns','clock_domain','max_intervals')})
        if contract!=expected:raise JournalError('audit contract or implementation binding differs')
        if Path(contract['raw_initial']['root'])!=budget.root or contract['raw_initial']['run_id']!=budget.contract['run_id']:
            raise JournalError('audit budget identity differs')
        self.directory=budget.path(directory)
        if self.directory==budget.root:raise JournalError('dedicated audit state directory required')
        self.path=self.directory/'checkpoint.json'
        self.reader=SegmentReader(budget=budget)
        self._doc=None;self.failed=False;self.closed=False
        self.lock=lock_directory(self.directory) if self.directory.is_dir() else None

    def _write(self,state,*,revision,previous):
        body=dict(version=1,contract=self.contract,revision=revision,previous_checkpoint_sha256=previous,state=state)
        row=body|dict(checkpoint_sha256=sha(encoded(body)))
        if len(encoded(row))>MAX_CHECKPOINT_BYTES:raise JournalError('audit checkpoint byte bound')
        stages={'after_checkpoint_fsync':'after_audit_checkpoint_fsync',
                'after_checkpoint_replace':'after_audit_checkpoint_replace',
                'after_directory_fsync':'after_audit_checkpoint_directory_fsync'}
        self.budget.atomic_json(self.path,row,lambda stage:self.hook(stages[stage]))
        self._doc=decoded(encoded(row))

    def receipt(self):
        if self.failed or self.closed:raise JournalError('audit state failed or closed; offline recovery required')
        return dict(revision=self._doc['revision'],checkpoint_sha256=self._doc['checkpoint_sha256'])

    @classmethod
    def resume(cls,directory,*,budget,contract,anchor,hook=lambda stage:None):
        obj=cls(directory,budget,contract,hook)
        try:
            obj._recover(anchor)
            return obj
        except BaseException:
            obj.close()
            raise

    def _recover(self,anchor):
        with self.budget.mutation():
            keys(anchor,'revision checkpoint_sha256');integer(anchor['revision']);digest(anchor['checkpoint_sha256'])
            if not self.path.is_file() or self.path.stat().st_size>MAX_CHECKPOINT_BYTES:raise JournalError('audit checkpoint missing or oversized')
            row=decoded(self.path.read_bytes())
            keys(row,'version contract revision previous_checkpoint_sha256 state checkpoint_sha256')
            if (type(row['version']) is not int or row['version']!=1 or row['contract']!=self.contract or
                    digest(row['checkpoint_sha256'])!=sha(encoded({k:v for k,v in row.items() if k!='checkpoint_sha256'}))):
                raise JournalError('audit checkpoint contract or checksum differs')
            revision=integer(row['revision']);digest(row['previous_checkpoint_sha256'])
            if not ((revision==anchor['revision'] and row['checkpoint_sha256']==anchor['checkpoint_sha256']) or
                    (revision==anchor['revision']+1 and row['previous_checkpoint_sha256']==anchor['checkpoint_sha256'])):
                raise JournalError('audit checkpoint rollback or unrelated successor')
            self._validate_state(row['state'])
            with self.path.open('rb') as stream:os.fsync(stream.fileno())
            sync_directory(self.directory)
            self._doc=row


    def _validate_state(self,state):
        keys(state,'replay raw_position audit_cursor valid_batches valid_audit_bytes previous_published audit_payload_chain_sha256 finalized')
        processor,reducer=unpack(state['replay'])
        if (reducer.start!=self.contract['window_start_ns'] or reducer.end!=self.contract['window_end_ns'] or
                reducer.limit!=self.contract['max_intervals']):raise JournalError('reducer scope differs')
        integer(state['valid_batches']);integer(state['valid_audit_bytes']);digest(state['audit_payload_chain_sha256'])
        if type(state['previous_published']) is not int or state['previous_published'] < -1 or type(state['finalized']) is not bool:
            raise JournalError('audit state publication/finalization fields')
        keys(state['raw_position'],'cursor ref consumed')
        raw=restore_cursor(state['raw_position']['cursor']);audit=restore_cursor(state['audit_cursor'])
        for cursor,key in ((raw,'raw_initial'),(audit,'audit_initial')):
            initial=restore_cursor(self.contract[key])
            for field in ('root','journal','run_id','metadata_sha256'):
                if getattr(cursor,field)!=getattr(initial,field):raise JournalError('saved cursor identity differs')
        consumed=integer(state['raw_position']['consumed'])
        if raw.sequence+consumed!=processor.sequence or state['valid_batches']!=audit.sequence or reducer.points!=audit.sequence:
            raise JournalError('saved state and input cursors differ')
        if state['raw_position']['ref'] is None:
            if consumed:raise JournalError('saved offset without segment')
        else:
            ref=state['raw_position']['ref'];keys(ref,'certificate archive')
            row=certificate(ref['certificate'].encode())
            from .background_segment_archive import advance_cursor
            after=advance_cursor(row,raw)
            if not 0<consumed<after.sequence-raw.sequence:raise JournalError('saved raw offset range')
        if processor.sequence and processor.deadline_ns!=self.contract['window_end_ns']:
            raise JournalError('saved processor window differs')
        if reducer.previous is None:
            if state['previous_published']!=-1 or state['valid_batches']!=0:raise JournalError('missing previous observation')
        elif reducer.previous[0]!=state['previous_published']:raise JournalError('saved publication differs')
        if state['finalized'] and (not processor.closed or state['raw_position']['ref'] is not None):
            raise JournalError('finalized state has incomplete inputs')
        return processor,reducer

    def advance(self,audit_ref,raw_refs):
        if self.failed or self.closed:raise JournalError('audit failed or closed')
        with self.budget.mutation():
            try:
                state=decoded(encoded(self._doc['state']))
                if state['finalized']:raise JournalError('final audit cannot accept more input')
                processor,reducer=self._validate_state(state)
                self.reader.reads=[]
                audit=self.reader.read(audit_ref,restore_cursor(state['audit_cursor']))
                raw=RawRows(self.reader,state['raw_position'],raw_refs)
                batches=0
                for record in audit.records():
                    batches+=1
                    if batches>MAX_BATCHES:raise JournalError('audit batch operation bound')
                    batch=record['payload'];line=encoded(batch)
                    if len(line)>4*1024**2:raise JournalError('audit payload bound')
                    keys(batch,'first_sequence last_sequence record_sha256 committed_ns observation')
                    begin=integer(batch['first_sequence'],1);last=integer(batch['last_sequence'],begin)
                    committed=integer(batch['committed_ns']);published=integer(batch['observation']['published_ns'])
                    if begin!=processor.sequence+1 or committed<state['previous_published'] or published<committed:
                        raise JournalError('audit prefix sequence or clock differs')
                    if last-begin+1>MAX_RAW_RECORDS-raw.count:raise JournalError('raw batch operation bound')
                    exclusions=[]
                    for sequence in range(begin,last+1):
                        item=raw.next();payload=item['payload']
                        if processor.sequence==0:
                            if (payload['kind']!='RUN_WINDOW' or payload['started_ns']!=self.contract['window_start_ns'] or
                                    payload['deadline_ns']!=self.contract['window_end_ns']):raise JournalError('original run window differs')
                        if (item['sequence']!=sequence or payload['process_epoch']!=item['epoch'] or
                                (processor.epoch is not None and item['epoch']!=processor.epoch)):
                            raise JournalError('raw process epoch or sequence differs')
                        errors_before=len(processor.errors)
                        processor.apply(sequence,payload,processed_ns=committed)
                        if payload['kind'] in ('OPEN','END','FAULT','STOP') or len(processor.errors)>errors_before:
                            exclusions.append([payload['received_ns'],published])
                    if item['sha256']!=batch['record_sha256']:raise JournalError('audit fence hash differs')
                    observation=processor.observe(now_ns=published,committed_ns=committed,committed_sequence=last)
                    if observation!=batch['observation']:raise JournalError('observation differs from raw replay')
                    expiries={}
                    if not processor.errors and not processor.closed and observation['within_window']:
                        age=dict(l2=min(processor.depth_received_ns+1_000_000_000,processor.book.available_ns+1_000_000_000)
                            if observation['gates']['l2'] else None,
                            market_connection=processor.market_received_ns+3_000_000_000 if observation['gates']['market_connection'] else None,
                            mark=processor.mark_received_ns+3_000_000_000 if observation['gates']['mark'] else None,
                            clock=processor.watchdog_ns+500_000_000 if observation['gates']['clock'] else None,
                            durable_log=self.contract['window_end_ns'])
                        expiries={k:v for k,v in age.items() if v is not None}
                    reducer.add(published,expiries,exclusions)
                    state['valid_batches']+=1;state['valid_audit_bytes']+=len(line)
                    state['previous_published']=published
                    state['audit_payload_chain_sha256']=sha(bytes.fromhex(state['audit_payload_chain_sha256'])+line)
                if raw.index!=len(raw.refs):raise JournalError('unused submitted raw segments')
                state['audit_cursor']=cursor_dict(audit.cursor);state['replay']=pack(processor,reducer)
                self._validate_state(state)
                self.hook('after_incremental_replay')
                self._write(state,revision=self._doc['revision']+1,previous=self._doc['checkpoint_sha256'])
                return self.receipt()
            except BaseException:
                self.failed=True
                raise

    def finalize(self,*,raw_cursor,audit_cursor):
        if self.failed or self.closed:raise JournalError('audit failed or closed')
        with self.budget.mutation():
            try:
                state=decoded(encoded(self._doc['state']));processor,reducer=self._validate_state(state)
                if (state['raw_position']!=dict(cursor=cursor_dict(raw_cursor),ref=None,consumed=0) or
                        state['audit_cursor']!=cursor_dict(audit_cursor) or not processor.closed or processor.sequence==0):
                    raise JournalError('final source anchors or clean stop missing')
                reducer.finish()  # Detect final exclusion fragmentation before persistence.
                state['finalized']=True
                self._write(state,revision=self._doc['revision']+1,previous=self._doc['checkpoint_sha256'])
                return self.summary()
            except BaseException:
                self.failed=True
                raise

    def summary(self):
        self.receipt()
        state=self._doc['state'];processor,reducer=self._validate_state(state)
        intervals,exclusions=reducer.finish()
        return dict(status='AUDIT_PREFIX_COMPLETE' if state['finalized'] else 'AUDITED_PREFIX_AWAITING_MORE',
            **{k:self.contract[k] for k in ('window_start_ns','window_end_ns','clock_domain')},
            epoch=processor.epoch,intervals=intervals,exclusions=exclusions,valid_batches=state['valid_batches'],
            valid_audit_bytes=state['valid_audit_bytes'],last_audited_sequence=processor.sequence,
            first_audited_publication_ns=reducer.first,
            last_audited_publication_ns=state['previous_published'] if reducer.points else None,
            errors=[],processor_errors=list(processor.errors),clean_stop_audited=processor.closed,
            continuous_runtime_coverage_certified=False,live_market_state_restored=False,
            interval_reduction=dict(points=reducer.points,peak_merged_intervals=reducer.peak,max_intervals=reducer.limit,failed=reducer.failed),
            audit_payload_chain_sha256=state['audit_payload_chain_sha256'],audit_hash_scope='CHAIN_OF_CANONICAL_PAYLOAD_LINES',
            receipt=self.receipt())

    def close(self):
        if not self.closed:
            if self.lock is not None:self.lock.close()
            self.closed=True
