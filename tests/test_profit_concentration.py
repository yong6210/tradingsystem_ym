import unittest
from decimal import Decimal as D
from app.research.diagnostics.concentration import (
    concentration,direction_groups,daily_attribution,calendar_months,episode_flow)


class ConcentrationTests(unittest.TestCase):
    def test_top_profit_denominator_is_winners_not_small_net(self):
        result=concentration([dict(id=i,net=v) for i,v in enumerate((10,5,-12))],(1,5))
        self.assertEqual(result['net'],3)
        self.assertAlmostEqual(result['top'][0]['positive_profit_share'],2/3)
        self.assertEqual(result['top'][0]['arithmetic_net_without_top'],-7)
        self.assertEqual(result['top'][1]['actual_count'],2)
        self.assertEqual(result['profit_factor'],1.25)

    def test_no_winners_or_no_losers_do_not_invent_ratios(self):
        loss=concentration([dict(id=0,net=-2),dict(id=1,net=0)],(1,))
        self.assertIsNone(loss['top'][0]['positive_profit_share'])
        self.assertEqual(loss['profit_factor'],0)
        self.assertEqual(loss['flat'],1)
        win=concentration([dict(id=0,net=2)],(1,))
        self.assertIsNone(win['profit_factor'])
        self.assertIsNone(win['mean_loser'])

    def test_ties_stable_and_invalid_values_rejected(self):
        result=concentration([dict(id='a',net=2),dict(id='b',net=2)],(1,))
        self.assertEqual(result['top'][0]['ids'],['a'])
        for rows in ([],[dict(id=0,net=float('nan'))]):
            with self.assertRaises(ValueError):concentration(rows,(1,))

    def test_direction_group_keeps_every_cycle_and_cash_gap(self):
        cycles=[dict(id=i,side=s,net=v,entry_time=f'2025-01-0{i*2+1}',exit_time=f'2025-01-0{i*2+2}')
                for i,(s,v) in enumerate(((1,10),(1,-2),(-1,3),(1,4)))]
        groups=direction_groups(cycles)
        self.assertEqual([g['cycle_ids'] for g in groups],[[0,1],[2],[3]])
        self.assertEqual([g['net'] for g in groups],[8,3,4])
        cycles[1]['entry_time']='2025-01-01'
        with self.assertRaises(ValueError):direction_groups(cycles)

    def fixture(self):
        events=[dict(time='2025-01-31T12:00:00+00:00',kind='entry',qty=1,side=1,price=100,fee=1,balance=99,quantity=1,average=100),
                dict(time='2025-02-01T08:00:00+00:00',kind='funding',historical_amount=-2,stress_amount=.5,amount=-1.5,balance=100.5,quantity=1,average=100),
                dict(time='2025-02-01T12:00:00+00:00',kind='exit',qty=1,side=-1,price=110,fee=1,pnl=10,balance=109.5,quantity=0,average=0)]
        days=[dict(day='2025-01-31',equity=104),dict(day='2025-02-01',equity=109.5)]
        parts={i:dict(slippage=D(0),tick_rounding=D(0)) for i in (0,2)}
        return events,days,dict(zip(('2025-01-31','2025-02-01'),(105,110))),parts

    def test_month_boundary_mtm_not_exit_month_attribution(self):
        rows=daily_attribution(*self.fixture(),initial=100)
        months=calendar_months(rows)
        self.assertEqual([r['fill_mtm'] for r in months],[5,5])
        self.assertEqual([r['net'] for r in months],[4,5.5])
        self.assertEqual(months[1]['historical_funding'],-2)
        self.assertEqual(months[1]['stress_funding'],.5)

    def test_episode_excludes_peak_day_costs(self):
        rows=daily_attribution(*self.fixture(),initial=100)
        period=episode_flow(rows,'2025-01-31','2025-02-01')
        self.assertEqual(period['fees'],1)
        self.assertEqual(period['net'],5.5)
        with self.assertRaises(ValueError):episode_flow(rows,'2025-01-29','2025-02-01')

    def test_same_timestamp_exit_then_entry_is_preserved(self):
        events,days,prices,parts=self.fixture()
        at='2025-02-01T12:00:00+00:00'
        events += [dict(time=at,kind='entry',qty=1,side=-1,price=110,fee=1,balance=108.5,quantity=-1,average=110),
                   dict(time='2025-02-01T23:59:00+00:00',kind='exit',qty=1,side=1,price=108,fee=1,pnl=2,balance=109.5,quantity=0,average=0)]
        parts.update({i:dict(slippage=D(0),tick_rounding=D(0)) for i in (3,4)})
        rows=daily_attribution(events,days,prices,parts,initial=100)
        self.assertEqual(rows[1]['realized'],12)
        self.assertEqual(rows[1]['net'],5.5)

    def test_missing_days_and_uncovered_events_are_rejected(self):
        events,days,prices,parts=self.fixture()
        days[1]['day']='2025-02-02'
        with self.assertRaises(ValueError):daily_attribution(events,days,prices,parts,initial=100)
        events,days,prices,parts=self.fixture()
        events[0]['time']='2025-01-30T12:00:00+00:00'
        with self.assertRaises(ValueError):daily_attribution(events,days,prices,parts,initial=100)


if __name__=='__main__':unittest.main()
