import json
import unittest
from dataclasses import replace
from pathlib import Path
from app.research.recovery.market_adapter import MarketAdapter
from app.research.recovery.models import Bar, Quote
from tests import test_recovery_entry_assessment as fixtures

ROOT = Path(__file__).resolve().parents[1]


class MarketTests(unittest.TestCase):
    def adapter(self):
        return MarketAdapter(json.loads((ROOT/'configs/research/recovery_market_v01.json').read_text()))

    def test_pivot_needs_two_completed_right_quarters(self):
        a = self.adapter()
        for i in range(1,76):
            low = 90 if 31 <= i <= 45 else 95
            a.observe(Bar(i*60000,100,105,low,100,i*60000))
            if i < 75:
                self.assertFalse(a.zones)
        self.assertEqual(len(a.zones),1)
        observer = next(iter(a.zones.values()))
        self.assertEqual(observer.history.as_of(75*60000)['state'],'candidate')
        self.assertIsNone(observer.last_bar)
        self.assertEqual(observer.history.zone.available_ms,75*60000)

    def test_gap_locks_without_consuming_future_bar(self):
        a = self.adapter()
        a.observe(Bar(60000,100,101,99,100,60000))
        with self.assertRaises(ValueError):
            a.observe(Bar(180000,100,101,99,100,180000))
        self.assertEqual(a.last_end,60000)
        self.assertTrue(a.replay.engine.locks)

    def test_quote_cannot_precede_received_bar(self):
        a = self.adapter()
        a.observe(Bar(60000,100,101,99,100,60010))
        with self.assertRaises(ValueError):
            a.decide(Quote(60000,100,100,1,1,1,True,True))

    def test_between_minute_decision_does_not_include_future_bar(self):
        f = fixtures.AdmissionTests(); f.setUp()
        c = replace(f.contract,decision_ms=120123,expected_by_ms=180123,reaction_by_ms=180123)
        bars = [f.bars[0],replace(f.bars[1],received_ms=120100),Bar(180000,100,999,1,100,180000)]
        r = f.reach(c,bars)
        self.assertEqual(r.excursions,f.reach().excursions)
        with self.assertRaises(ValueError):
            f.reach(c,[bars[0],replace(bars[1],received_ms=120124)])

    def test_delayed_pivot_registration_skips_partial_bar(self):
        a = self.adapter()
        for i in range(1,77):
            a.observe(Bar(i*60000,100,105,90 if 31<=i<=45 else 95,100,i*60000+100))
        observer = next(iter(a.zones.values()))
        self.assertIsNone(observer.last_bar)
        a.observe(Bar(77*60000,100,105,95,100,77*60000+100))
        self.assertEqual(next(iter(a.zones.values())).last_bar.end_ms,77*60000)

    def test_adapter_restart_retains_zones_and_locks_orders(self):
        a=self.adapter()
        for i in range(1,78):
            a.observe(Bar(i*60000,100,105,90 if 31<=i<=45 else 95,100,i*60000))
        restored=MarketAdapter.restore(a.config,a.checkpoint(),77*60000+1)
        self.assertEqual(restored.zones,a.zones)
        self.assertEqual(restored.bars,a.bars)
        self.assertEqual(restored.last_end,a.last_end)
        self.assertIn('restart',restored.replay.engine.locks)
        with self.assertRaises(ValueError):
            config=json.loads(json.dumps(a.config)); config['adapter']['reaction_minutes']=10
            MarketAdapter.restore(config,a.checkpoint(),77*60000+1)


if __name__ == '__main__':
    unittest.main()
