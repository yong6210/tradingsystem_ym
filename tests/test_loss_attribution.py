import unittest
from copy import deepcopy
import numpy as np
import pandas as pd
from app.research.baseline.account import Costs
from app.research.diagnostics.loss_attribution import cycles_from_events,early_exit,describe_cycle,block_total_interval


def market():
    return pd.DataFrame(dict(o=100.,h=101.,l=99.,c=100.,v=1.),index=pd.date_range('2025-01-01',periods=10,freq='min',tz='UTC'))


def sample(side=1):
    frame=market()
    entry=dict(kind='entry',time=frame.index[1].isoformat(),qty=1.,side=side,price=100.,fee=1.)
    funding=dict(kind='funding',time=frame.index[4].isoformat(),amount=.5)
    exit=dict(kind='exit',time=frame.index[8].isoformat(),qty=1.,side=-side,price=102.,fee=1.)
    trade=dict(entry_time=entry['time'],exit_time=exit['time'],side=side,quantity=1.,entry_minute=1,exit_minute=8,
               entry_price=100.,net_pnl=side*2-2.5,reason='neutral_exit')
    return frame,[entry,funding,exit],[trade]


class AttributionTests(unittest.TestCase):
    def test_long_short_identity(self):
        for side in (1,-1):
            frame,events,trades=sample(side)
            cycle=cycles_from_events(events,trades)[0]
            self.assertEqual(cycle['gross'],side*2)
            self.assertEqual(cycle['net'],side*2-2.5)

    def test_same_time_reversal_preserves_funding_owner(self):
        frame,events,trades=sample()
        second=deepcopy(events)
        second[0]['time']=events[-1]['time']
        second[1]['time']=events[-1]['time']
        second[1]['amount']=.2
        second_trade=dict(trades[0],entry_time=second[0]['time'],net_pnl=-.2)
        result=cycles_from_events(events+second,trades+[second_trade])
        self.assertEqual([r['funding_paid'] for r in result],[.5,.2])

    def test_bad_ledger_rejected(self):
        frame,events,trades=sample()
        for broken in (events[:-1],[events[1]]+events,events+[events[-1]]):
            with self.assertRaises(ValueError): cycles_from_events(broken,trades)

    def test_funding_at_cap_included_after_entry(self):
        frame,events,trades=sample()
        cycle=cycles_from_events(events,trades)[0]
        before=early_exit(cycle,frame,Costs(0,0,0,.1),2)
        at=early_exit(cycle,frame,Costs(0,0,0,.1),3)
        self.assertEqual(before['net'],-1.)
        self.assertEqual(at['net'],-1.5)

    def test_original_stop_and_tie_preserved(self):
        frame,events,trades=sample()
        cycle=cycles_from_events(events,trades)[0]
        for cap in (7,8,100):
            result=early_exit(cycle,frame,Costs(),cap)
            self.assertFalse(result['changed']);self.assertEqual(result['delta'],0)

    def test_close_excursion_excludes_exit_bar_and_lags_regime(self):
        frame,events,trades=sample()
        frame.loc[frame.index[8],'c']=10000
        regimes=np.array([2]+[4]*9)
        row=describe_cycle(cycles_from_events(events,trades)[0],frame,regimes)
        self.assertEqual(row['close_mfe'],0)
        self.assertEqual(row['entry_regime'],2)

    def test_zero_calendar_and_constant_bootstrap(self):
        start='2025-01-01T00:00:00+00:00';end='2025-01-04T00:00:00+00:00'
        self.assertEqual(block_total_interval([],start,end)['interval95'],[0.,0.])
        rows=[dict(entry_time=f'2025-01-0{i}T01:00:00+00:00',delta=1.) for i in range(1,4)]
        result=block_total_interval(rows,start,end,2,100)
        self.assertEqual(result['days'],3);self.assertEqual(result['interval95'],[3.,3.])

    def test_counterfactual_short_profit(self):
        frame,events,trades=sample(-1)
        frame.loc[frame.index[3],'o']=90.
        result=early_exit(cycles_from_events(events,trades)[0],frame,Costs(0,0,0,.1),2)
        self.assertEqual(result['net'],9.)
