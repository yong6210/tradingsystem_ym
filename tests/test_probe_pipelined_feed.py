import asyncio
import copy
import json
from pathlib import Path
import tempfile
import unittest

from app.research.data.pipelined_feed_collector import run_bounded
from app.research.foundation.forward_data_contract import load_contract
from scripts.probe_pipelined_feed import result_checks, verify_capture, run_probe
from tests.test_bounded_feed_collector import ScriptedTransport, ROOT


class CaptureVerificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.capture = Path(cls.temp.name).resolve()/'capture'
        cls.result = asyncio.run(run_bounded(cls.capture, duration_ns=300_000_000,
            transport=ScriptedTransport(), policy=load_contract(ROOT/'configs/research/forward_data_policy_v1.json')))
        assert cls.result['stop_reason'] == 'ORIGINAL_DEADLINE', cls.result['errors']

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def checks(self, result, *, reconnect=False, duration_ns=300_000_000):
        return result_checks(result, duration_ns=duration_ns, reconnect=reconnect)

    def test_real_offline_capture_passes_all_independent_checks(self):
        self.assertTrue(all(self.checks(self.result).values()))
        report = verify_capture(self.capture, self.result)
        self.assertTrue(all(report['checks'].values()))
        self.assertEqual(len(report['comparisons'][0]['fields']), 17)
        self.assertGreater(len(report['registrations']), 0)

    def test_missing_result_never_passes_vacuously(self):
        self.assertFalse(all(self.checks(None).values()))

    def test_json_reloaded_capture_has_same_semantic_verdict(self):
        reloaded = json.loads(json.dumps(self.result))
        report = verify_capture(self.capture, reloaded)
        self.assertTrue(all(report['checks'].values()))

    def test_canonical_comparison_still_rejects_changed_exclusion_values(self):
        path = self.capture/'collection_result.json'
        original = path.read_bytes()
        reloaded = json.loads(json.dumps(self.result))
        self.assertTrue(reloaded['audits'][0]['exclusions'])
        reloaded['audits'][0]['exclusions'][0][0] += 1
        stored = json.loads(original)
        stored['audits'] = reloaded['audits']
        try:
            path.write_text(json.dumps(stored))
            report = verify_capture(self.capture, reloaded)
            self.assertFalse(report['comparisons'][0]['fields']['exclusions'])
            self.assertFalse(report['checks']['full_replay_equal'])
        finally:
            path.write_bytes(original)

    def test_requested_reconnect_is_not_waived_after_healthy_single_epoch(self):
        checks = self.checks(self.result, reconnect=True)
        self.assertFalse(checks['expected_epochs'])
        self.assertFalse(checks['requested_reconnect'])

    def test_changed_calendar_rejected(self):
        self.assertFalse(self.checks(self.result, duration_ns=5_000_000_000)['original_calendar'])

    def test_incomplete_audit_set_rejected(self):
        result = copy.deepcopy(self.result)
        result['audits'] = []
        self.assertFalse(self.checks(result)['epoch_audit_set'])
        self.assertFalse(self.checks(result)['clean_final_audits'])

    def test_unreaped_worker_rejected(self):
        result = copy.deepcopy(self.result)
        result['pipeline']['channels'][0]['raw']['child_reaped'] = False
        self.assertFalse(self.checks(result)['workers_complete'])

    def test_unfinished_unit_rejected(self):
        result = copy.deepcopy(self.result)
        result['pipeline']['units'][0]['status'] = 'WAIT_ARCHIVE'
        self.assertFalse(self.checks(result)['units_complete'])

    def test_leaked_reservation_rejected(self):
        result = copy.deepcopy(self.result)
        result['storage_after_result']['reserved_bytes'] = 1
        self.assertFalse(self.checks(result)['reservations_released'])

    def test_missing_archive_descriptor_rejected(self):
        path = next(self.capture.glob('epoch-*/raw-archives/*.json'))
        hidden = path.with_suffix('.hidden')
        path.rename(hidden)
        try:
            with self.assertRaisesRegex(ValueError, 'gzip set'):
                verify_capture(self.capture, self.result)
        finally:
            hidden.rename(path)

    def test_corrupt_compressed_payload_rejected(self):
        path = next(self.capture.glob('epoch-*/raw-archives/*.gz'))
        original = path.read_bytes()
        try:
            path.write_bytes(original[:-1])
            with self.assertRaises((EOFError, ValueError, OSError)):
                verify_capture(self.capture, self.result)
        finally:
            path.write_bytes(original)

    def test_changed_persisted_summary_rejected(self):
        path = self.capture/'collection_result.json'
        original = path.read_bytes()
        try:
            value = json.loads(original)
            value['audits'][0]['valid_batches'] += 1
            path.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, 'persisted result'):
                verify_capture(self.capture, self.result)
        finally:
            path.write_bytes(original)

    def test_changed_checkpoint_receipt_rejected(self):
        path = self.capture/'epoch-00/replay-state/checkpoint.json'
        original = path.read_bytes()
        try:
            value = json.loads(original)
            value['revision'] += 1
            path.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, 'checkpoint'):
                verify_capture(self.capture, self.result)
        finally:
            path.write_bytes(original)


class HarnessHistoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_attempt_still_records_inspection_and_counts(self):
        class Transport:
            connection_attempts = 3
            snapshot_attempts = 1
            timings = []
        async def fail(*args, **kwargs):
            raise OSError('injected transport setup failure')
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'probe'
            row = await run_probe(output, _transport=Transport(), _runner=fail)
            self.assertFalse(row['success'])
            record = json.loads((output/'inspection_record.json').read_text())
            self.assertEqual(record['connection_attempts'], 3)
            self.assertEqual(record['snapshot_attempts'], 1)
            self.assertIn('OSError', record['error'])
            self.assertGreater(record['conservative_inspection_end_utc_ns'], 0)
            self.assertTrue((output/'harness_plan.json').exists())
            self.assertTrue((output/'harness_result.json').exists())

    async def test_invalid_duration_opens_no_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'probe'
            for seconds in (True, 4, 121):
                with self.assertRaises(ValueError):
                    await run_probe(output, seconds=seconds)
                self.assertFalse(output.exists())
