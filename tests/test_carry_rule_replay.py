from datetime import datetime, timezone
from decimal import Decimal as D
from pathlib import Path
import tempfile
import unittest

from app.research.diagnostics.carry_rule_replay import run, independent_audit, HOUR


def rows(start='2024-09-01T00:00:00+00:00', count=4):
    t=int(datetime.fromisoformat(start).timestamp()*1000)
    return [dict(time_ms=t+i*HOUR,spot_open='60000',spot_close='60000',
        future_open='60000',future_close='60000',mark_open='60000',mark_close='60000') for i in range(count)]


class CarryRuleReplayTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def execute(self,rr,ff=(),*,cost=0,extra=0,name='run'):
        out=self.root/name
        result=run(out,rr,ff,slip_bps=2,extra_funding_bps=extra,monthly_cost=cost)
        audit=independent_audit(out,rr,result,2)
        return result,audit
    def test_delayed_two_leg_fill_and_registered_end(self):
        r,a=self.execute(rows())
        self.assertEqual(a['fills'],4);self.assertEqual(a['orders'],8)
        self.assertEqual(r['first_exit']['reason'],'REGISTERED_END')
        self.assertGreater(r['opened_at']-rows()[0]['time_ms'],6000)
        self.assertEqual(D(a['residual_spot']),0);self.assertLess(D(a['net_usdc']),0)
    def test_funding_before_hedge_zero_and_later_historical_position(self):
        rr=rows();t=rr[0]['time_ms']
        ff=[dict(time_ms=t+1,mark='60000',rate='.01'),dict(time_ms=t+7000,mark='60000',rate='.0001'),
            dict(time_ms=t+HOUR,mark='60000',rate='-.0001')]
        r,a=self.execute(rr,ff)
        self.assertEqual(D(r['adjustments'][0]['receipt']),0)
        self.assertEqual(D(r['adjustments'][1]['receipt']),D('.036'))
        self.assertEqual(D(a['funding_net']),0)
    def test_risk_exit_stays_flat_and_later_funding_zero(self):
        rr=rows(count=6);rr[1]['spot_open']='58000';rr[1]['spot_close']='58000'
        ff=[dict(time_ms=rr[3]['time_ms'],mark='60000',rate='.1')]
        r,a=self.execute(rr,ff)
        self.assertEqual(r['first_exit']['time_ms'],rr[1]['time_ms'])
        self.assertEqual(r['first_exit']['reason'],'RISK_OR_ENTRY_FAILURE')
        self.assertEqual(D(a['funding_net']),0)
        self.assertTrue(all(D(p['spot_qty'])==0 for p in r['rows'][1:]))
        self.assertEqual(a['fills'],4)
    def test_unknown_future_close_does_not_change_earlier_actions(self):
        rr=rows();a,_=self.execute(rr,name='a')
        changed=[dict(r) for r in rr];changed[0]['spot_close']='30000';changed[0]['mark_close']='150000'
        b,_=self.execute(changed,name='b')
        self.assertEqual(a['decisions'],b['decisions'])
        self.assertNotEqual(a['rows'][0]['equity'],b['rows'][0]['equity'])
    def test_operating_cost_continues_after_halt(self):
        rr=rows('2024-09-30T21:00:00+00:00',count=5)
        rr[1]['spot_open']='58000'
        r,a=self.execute(rr,cost=2)
        self.assertEqual(r['first_exit']['time_ms'],rr[1]['time_ms'])
        self.assertEqual(D(a['operating_cost']),2)
        self.assertEqual(r['adjustments'][0]['posted_ms'],rr[2]['time_ms'])
        self.assertEqual(D(r['rows'][1]['equity'])-D(r['rows'][2]['equity']),2)
    def test_future_funding_change_cannot_affect_earlier_exit(self):
        rr=rows(count=6);rr[1]['spot_open']='58000'
        t=rr[4]['time_ms']
        a,aa=self.execute(rr,[dict(time_ms=t,mark='60000',rate='.1')],name='a')
        b,bb=self.execute(rr,[dict(time_ms=t,mark='60000',rate='-.1')],name='b')
        self.assertEqual(a['decisions'],b['decisions']);self.assertEqual(aa['terminal_equity'],bb['terminal_equity'])


if __name__=='__main__':unittest.main()
