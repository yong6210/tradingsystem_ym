import unittest
from app.research.data.retention_capacity import retention_capacity


class CapacityTests(unittest.TestCase):
    def scenario(self,**overrides):
        args=dict(seconds=120,raw_bytes_per_second=1000,gzip_ratio_ppm=200000,
            metadata_bytes_per_unit=100,seal_seconds=2,free_bytes=100*1024**3,logical_cap_bytes=64*1024**3)
        return retention_capacity(**(args|overrides))
    def test_closed_capture_peak_includes_all_raw(self):
        r=self.scenario();self.assertEqual(r['archive_only_steady_bytes'],30000)
        self.assertEqual(r['retain_all_until_closed_bytes'],150000);self.assertFalse(r['long_run_admitted'])
    def test_24h_fails_protocol_even_with_unlimited_space(self):
        r=self.scenario(seconds=86400,free_bytes=10**18,logical_cap_bytes=10**18)
        self.assertEqual(r['units'],43200);self.assertTrue(r['hypothetical_active_retirement_space_fit'])
        self.assertIn('TOTAL_UNIT_BUDGET',r['blockers']);self.assertIn('SUPERVISOR_EVENT_BUDGET_EVEN_BEFORE_FIXED_OVERHEAD',r['blockers'])
        self.assertFalse(r['long_run_admitted'])
    def test_ceiling_never_rounds_required_bytes_down(self):
        r=self.scenario(seconds=3,raw_bytes_per_second=1,gzip_ratio_ppm=333334)
        self.assertEqual(r['gzip_bytes'],2);self.assertEqual(r['units'],2)
    def test_logical_cap_and_disk_reserve_checked_separately(self):
        self.assertFalse(self.scenario(logical_cap_bytes=1000)['hypothetical_active_retirement_space_fit'])
        self.assertFalse(self.scenario(free_bytes=16*1024**3)['hypothetical_active_retirement_space_fit'])
    def test_existing_bytes_do_not_receive_new_allowance(self):
        r=self.scenario(logical_cap_bytes=1000,existing_bytes=999)
        self.assertEqual(r['available_logical_bytes'],1)
    def test_invalid_and_bool_inputs_rejected(self):
        for kw in [dict(seconds=True),dict(gzip_ratio_ppm=0),dict(seal_seconds=0),dict(free_bytes=-1)]:
            with self.assertRaises((ValueError,RuntimeError)):self.scenario(**kw)
