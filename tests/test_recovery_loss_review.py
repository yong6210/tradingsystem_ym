"""Hand-calculated quote trigger attribution, separate from strategy outcomes."""
import unittest
from decimal import Decimal as D
from scripts.review_recovery_market_losses import slippage_only_stop


class AttributionTests(unittest.TestCase):
    def test_long_boundary_crossed_only_by_execution_haircut(self):
        # Recorded example: half-spread bid 81051.7 stays above stop;
        # including slippage gives 81035.5, which crosses the stop.
        self.assertTrue(slippage_only_stop(1,D('81046.3'),D('81055.8'),D('81050'),D('.00005'),D('.0002'),D('.1')))

    def test_short_symmetric_and_actual_breach_not_mislabelled(self):
        self.assertTrue(slippage_only_stop(-1,D('100'),D('99.98'),D('99.99'),D(0),D('.001'),D('.001')))
        self.assertFalse(slippage_only_stop(-1,D('100'),D('100.01'),D('99.99'),D(0),D('.001'),D('.001')))
        self.assertFalse(slippage_only_stop(-1,D('100'),D('99.98'),D('100'),D(0),D('.001'),D('.001')))

    def test_no_slippage_cannot_be_attributed_to_slippage(self):
        for side in (1,-1):
            self.assertFalse(slippage_only_stop(side,D('100'),D('100'),D('100')+side,D('.00005'),D(0),D('.1')))


if __name__=='__main__':unittest.main()
