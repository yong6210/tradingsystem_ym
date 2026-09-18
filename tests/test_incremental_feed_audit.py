from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.research.data.archive_segment_reader import SegmentReader,segment_ref,restore_cursor
from app.research.data.durable_capture_log import JournalError,decoded,encoded,file_hash
from app.research.data.feed_audit_state_codec import pack,unpack,convert
from app.research.data.incremental_feed_audit import IncrementalFeedAudit
from app.research.data.reserved_feed_storage import ReservedStorageBudget
from app.research.data.sealed_segment_handoff import read_segment
from tests import incremental_audit_fixture as fixtures


class IncrementalAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name).resolve()
        self.fix=fixtures.fixture(self.base);self.budget=self.fix['budget'];self.root=self.fix['root']
        self.audit=IncrementalFeedAudit.create(self.root/'state',budget=self.budget,contract=self.fix['contract'])

    def tearDown(self):self.audit.close();self.budget.close();self.temp.cleanup()

    def reopen(self,anchor=None):
        anchor=anchor or self.audit.receipt();self.audit.close()
        self.audit=IncrementalFeedAudit.resume(self.root/'state',budget=self.budget,contract=self.fix['contract'],
            anchor=anchor)
        return self.audit

    def recover_failed(self,anchor):
        contract={k:v for k,v in self.budget.contract.items() if k!='version'};self.audit.close();self.budget.close()
        self.budget=ReservedStorageBudget.resume(self.root,**contract);self.fix['budget']=self.budget
        return self.reopen(anchor)

    def run_all(self,compressed=False,restart=False):
        for a,r in fixtures.jobs(self.fix,compressed=compressed):
            self.audit.advance(a,r)
            if restart:self.reopen()
        result=self.audit.finalize(raw_cursor=self.fix['raw_cursor'],audit_cursor=self.fix['audit_cursor'])
        for k in fixtures.COMPARABLE:self.assertEqual(result[k],self.fix['expected'][k],k)
        return result

    def test_raw_cross_segment_replay_equals_full_replay(self):self.run_all()
    def test_gzip_cross_segment_replay_equals_full_replay(self):self.run_all(compressed=True)
    def test_resume_every_audit_segment_preserves_all_semantics(self):self.run_all(restart=True)
    def test_gzip_resume_every_segment_preserves_all_semantics(self):self.run_all(compressed=True,restart=True)

    def test_cursor_inside_raw_segment_is_persisted_with_processor(self):
        a,r=fixtures.jobs(self.fix)[0];self.audit.advance(a,r)
        state=decoded(self.audit.path.read_bytes())['state'];p=state['raw_position']
        self.assertIsNotNone(p['ref']);self.assertGreater(p['consumed'],0)
        processor,_=unpack(state['replay'])
        self.assertEqual(processor.sequence,p['cursor']['sequence']+p['consumed'])
        self.reopen();self.assertEqual(self.audit.summary()['last_audited_sequence'],processor.sequence)

    def test_restart_reads_current_raw_segment_but_not_completed_history(self):
        work=fixtures.jobs(self.fix);self.audit.advance(*work[0]);self.reopen()
        state=decoded(self.audit.path.read_bytes())['state'];completed_index=state['raw_position']['cursor']['index']
        original=Path.open
        def guarded(path,*args,**kwargs):
            if path.parent==self.root/'raw' and path.name.startswith('segment-'):
                self.assertGreater(int(path.name[8:15]),completed_index)
            return original(path,*args,**kwargs)
        with patch.object(Path,'open',guarded):self.audit.advance(*work[1])

    def test_gzip_can_replay_without_raw_segment_files(self):
        work=fixtures.jobs(self.fix,compressed=True)
        for directory in ('raw','audit'):
            for path in (self.root/directory).glob('segment-*.jsonl'):path.rename(path.with_suffix('.retained'))
        for a,r in work:self.audit.advance(a,r);self.reopen()
        result=self.audit.finalize(raw_cursor=self.fix['raw_cursor'],audit_cursor=self.fix['audit_cursor'])
        self.assertEqual(result['intervals'],self.fix['expected']['intervals'])

    def test_missing_selected_gzip_does_not_fall_back_to_raw(self):
        work=fixtures.jobs(self.fix,compressed=True);ref=work[0][0]
        descriptor=decoded((self.root/'audit-archives'/(ref['archive']['archive_id']+'.json')).read_bytes())
        (self.root/'audit-archives'/descriptor['compressed_name']).unlink()
        before=self.audit.path.read_bytes()
        with self.assertRaises(FileNotFoundError):self.audit.advance(*work[0])
        self.assertEqual(self.audit.path.read_bytes(),before);self.assertTrue(self.budget.failed)

    def test_corrupt_selected_archive_rejected_before_state_commit(self):
        work=fixtures.jobs(self.fix,compressed=True);ref=work[0][0]
        descriptor=decoded((self.root/'audit-archives'/(ref['archive']['archive_id']+'.json')).read_bytes())
        path=self.root/'audit-archives'/descriptor['compressed_name'];raw=bytearray(path.read_bytes());raw[-1]^=1;path.write_bytes(raw)
        before=self.audit.path.read_bytes()
        with self.assertRaises(JournalError):self.audit.advance(*work[0])
        self.assertEqual(self.audit.path.read_bytes(),before)

    def test_wrong_archive_binding_is_rejected(self):
        work=fixtures.jobs(self.fix,compressed=True);a,r=work[0]
        bad=dict(a,archive=work[1][0]['archive'])
        with self.assertRaises(JournalError):self.audit.advance(bad,r)

    def test_duplicate_or_skipped_audit_segment_cannot_advance(self):
        work=fixtures.jobs(self.fix)
        with self.assertRaises(JournalError):self.audit.advance(*work[1])
        self.assertEqual(decoded(self.audit.path.read_bytes())['revision'],0)

    def test_duplicate_after_resume_rejected(self):
        work=fixtures.jobs(self.fix);self.audit.advance(*work[0]);self.reopen()
        before=self.audit.path.read_bytes()
        with self.assertRaises(JournalError):self.audit.advance(*work[0])
        self.assertEqual(self.audit.path.read_bytes(),before)

    def test_missing_raw_segment_preserves_checkpoint(self):
        work=fixtures.jobs(self.fix);before=self.audit.path.read_bytes()
        with self.assertRaisesRegex(JournalError,'missing raw'):self.audit.advance(work[0][0],[])
        self.assertEqual(self.audit.path.read_bytes(),before)

    def test_extra_unconsumed_raw_segment_is_not_silently_accepted(self):
        a,r=fixtures.jobs(self.fix)[0];r=r+[segment_ref(self.fix['raw_tickets'][-1])]
        with self.assertRaisesRegex(JournalError,'unused'):self.audit.advance(a,r)

    def test_finalization_requires_full_source_anchors_and_stop(self):
        self.audit.advance(*fixtures.jobs(self.fix)[0])
        with self.assertRaisesRegex(JournalError,'anchors'):self.audit.finalize(raw_cursor=self.fix['raw_cursor'],audit_cursor=self.fix['audit_cursor'])

    def test_wrong_final_anchor_is_rejected(self):
        for a,r in fixtures.jobs(self.fix):self.audit.advance(a,r)
        with self.assertRaises(JournalError):self.audit.finalize(raw_cursor=replace(self.fix['raw_cursor'],record_sha256='1'*64),audit_cursor=self.fix['audit_cursor'])

    def test_final_state_cannot_accept_new_input(self):
        self.run_all();self.reopen()
        with self.assertRaisesRegex(JournalError,'final audit'):self.audit.advance(*fixtures.jobs(self.fix)[0])

    def test_tampered_checkpoint_is_rejected(self):
        anchor=self.audit.receipt();row=decoded(self.audit.path.read_bytes());row['state']['valid_batches']=10
        self.audit.path.write_bytes(encoded(row))
        with self.assertRaisesRegex(JournalError,'checksum'):self.reopen(anchor)

    def test_rollback_to_older_checkpoint_rejected(self):
        old=self.audit.path.read_bytes();self.audit.advance(*fixtures.jobs(self.fix)[0]);anchor=self.audit.receipt()
        self.audit.path.write_bytes(old)
        with self.assertRaisesRegex(JournalError,'rollback'):self.reopen(anchor)

    def test_corrupt_raw_keeps_prior_state(self):
        a,r=fixtures.jobs(self.fix)[0];row=decoded(r[0]['certificate']);path=self.root/'raw'/row['segment']['name']
        data=bytearray(path.read_bytes());data[-2]^=1;path.write_bytes(data)
        before=self.audit.path.read_bytes()
        with self.assertRaises(JournalError):self.audit.advance(a,r)
        self.assertEqual(self.audit.path.read_bytes(),before)

    def test_fail_after_checkpoint_temp_fsync_keeps_old_revision(self):
        work=fixtures.jobs(self.fix);anchor=self.audit.receipt()
        def fail(stage):
            if stage=='after_audit_checkpoint_fsync':raise OSError('fsync fault')
        self.audit.hook=fail
        with self.assertRaises(OSError):self.audit.advance(*work[0])
        self.assertTrue(self.budget.failed)
        self.recover_failed(anchor);self.assertEqual(self.audit.receipt(),anchor)
        self.audit.advance(*work[0])

    def test_renamed_unacknowledged_checkpoint_reanchors_successor(self):
        work=fixtures.jobs(self.fix);anchor=self.audit.receipt()
        def fail(stage):
            if stage=='after_audit_checkpoint_replace':raise OSError('directory fence fault')
        self.audit.hook=fail
        with self.assertRaises(OSError):self.audit.advance(*work[0])
        self.recover_failed(anchor);self.assertEqual(self.audit.receipt()['revision'],anchor['revision']+1)
        self.audit.advance(*work[1])

    def test_recovery_requires_new_directory_fsync(self):
        with patch('app.research.data.incremental_feed_audit.sync_directory',side_effect=OSError('fence')):
            with self.assertRaises(OSError):self.reopen()
        self.assertTrue(self.budget.failed)

    def test_checkpoint_replacement_counts_old_and_new_bytes(self):
        work=fixtures.jobs(self.fix);before=self.audit.path.read_bytes()
        self.budget.contract['max_bytes']=self.budget.used+1
        with self.assertRaises(JournalError):self.audit.advance(*work[0])
        self.assertEqual(self.audit.path.read_bytes(),before)

    def test_common_raw_reader_matches_frozen_reader(self):
        ticket=self.fix['raw_tickets'][0];cursor=restore_cursor(self.fix['contract']['raw_initial'])
        original=read_segment(ticket,cursor);common=SegmentReader(budget=self.budget).read(segment_ref(ticket),cursor)
        self.assertEqual(original,common)

    def test_state_codec_preserves_decimal_tuple_set_and_counter(self):
        self.audit.advance(*fixtures.jobs(self.fix)[0]);payload=decoded(self.audit.path.read_bytes())['state']['replay']
        processor,reducer=unpack(payload);self.assertEqual(pack(processor,reducer),payload)
        self.assertEqual(processor.book.quote(now_ns=processor.processed_ns)['bid'],'100')

    def test_state_codec_rejects_unknown_type_and_depth(self):
        with self.assertRaises(JournalError):convert(dict(t='pickle',v=[]),restore=True)
        data=[]
        for _ in range(40):data=[data]
        with self.assertRaises(JournalError):convert(data)

    def test_scope_implementation_binding_cannot_be_changed(self):
        contract=dict(self.fix['contract'],clock_domain='another-clock')
        with self.assertRaises(JournalError):IncrementalFeedAudit.resume(self.root/'state',budget=self.budget,contract=contract,anchor=self.audit.receipt())


    def test_second_audit_owner_cannot_open_same_checkpoint(self):
        with self.assertRaisesRegex(JournalError,'busy'):
            IncrementalFeedAudit.resume(self.root/'state',budget=self.budget,contract=self.fix['contract'],anchor=self.audit.receipt())
        self.audit.advance(*fixtures.jobs(self.fix)[0])

    def test_caller_cannot_mutate_committed_partial_segment_reference(self):
        a,r=fixtures.jobs(self.fix)[0];self.audit.advance(a,r)
        before=self.audit.summary();r[-1]['certificate']='broken'
        self.assertEqual(self.audit.summary(),before)
        self.reopen();self.assertEqual(self.audit.summary(),before)

    def test_raw_input_count_is_bounded_before_replay(self):
        a,r=fixtures.jobs(self.fix)[0];before=self.audit.path.read_bytes()
        with self.assertRaisesRegex(JournalError,'batch bound'):self.audit.advance(a,r*20)
        self.assertEqual(self.audit.path.read_bytes(),before)

    def test_checkpoint_size_bound_keeps_prior_receipt(self):
        work=fixtures.jobs(self.fix);before=self.audit.path.read_bytes()
        with patch('app.research.data.incremental_feed_audit.MAX_CHECKPOINT_BYTES',100):
            with self.assertRaisesRegex(JournalError,'byte bound'):self.audit.advance(*work[0])
        self.assertEqual(self.audit.path.read_bytes(),before)

    def test_audit_batch_limit_is_fail_closed(self):
        work=fixtures.jobs(self.fix);before=self.audit.path.read_bytes()
        with patch('app.research.data.incremental_feed_audit.MAX_BATCHES',1):
            with self.assertRaisesRegex(JournalError,'operation bound'):self.audit.advance(*work[0])
        self.assertEqual(self.audit.path.read_bytes(),before)


    def test_changed_feed_dependency_refuses_saved_contract(self):
        from app.research.data import incremental_feed_audit as module
        original=module.file_hash
        def changed(path):
            return '1'*64 if path.name=='forward_data_contract.py' else original(path)
        with patch.object(module,'file_hash',changed):
            with self.assertRaisesRegex(JournalError,'implementation binding'):
                IncrementalFeedAudit.resume(self.root/'state',budget=self.budget,contract=self.fix['contract'],anchor=self.audit.receipt())


class BufferedStateTests(unittest.TestCase):
    def test_pre_snapshot_buffer_and_all_lifecycle_states_survive_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            fix=fixtures.fixture(Path(tmp).resolve(),buffered=True,raw_step=3,audit_step=1)
            budget=fix['budget'];seen=set()
            try:
                state=IncrementalFeedAudit.create(fix['root']/'state',budget=budget,contract=fix['contract'])
                for a,r in fixtures.jobs(fix,compressed=True):
                    state.advance(a,r)
                    processor,_=unpack(decoded(state.path.read_bytes())['state']['replay']);seen.add(processor.book.state)
                    anchor=state.receipt();state.close()
                    state=IncrementalFeedAudit.resume(fix['root']/'state',budget=budget,contract=fix['contract'],anchor=anchor)
                result=state.finalize(raw_cursor=fix['raw_cursor'],audit_cursor=fix['audit_cursor'])
                self.assertTrue({'EMPTY','BUFFERING','LIVE','INVALID'}.issubset(seen))
                for k in fixtures.COMPARABLE:self.assertEqual(result[k],fix['expected'][k],k)
            finally:
                state.close();budget.close()


class InvalidObservationTests(unittest.TestCase):
    def test_validly_sealed_wrong_observation_cannot_advance_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            def mutate(index,batch):
                return batch|dict(observation=batch['observation']|dict(eligible=not batch['observation']['eligible'])) if index==1 else batch
            fix=fixtures.fixture(Path(tmp).resolve(),audit_mutation=mutate)
            state=None
            try:
                state=IncrementalFeedAudit.create(fix['root']/'state',budget=fix['budget'],contract=fix['contract'])
                before=state.path.read_bytes()
                with self.assertRaisesRegex(JournalError,'observation differs'):state.advance(*fixtures.jobs(fix)[0])
                self.assertEqual(state.path.read_bytes(),before)
            finally:
                if state is not None:state.close()
                fix['budget'].close()
