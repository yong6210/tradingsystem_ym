import json
from pathlib import Path
import tempfile
import unittest
from decimal import Decimal as D

from app.research.diagnostics.flow_absorption import signal,market_leg,events,grid_from_raw,NS
from scripts.audit_microstructure_raw_sample import timestamp_ns


def point(second, mid='60000', valid=True, bid_qty='.1', ask_qty='.01'):
    return dict(time_ns=second*NS,valid=valid,mid=mid,
        bids=[[str(D(mid)-D('.1')-i),bid_qty] for i in range(5)],
        asks=[[str(D(mid)+D('.1')+i),ask_qty] for i in range(5)],trades=[])


def flow(second,maker=True):
    return [dict(id=i,time_ns=(second*NS)-i*100_000_000,price='60000',qty='.01',buyer_maker=maker) for i in range(3)]


class FlowBoundaries(unittest.TestCase):
    def test_sell_pressure_buyer_maker_maps_to_supported_long(self):
        self.assertEqual(signal(point(10),point(5),flow(10)),(1,True))

    def test_buy_pressure_mirror_and_depth_ablation(self):
        self.assertEqual(signal(point(10,bid_qty='.01',ask_qty='.1'),point(5),flow(10,False)),(-1,True))
        self.assertEqual(signal(point(10,bid_qty='.01',ask_qty='.1'),point(5),flow(10)),(1,False))

    def test_future_left_boundary_duplicates_do_not_add_evidence(self):
        f=flow(10); f[0]['time_ns']=11*NS;f[1]['time_ns']=5*NS
        self.assertEqual(signal(point(10),point(5),f),(0,False))
        f=flow(10);f[1]['id']=f[0]['id']
        self.assertEqual(signal(point(10),point(5),f),(0,False))

    def test_prices_must_absorb_pressure_and_points_must_be_valid(self):
        self.assertEqual(signal(point(10,mid='59999'),point(5),flow(10)),(0,False))
        self.assertEqual(signal(point(10),point(5,valid=False),flow(10)),(0,False))

    def test_market_cost_uses_displayed_spread_fee_and_adverse_tick(self):
        p=point(10);buy=market_leg(p,1,2);sell=market_leg(p,-1,2)
        self.assertGreater(D(buy['quote']),D('60'))
        self.assertLess(D(sell['quote']),D('60'))
        self.assertEqual(D(buy['fee']),D(buy['quote'])*D('.00025'))
        self.assertEqual(D(buy['fills'][0]['price']) % D('.1'),0)

    def test_insufficient_displayed_size_keeps_residual(self):
        r=market_leg(point(1,ask_qty='.0001'),1,2)
        self.assertEqual(r['status'],'INSUFFICIENT_VISIBLE_SIZE')
        self.assertEqual(D(r['residual']),D('.0005'))

    def test_cohort_clock_is_shared_when_candidate_rejects(self):
        g=[point(i,bid_qty='.01',ask_qty='.1') for i in range(220)]
        for p in g:p['trades']=flow(p['time_ns']//NS)
        r=events(g)
        self.assertEqual([x['signal_ns']//NS for x in r],[5,78,151])
        self.assertFalse(any(x['candidate'] for x in r))
        self.assertTrue(all(x['conditions']['base']['status']=='COMPLETE_CONDITIONAL_EVENT' for x in r))

    def test_entry_and_unresolved_exit_are_not_zero_pnl(self):
        g=[point(i) for i in range(80)];g[5]['trades']=flow(5);g[68]['valid']=False
        r=events(g)[0]['conditions']['base'];self.assertEqual(r['status'],'EXIT_UNRESOLVED');self.assertNotIn('net',r)
        g[8]['valid']=False;r=events(g)[0]['conditions']['base'];self.assertEqual(r['status'],'ENTRY_UNAVAILABLE')

    def test_minimum_notional_and_terminal_boundary(self):
        g=[point(i,mid='40000') for i in range(80)];g[5]['trades']=flow(5)
        self.assertEqual(events(g)[0]['conditions']['base']['status'],'ENTRY_NOTIONAL_REJECTED')
        self.assertEqual(events(g[:68]),[])

    def fixture(self,folder,gap=False,future_change=False):
        start=timestamp_ns('2024-09-01T00:00:00Z');rows=[]
        snap=dict(lastUpdateId=1,bids=[[str(60000-i),'.1'] for i in range(6)],asks=[[str(60001+i),'.1'] for i in range(6)])
        def put(second,stream,data,**extra):
            stamp=f'2024-09-01T00:{second//60:02}:{second%60:02}.0000000Z'
            rows.append(stamp+' '+json.dumps(dict(stream='btcusdc@'+stream,data=data,**extra)))
        put(0,'depthSnapshot',snap,generated=True)
        uid=1
        for sec in range(90):
            if not gap or sec%2==0:
                d=dict(e='depthUpdate',s='BTCUSDC',E=sec,T=sec,U=uid,u=uid+1,pu=uid-1,b=[],a=[])
                if sec:d['pu']=uid
                if future_change and sec>=80:d['b']=[['60000','5']]
                put(sec,'depth@0ms',d);uid+=1
            put(sec,'markPrice@1s',dict(e='markPriceUpdate',s='BTCUSDC',E=sec,T=1000,p='60000',i='60000',r='0'))
        path=folder/'raw';path.write_text('\n'.join(rows)+'\n')
        return grid_from_raw(path,start,start+90*NS,timestamp_ns)

    def test_raw_future_changes_do_not_rewrite_past(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);a,_=self.fixture(p);b,_=self.fixture(p,future_change=True)
            self.assertEqual(a[:80],b[:80]);self.assertFalse(a[59]['valid']);self.assertTrue(a[65]['valid'])

    def test_repeated_stale_depth_never_completes_warmup(self):
        with tempfile.TemporaryDirectory() as tmp:
            grid,_=self.fixture(Path(tmp),gap=True)
            self.assertFalse(any(p['valid'] for p in grid))
