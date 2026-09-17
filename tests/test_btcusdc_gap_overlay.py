import unittest
from scripts.validate_btcusdc_gap_overlay import validate_bars


class GapValidationTest(unittest.TestCase):
    def bar(self, time=0):
        return [time, '10', '12', '9', '11', '0', time + 59999, '0', 0, '0', '0', '0']

    def test_exact_coverage(self):
        self.assertEqual(validate_bars([self.bar(), self.bar(60000)], 0, 120000), 2)

    def test_missing_duplicate_reverse(self):
        for rows in ([], [self.bar(), self.bar()], [self.bar(60000), self.bar()]):
            with self.assertRaises(ValueError):
                validate_bars(rows, 0, 120000)

    def test_invalid_prices_and_geometry(self):
        for column, value in ((1, 'NaN'), (2, 'Infinity'), (3, '0'), (2, '9'), (3, '12')):
            row = self.bar()
            row[column] = value
            with self.assertRaises(ValueError):
                validate_bars([row], 0, 60000)

    def test_close_time(self):
        row = self.bar()
        row[6] = 60000
        with self.assertRaises(ValueError):
            validate_bars([row], 0, 60000)
