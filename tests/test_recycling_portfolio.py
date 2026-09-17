import unittest
import numpy as np
from tests.test_multistrategy_research import market, one_signal
from app.research.recycling_portfolio import Sleeve, simulate
from app.research.multistrategy import Costs

class RecyclingTests(unittest.TestCase):
    def run_case(self,f,s,**kwargs):
        specs=kwargs.pop('sleeves',[Sleeve('a')])
        sets=kwargs.pop('sets',{'a':s})
        return simulate(f,sets,np.full(len(f),2),'2026-01-01','2026-01-02',specs,**kwargs)

    def rotation(self,n=20):
        f=market(n);f['v']=100000.
        s=one_signal(n);s.update(rotation=True,stop_atr=4.,target_atr=1.5,max_hold=100)
        for i in range(1,n):
            if i%2:
                f.loc[f.index[i],['o','h','l','c']]=[101.,103.,100.8,102.]
            else:
                f.loc[f.index[i],['o','h','l','c']]=[100.3,100.5,99.8,100.2]
                s['decision'][i]=True;s['atr'][i]=1.;s['close'][i]=100.2
        return f,s

    def test_recycling_replenishes_sold_inventory_without_widening_stop(self):
        f,s=self.rotation()
        r=self.run_case(f,s)
        cycle=r['sleeves']['a']['cycles'][0]
        self.assertGreater(cycle['total_bought'],3*cycle['seed'])
        stops={e['stop'] for e in r['events']}
        self.assertEqual(len(stops),1)
        self.assertLessEqual(max(e['remaining'] for e in r['events']),3*cycle['seed']+1e-8)
        limited=self.run_case(f,s,sleeves=[Sleeve('a',recycling=False)])
        cycle=limited['sleeves']['a']['cycles'][0]
        self.assertLessEqual(cycle['total_bought'],3*cycle['seed']+1e-8)

    def test_no_add_preserves_seed(self):
        f,s=self.rotation()
        r=self.run_case(f,s,sleeves=[Sleeve('a',additions=False)])
        self.assertEqual(sum(e['action']=='maker_add' for e in r['events']),1)
        self.assertAlmostEqual(r['sleeves']['a']['cycles'][0]['seed'],r['events'][0]['qty'])

    def test_profit_slot_does_not_block_add_and_no_same_bar_rebound_profit(self):
        f,s=self.rotation(6)
        f.loc[f.index[2],['o','h','l','c']]=[100.3,104.,99.8,100.2]
        r=self.run_case(f,s)
        actions=[e['action'] for e in r['events'] if e['time']==f.index[2].isoformat()]
        self.assertIn('maker_add',actions)
        self.assertNotIn('maker_reduce',actions)

    def test_stop_precedes_profit_and_add_precedes_stop(self):
        f,s=self.rotation(6)
        f.loc[f.index[2],['o','h','l','c']]=[100.3,104.,94.,99.]
        r=self.run_case(f,s)
        actions=[e['action'] for e in r['events'] if e['time']==f.index[2].isoformat()]
        self.assertEqual(actions,['maker_add','market_stop'])

    def test_short_recycling_and_stop_ordering(self):
        f,s=self.rotation(6)
        f.loc[f.index[2],['o','h','l','c']]=[100.3,104.,94.,99.]
        f[['o','c']]=200-f[['o','c']]
        f['h'],f['l']=200-f['l'].copy(),200-f['h'].copy()
        s['side']*=-1;s['direction']*=-1
        s['close'][s['decision']]=200-s['close'][s['decision']]
        r=self.run_case(f,s)
        actions=[e['action'] for e in r['events'] if e['time']==f.index[2].isoformat()]
        self.assertEqual(actions,['maker_add','market_stop'])
        self.assertTrue(all(e['side']==-1 for e in r['events']))

    def test_market_entry_pays_fee_and_slippage(self):
        f=market();s=one_signal()
        r=self.run_case(f,s,sleeves=[Sleeve('a',entry_mode='market')])
        e=r['events'][0]
        self.assertEqual(e['action'],'market_add');self.assertAlmostEqual(e['price'],100*1.0002)
        self.assertLess(e['balance'],10000.)
        self.assertGreater(r['sleeves']['a']['fees'],0.)

    def test_shared_volume_cap_and_capital_conservation(self):
        f=market();f['v']=1.;s=one_signal()
        r=self.run_case(f,s,sets={'a':s,'b':s},sleeves=[Sleeve('a',.5),Sleeve('b',.5)])
        times={e['time'] for e in r['events']}
        for time in times:
            volume=sum(e['qty'] for e in r['events'] if e['time']==time and e['action'].startswith('maker_'))
            self.assertLessEqual(volume,.001+1e-10)
        self.assertEqual(sum(x['initial'] for x in r['sleeves'].values()),10000)
        self.assertLessEqual(r['gross_entry_exposure_peak'],1+1e-8)

    def test_sleeve_does_not_occupy_another_strategy_position(self):
        f=market();f['v']=100000.;s=one_signal()
        r=self.run_case(f,s,sets={'a':s,'b':s},sleeves=[Sleeve('a',.5),Sleeve('b',.5)])
        self.assertEqual({e['model'] for e in r['events'] if e['action']=='maker_add'},{'a','b'})

    def test_prefix_invariance(self):
        f,s=self.rotation(20);changed=f.copy();changed.iloc[12:,:4]*=1.1
        a=self.run_case(f,s);b=self.run_case(changed,s)
        cutoff=f.index[12].isoformat()
        self.assertEqual([e for e in a['events'] if e['time']<cutoff],[e for e in b['events'] if e['time']<cutoff])

    def test_invalid_allocation_rejected(self):
        with self.assertRaises(ValueError):self.run_case(market(),one_signal(),sleeves=[Sleeve('a',.5)])

if __name__=='__main__':unittest.main()
