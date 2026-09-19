import unittest
from decimal import Decimal as D
from app.research.diagnostics.execution_cost_evidence import (
    displayed_leg, diagnose, stats, validate_grid, NS)


def point(t=0, shift=D(0)):
    return dict(time_ns=t, valid=True, mid=str(D('100.5') + shift),
                bids=[[str(D(100 - i) + shift), '.0006'] for i in range(5)],
                asks=[[str(D(101 + i) + shift), '.0006'] for i in range(5)],
                last_depth_ns=t, last_mark_ns=t, quality_reset_ns=-60 * NS)


class ExecutionCostEvidenceTest(unittest.TestCase):
    def test_multilevel_buy_sell_and_decomposition(self):
        for side, expected in ((1, '101.4'), (-1, '99.6')):
            leg = displayed_leg(point(), side)
            self.assertEqual(D(leg['vwap']), D(expected))
            self.assertAlmostEqual(D(leg['total_bps']),
                                   D(leg['half_spread_bps']) + D(leg['depth_bps']))

    def test_insufficient_not_reported_as_filled(self):
        leg = displayed_leg(point(), 1, D('.004'))
        self.assertEqual(leg['status'], 'INSUFFICIENT_VISIBLE_DEPTH')
        self.assertEqual(D(leg['unfilled_qty']), D('.001'))
        self.assertNotIn('vwap', leg)

    def test_delay_sign_and_reference(self):
        grid = [point(i * NS, D(i)) for i in range(4)]
        rows = diagnose(grid)
        buy, sell = rows[0]['delayed'], rows[1]['delayed']
        self.assertGreater(D(buy['move_bps']), 0)
        self.assertLess(D(sell['move_bps']), 0)
        self.assertLess(D(sell['total_bps']), 0)
        self.assertAlmostEqual(D(buy['total_bps']), D('3.9') / D('100.5') * 10000)
        self.assertAlmostEqual(D(buy['total_bps']), sum(D(buy[k]) for k in
                               ('move_bps', 'half_spread_bps', 'depth_bps')))

    def test_invalid_interior_cannot_be_bridged(self):
        grid = [point(i * NS) for i in range(4)]
        grid[1]['valid'] = False
        rows = diagnose(grid)
        self.assertEqual(rows[0]['delayed']['status'], 'INVALID_PATH')
        self.assertEqual(rows[2]['immediate']['status'], 'INVALID_GRID')
        self.assertEqual(rows[-1]['delayed']['status'], 'END_OF_INTERVAL')

    def test_grid_causality_and_order(self):
        for mutate in (lambda p: p.update(mid='100'),
                       lambda p: p.update(last_depth_ns=1),
                       lambda p: p.update(asks=list(reversed(p['asks']))),
                       lambda p: p.update(quality_reset_ns=0)):
            p = point()
            mutate(p)
            with self.assertRaises(ValueError):
                validate_grid([p])
        with self.assertRaises(ValueError):
            validate_grid([point(), point(2 * NS)])

    def test_nearest_rank_and_empty(self):
        self.assertEqual(stats(['1', '2', '3', '4'])['median'], '2')
        self.assertEqual(stats(range(1, 21))['p95'], '19')
        self.assertIsNone(stats([])['mean'])


if __name__ == '__main__':
    unittest.main()
