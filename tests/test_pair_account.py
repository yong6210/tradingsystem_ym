from decimal import Decimal as D
import unittest
from app.research.diagnostics.pair_account import Book,run,signals,HOUR


def rows(count=5,start=1725148800000):
    import datetime
    return [dict(time_ms=start+i*HOUR,hour=datetime.datetime.fromtimestamp((start+i*HOUR)/1000,datetime.timezone.utc).isoformat(),
        btc_open='60000',btc_close='60000',btc_mark_open='60000',btc_mark_close='60000',
        eth_open='3000',eth_close='3000',eth_mark_open='3000',eth_mark_close='3000') for i in range(count)]


CONTRACTS={name:dict(step=D('.001'),min_qty=D('.001'),max_qty=D('1000'),min_notional=D(minimum))
    for name,minimum in [('BTCUSDC','50'),('ETHUSDC','20')]}


def account(rr,zz,ff=(),cost=0):
    return run(rr,ff,CONTRACTS,slip_bps=2,extra_funding_bps=0,monthly_cost=cost,signal_values=zz)


class PairAccountTests(unittest.TestCase):
    def test_long_and_short_realization_fee(self):
        b=Book();b.fill('a','btc',1,'.003','60000',1,1);b.fill('b','eth',-1,'.06','3000',2,1)
        b.fill('c','btc',-1,'.003','61000',3,1);b.fill('d','eth',1,'.06','2900',4,1)
        self.assertEqual(D(b.s['wallet']['btc']),D('402.90925'))
        self.assertEqual(D(b.s['wallet']['eth']),D('405.9115'))
    def test_partial_close_preserves_actual_residual_and_overclose_rejected(self):
        b=Book();b.fill('a','btc',-1,'.003','60000',1,1);b.fill('b','btc',1,'.001','61000',2,1)
        self.assertEqual(D(b.s['position']['btc']),D('-.002'))
        with self.assertRaises(ValueError):b.fill('c','btc',1,'.003','61000',3,1)
        self.assertEqual(D(b.s['position']['btc']),D('-.002'))
    def test_fill_duplicate_and_conflict(self):
        b=Book();b.fill('a','btc',1,'.003','60000',1,1);before=b.restore().s
        b.fill('a','btc',1,'.003','60000',1,1);self.assertEqual(before,b.s)
        with self.assertRaises(ValueError):b.fill('a','btc',1,'.003','61000',1,1)
    def test_nonfinite_fill_rejected(self):
        with self.assertRaises(ValueError):Book().fill('a','btc',1,'.003','Infinity',1,1)
    def test_funding_same_timestamp_precedes_fill(self):
        b=Book();b.fill('a','btc',1,'.003','60000',10,1)
        e=dict(leg='btc',time_ms=10,mark='60000',rate='.01');b.fund(e,10,D(0))
        self.assertEqual(D(b.s['wallet']['btc']),D('399.955'))
        e['time_ms']=11;b.fund(e,11,D('.0001'));after=b.s['wallet']['btc'];b.fund(e,11,D('.0001'))
        self.assertEqual(after,b.s['wallet']['btc']);self.assertEqual(D(after),D('398.137'))
    def test_serialized_book_retains_position_and_duplicate_ids(self):
        b=Book();b.fill('a','eth',-1,'.06','3000',1,1);r=b.restore()
        r.fill('a','eth',-1,'.06','3000',1,1);r.fill('b','eth',1,'.06','2900',2,1)
        self.assertEqual(D(r.s['wallet']['eth']),D('405.9115'))
    def test_signals_exclude_current_and_future_from_reference_window(self):
        rr=rows(725)
        for i,r in enumerate(rr):r['eth_close']=str(3000+i%17)
        aa=signals(rr);rr[724]['eth_close']='9000';bb=signals(rr)
        self.assertEqual(aa[:724],bb[:724]);self.assertTrue(all(x is None for x in aa[:720]))
        rr[720]['eth_close']='6000';cc=signals(rr)
        self.assertGreater(cc[720],aa[720]+100)
    def test_zero_variance_no_entry(self):
        rr=rows(724);self.assertTrue(all(x is None for x in signals(rr)))
    def test_signal_executes_only_next_hour_and_legs_sequential(self):
        rr=rows();r=account(rr,[2.5,2.5,0,0,0]);fills=[x for x in r['ledger'] if x['type']=='fill']
        self.assertEqual(fills[0]['time_ms'],rr[1]['time_ms']+3001)
        self.assertEqual(fills[1]['time_ms'],rr[1]['time_ms']+6003)
        self.assertEqual([f['side'] for f in fills],[1,-1,-1,1])
        self.assertEqual(r['cycles'][0]['reason'],'REVERT')
    def test_opposite_signal_direction(self):
        r=account(rows(),[-2.5,-2.5,0,0,0]);fills=[x for x in r['ledger'] if x['type']=='fill']
        self.assertEqual([f['side'] for f in fills],[-1,1,1,-1])
    def test_pair_loss_and_complete_hour_cooldown(self):
        rr=rows(8);rr[2]['eth_open']='3200'
        r=account(rr,[2.5]*8)
        self.assertEqual(r['cycles'][0]['reason'],'PAIR_LOSS')
        self.assertLess(D(r['cycles'][0]['net_pnl']),-5)
        entries=[o for o in r['orders'] if o['role']=='ENTRY' and o['leg']=='btc']
        self.assertGreaterEqual(entries[1]['created_ms'],rr[4]['time_ms'])
    def test_final_hour_closes_and_does_not_reenter(self):
        rr=rows();r=account(rr,[2.5]*5)
        self.assertEqual(r['cycles'][-1]['reason'],'REGISTERED_END')
        self.assertTrue(all(D(q)==0 for q in r['state']['position'].values()))
    def test_future_funding_not_used_before_settlement(self):
        rr=rows(6);t=rr[4]['time_ms'];e=dict(leg='btc',time_ms=t,mark='60000',rate='.5')
        a=account(rr,[2.5]*6,[e]);b=account(rr,[2.5]*6,[dict(e,rate='-.5')])
        self.assertEqual([o for o in a['orders'] if o['created_ms']<t],[o for o in b['orders'] if o['created_ms']<t])
    def test_daily_reset_does_not_reset_permanent_halt(self):
        b=Book();row=rows()[0];b.risk(row,D(0),row['time_ms'])
        b.s['outside']='175';self.assertEqual(b.risk(row,D(0),row['time_ms']+1),'DAILY')
        self.assertIsNone(b.risk(row,D(0),row['time_ms']+86400000))
        b.s['outside']='100';self.assertEqual(b.risk(row,D(0),row['time_ms']+86400001),'DRAWDOWN')
        self.assertEqual(b.risk(row,D(0),row['time_ms']+2*86400000),'DRAWDOWN')
    def test_operating_cost_after_halt_still_charged_once(self):
        b=Book();b.s['halt']='DRAWDOWN';b.cost('month',2,1);b.cost('month',2,1)
        self.assertEqual(D(b.s['outside']),198)
    def test_current_individual_wallet_margin_is_not_shared(self):
        b=Book();b.fill('a','btc',-1,'.003','60000',1,1);b.fill('b','eth',1,'.06','3000',2,1);row=rows()[0]
        row['btc_mark_open']='200000';row['btc_open']='200000'
        row['eth_mark_open']='10000';row['eth_open']='10000'
        self.assertEqual(b.risk(row,D(0),3),'MARGIN')
        self.assertEqual(D(b.s['wallet']['eth']),D('399.955'))
    def test_extreme_exit_uses_last_completed_signal(self):
        rr=rows(6);r=account(rr,[2.5,4.5,4.5,0,0,0])
        self.assertEqual(r['cycles'][0]['reason'],'EXTREME')
        self.assertEqual(r['cycles'][0]['exit_time_ms'],rr[2]['time_ms']+3)
    def test_time_exit_at_first_hourly_check_after_168_hours(self):
        rr=rows(174);r=account(rr,[2.5]*174)
        c=r['cycles'][0];self.assertEqual(c['reason'],'TIME')
        held=c['exit_time_ms']-c['entry_time_ms']
        self.assertGreaterEqual(held,168*HOUR);self.assertLess(held,170*HOUR)


if __name__=='__main__':unittest.main()
