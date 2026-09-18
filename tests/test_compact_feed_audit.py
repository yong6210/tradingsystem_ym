from copy import deepcopy
from pathlib import Path
import random
import tempfile
import unittest

from app.research.data.compact_feed_intervals import CompactIntervals, IntervalLimitError
from app.research.data.compact_feed_audit import audit_epoch
from app.research.data.segmented_feed_audit import audit_epoch as previous_audit
from app.research.data.feed_coverage_audit import subtract
from app.research.data.shared_feed_storage import SharedStorageBudget, SegmentedAudit
from app.research.foundation.forward_data_contract import REQUIREMENTS, merge_intervals
from tests.test_feed_coverage_audit import SyntheticEpoch


def reference(points, start, end):
    intervals = {name: [] for name in REQUIREMENTS}
    for (left, expiry, _), (right, _, _) in zip(points, points[1:]):
        for name, until in expiry.items():
            lo, hi = max(start,left), min(end,right,until)
            if lo < hi: intervals[name].append([lo,hi])
    cuts = merge_intervals([span for _,_,spans in points for span in spans if span[0]<span[1]], start, end)
    return {name:subtract(merge_intervals(rows,start,end),cuts) for name,rows in intervals.items()}, cuts


class IntervalTests(unittest.TestCase):
    def compare(self, points, start=0, end=1000):
        reducer = CompactIntervals(start,end)
        for publication, expiry, exclusions in points: reducer.add(publication,expiry,exclusions)
        self.assertEqual(reducer.finish(),reference(points,start,end))
        return reducer

    def test_randomized_expiry_gaps_duplicates_and_retroactive_exclusions(self):
        for seed in range(50):
            rng=random.Random(seed)
            points=[]
            publication=0
            for _ in range(100):
                publication+=rng.randrange(0,20)
                expiry={name:publication+rng.randrange(0,30) for name in REQUIREMENTS if rng.random()<.7}
                cuts=[(rng.randrange(publication+1),publication)] if rng.random()<.1 else []
                points.append((publication,expiry,cuts))
            with self.subTest(seed=seed): self.compare(points)

    def test_single_point_does_not_extrapolate(self):
        reducer=self.compare([(10,dict.fromkeys(REQUIREMENTS,1000),[])])
        self.assertTrue(all(not rows for rows in reducer.finish()[0].values()))

    def test_late_exclusion_removes_multiple_old_intervals(self):
        points=[(10,{'l2':20},[]),(30,{'l2':40},[]),(50,{'l2':70},[]),(90,{},[(15,90)])]
        reducer=self.compare(points)
        self.assertEqual(reducer.finish()[0]['l2'],[[10,15]])

    def test_window_clipping_and_no_final_extension(self):
        reducer=self.compare([(10,{'l2':1000},[]),(100,{'l2':1000},[])],start=20,end=70)
        self.assertEqual(reducer.finish()[0]['l2'],[[20,70]])

    def test_adjacent_points_keep_only_one_interval_per_gate(self):
        reducer=CompactIntervals(0,10000)
        for publication in range(5000): reducer.add(publication,dict.fromkeys(REQUIREMENTS,publication+1))
        self.assertEqual(reducer.peak,len(REQUIREMENTS))
        self.assertEqual(reducer.points,5000)
        self.assertTrue(all(rows==[[0,4999]] for rows in reducer.finish()[0].values()))

    def test_fragmentation_limit_fails_without_truncation(self):
        reducer=CompactIntervals(0,100,max_intervals=2)
        for publication in (0,2,4): reducer.add(publication,{'l2':publication+1})
        with self.assertRaises(IntervalLimitError): reducer.add(6,{'l2':7})
        with self.assertRaises(IntervalLimitError): reducer.finish()
        self.assertTrue(reducer.failed)

    def test_subtraction_output_limit_is_also_enforced(self):
        reducer=CompactIntervals(0,100,max_intervals=4)
        reducer.add(0,{'l2':100,'mark':100})
        reducer.add(10,{'l2':100,'mark':100},[(3,10)])
        reducer.add(20,{'l2':100,'mark':100},[(13,20)])
        reducer.add(30,{})
        with self.assertRaises(IntervalLimitError): reducer.finish()
        self.assertTrue(reducer.failed)

    def test_bad_publication_latches_reducer(self):
        reducer=CompactIntervals(0,100)
        reducer.add(10,{'l2':20})
        with self.assertRaises(ValueError): reducer.add(9,{})
        with self.assertRaises(IntervalLimitError): reducer.add(20,{})

    def test_exclusion_cannot_claim_future_or_unknown_gate(self):
        for expiry,cuts in [({'unknown':12},[]), ({'l2':12},[(1,11)])]:
            reducer=CompactIntervals(0,100)
            with self.assertRaises(ValueError): reducer.add(10,expiry,cuts)


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name).resolve()
        self.e=SyntheticEpoch(self.root/'raw',end=10_000_000_000)
        self.scope=dict(window_start_ns=0,window_end_ns=self.e.end,clock_domain='synthetic-domain')

    def tearDown(self):
        self.e.close()
        self.temp.cleanup()

    def convert(self, batches=None):
        self.e.close()
        disk=SharedStorageBudget.create(self.root/'storage',run_id='synthetic',max_bytes=1_000_000,min_free_bytes=0)
        audit=SegmentedAudit(disk.root/'audit',budget=disk,rotation_bytes=4096,max_record_bytes=3840)
        try:
            for batch in self.e.batches if batches is None else batches: audit.append(batch)
        finally:
            audit.close(); disk.close()
        return disk.root/'audit'

    def compare(self,path,**extra):
        original=previous_audit(self.e.root/'journal',path,**self.scope)
        current=audit_epoch(self.e.root/'journal',path,**self.scope,**extra)
        details=current.pop('interval_reduction')
        self.assertEqual(current,original)
        return current,details

    def test_fresh_then_expiry_and_lifecycle_exclusion(self):
        self.e.fresh(100_000_000)
        self.e.tick(300_000_000)
        self.e.received=400_000_000
        self.e.add('END','market')
        self.e.flush(800_000_000)
        self.compare(self.convert())

    def test_missing_audit_tail_keeps_same_verified_prefix(self):
        self.e.fresh(100_000_000)
        self.e.tick(300_000_000)
        self.e.tick(500_000_000)
        result,_=self.compare(self.convert(self.e.batches[:-1]))
        self.assertEqual(result['unaudited_committed_records'],1)

    def test_invalid_observation_never_increases_coverage(self):
        self.e.fresh(100_000_000)
        self.e.tick(300_000_000)
        batches=deepcopy(self.e.batches)
        batches[-1]['observation']['quote']['bid']='999'
        result,_=self.compare(self.convert(batches))
        self.assertEqual(result['valid_batches'],1)
        self.assertFalse(result['intervals']['l2'])

    def test_committed_audit_corruption_returns_no_coverage(self):
        self.e.fresh(100_000_000)
        path=self.convert()
        segment=next(path.glob('segment-*.jsonl'))
        data=bytearray(segment.read_bytes()); data[-5]^=1; segment.write_bytes(data)
        result,_=self.compare(path)
        self.assertEqual(result['valid_batches'],0)
        self.assertTrue(result['errors'])

    def test_changed_window_is_rejected(self):
        self.e.fresh(100_000_000)
        path=self.convert()
        self.scope['window_end_ns']-=1
        result,_=self.compare(path)
        self.assertTrue(result['errors'])

    def test_replay_budget_failure_cannot_certify_partial_coverage(self):
        self.e.fresh(100_000_000)
        self.e.tick(300_000_000)
        path=self.convert()
        result=audit_epoch(self.e.root/'journal',path,**self.scope,max_intervals=1)
        self.assertTrue(result['errors'])
        self.assertTrue(result['interval_reduction']['failed'])
        self.assertTrue(all(not rows for rows in result['intervals'].values()))


from tests import test_segmented_feed_storage as collector_fixtures
from app.research.data.compact_feed_collector import run_bounded
from app.research.data import compact_feed_collector
from unittest.mock import patch


class CompactCollectorTests(collector_fixtures.CollectorTests):
    async def run_case(self, transport, duration=200_000_000, **kwargs):
        return await run_bounded(self.output, duration_ns=duration, transport=transport, policy=self.policy, **kwargs)

    async def test_audit_resource_limit_rejects_collection_quality(self):
        original = compact_feed_collector.audit_epoch
        def limited(*args, **kwargs):
            return original(*args, **kwargs, max_intervals=1)
        with patch.object(compact_feed_collector, 'audit_epoch', limited):
            result = await self.run_case(collector_fixtures.fixtures.ScriptedTransport())
        self.assertEqual(result['stop_reason'], 'FATAL_FAILURE')
        self.assertEqual(result['combined']['quality']['status'], 'QUALITY_INPUTS_REJECTED')
        self.assertTrue(result['audits'][0]['interval_reduction']['failed'])
        self.assertEqual(result['retries_used'], 0)


if __name__=='__main__': unittest.main()
