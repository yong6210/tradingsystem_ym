"""Pin interpretation of frozen E005 exits; these are not new strategies."""
import unittest
import pandas as pd
from app.research.comparison.policies import family_sides


def frame(**updates):
    values=dict(c=[96.,99.,101.],h=[101.,110.,102.],l=[94.,98.,99.],atr=[2.]*3,er=[.1]*3,z=[-1.]*3,
                high24=[110.]*3,low24=[90.]*3,high12=[105.]*3,low12=[95.]*3)
    values.update(updates)
    return pd.DataFrame(values)


class ExitContractTests(unittest.TestCase):
    def test_intrabar_target_touch_is_not_close_confirmation(self):
        # Target100: second bar high110 touches it, but close99 keeps exposure.
        self.assertEqual(family_sides(frame(),'F0'),[1,1,0])

    def test_target_is_frozen_at_signal_episode_not_current_channel(self):
        # New channel midpoint115 must not replace original target100.
        values=frame(c=[96.,101.,102.],h=[101.,110.,110.],l=[94.,99.,99.],
                     high12=[105.,125.,125.],low12=[95.,105.,105.])
        self.assertEqual(family_sides(values,'F0'),[1,0,0])

    def test_regime_can_exit_before_reversion_target(self):
        values=frame(z=[-2.1,-1.,-.5],er=[.1,.4,.4])
        self.assertEqual(family_sides(values,'R0'),[1,0,0])
