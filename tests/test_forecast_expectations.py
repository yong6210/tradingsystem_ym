from datetime import datetime, timedelta, timezone
import unittest
from scripts.audit_forecast_expectations import past_mean, band, scores, improvement, selected_summary


class ForecastExpectationTest(unittest.TestCase):
    def test_control_uses_only_original_matured_window(self):
        t = datetime(2026, 9, 1, tzinfo=timezone.utc)
        panel = {t - timedelta(days=k): dict(target_bps=float(k), exit_time=(t - timedelta(days=k-1)).isoformat()) for k in range(-1, 183)}
        self.assertEqual(past_mean(panel, t), 91.5)
        for k in [-1, 0, 1, 182]:
            panel[t - timedelta(days=k)]['target_bps'] = 999999.
        self.assertEqual(past_mean(panel, t), 91.5)

    def test_rejects_missing_or_unmatured_history(self):
        t = datetime(2026, 9, 1, tzinfo=timezone.utc)
        with self.assertRaises(KeyError):
            past_mean({}, t)
        panel = {t - timedelta(days=k): dict(target_bps=1., exit_time=t.isoformat()) for k in range(2, 182)}
        with self.assertRaises(ValueError):
            past_mean(panel, t)

    def test_bands_include_exact_boundaries(self):
        self.assertEqual(band(-10., 10.), 'inactive')
        self.assertEqual(band(-20., 10.), 'H_to_2H')
        self.assertEqual(band(20.1, 10.), 'above_2H')

    def test_mse_is_not_mae_and_zero_reference_is_null(self):
        self.assertEqual(scores([1., 3.], [0., 0.])['mse_bps_squared'], 5.)
        self.assertEqual(scores([1., 3.], [0., 0.])['mae_bps'], 2.)
        self.assertIsNone(improvement(0., 0.))

    def test_inactive_does_not_become_net_trade_return(self):
        rows = [dict(prediction_bps=-3., target_bps=4.)]
        result = selected_summary(rows, False)
        self.assertEqual(result['actual_direction_bps'], -4.)
        self.assertIsNone(result['base_net_bps'])
        self.assertIsNone(selected_summary([], True)['actual_direction_bps'])


if __name__ == '__main__':
    unittest.main()
