#!/usr/bin/env python3
"""Fixed, unlevered BTC inventory-rotation experiment; not the existing v6 strategy."""
from __future__ import annotations
import argparse, hashlib, json, math, sys
from dataclasses import dataclass, asdict
from datetime import UTC, datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.run_market_state_rotation_v6_backtest import FeatureSet, _load_local_bars, _map_closed_indices

@dataclass
class Lot:
    qty: float
    cost: float  # Total cash paid, including entry fee.
    entry: float
    index: int

class Ledger:
    def __init__(self, initial=10000.0):
        self.initial=initial; self.cash=initial; self.lots=[]; self.realized=0.0; self.fees=0.0
    @property
    def qty(self): return sum(x.qty for x in self.lots)
    def equity(self,price): return self.cash+self.qty*price
    def buy(self,price,budget,fee,index):
        budget=min(budget,self.cash)
        if budget<=1e-8:return False
        qty=budget/(price*(1+fee)); charge=qty*price*fee
        self.cash-=budget;self.fees+=charge;self.lots.append(Lot(qty,budget,price,index));return True
    def sell(self,index,price,fee):
        lot=self.lots.pop(index);charge=lot.qty*price*fee; proceeds=lot.qty*price-charge
        self.cash+=proceeds;self.fees+=charge;self.realized+=proceeds-lot.cost
    def check(self,price):
        unrealized=sum(l.qty*price-l.cost for l in self.lots)
        assert self.cash>=-1e-7 and self.qty>=0
        assert math.isclose(self.equity(price)-self.initial,self.realized+unrealized,abs_tol=1e-6)

CONFIGS={'rotation_15m':('15m',288), 'rotation_1h':('1h',864), 'rotation_4h':('4h',2016)}

def simulate(bars,features,maps,start,end,name,cost_bps=5):
    account=Ledger(); fee=cost_bps/10000;events=[];curve=[];monthly={};peak=10000.;maxdd=0.;maxlots=0;maxexposure=0.;lastsignal=-1;lastbuy=None;lastsell=None;cooldown=-1;partial=0;reentries=0;scaleins=0;holding_bars=0;reloads=0;trim_since_add=False
    indices=[i for i,b in enumerate(bars) if start<=b.ts<end]
    for i in indices:
        b=bars[i]; before=account.equity(b.o)
        if name=='buy_hold':
            if i==indices[0]: account.buy(b.o,account.cash,fee,i);events.append({'ts':b.ts.isoformat(),'action':'buy','reason':'buy_hold','price':b.o})
        else:
            interval,maxhold=CONFIGS[name];f=features[interval];j=maps[interval][i];h=maps['4h'][i];trend=features['4h']
            if j>=200 and h>=200 and j!=lastsignal:
                lastsignal=j;atr=f.atr[j];close=f.c[j];eligible=trend.ema(50)[h]>=trend.ema(200)[h]
                def sell(k,reason):
                    nonlocal lastsell,partial,trim_since_add
                    if reason=='rebound_trim':
                        trim_since_add=True
                        if len(account.lots)>1:partial+=1
                    qty=account.lots[k].qty;account.sell(k,b.o,fee);lastsell=b.o
                    events.append({'ts':b.ts.isoformat(),'action':'sell','reason':reason,'price':b.o,'qty':qty})
                if account.lots:
                    avg=sum(l.qty*l.entry for l in account.lots)/account.qty
                    if not eligible or close<=avg-3*atr or i-min(l.index for l in account.lots)>=maxhold:
                        reason='trend_exit' if not eligible else 'stop' if close<=avg-3*atr else 'time_exit'
                        while account.lots:sell(len(account.lots)-1,reason)
                        cooldown=i+12;lastbuy=None
                    else:
                        profitable=[k for k,l in enumerate(account.lots) if close>=l.entry+max(1.5*atr, l.entry*fee*3) and b.o*(1-fee)*l.qty>l.cost]
                        if profitable:sell(profitable[-1],'rebound_trim')
                        elif len(account.lots)<4 and lastbuy is not None and close<=lastbuy-atr and close<=f.ema(20)[j]-.5*atr:
                            scaleins+=1
                            if trim_since_add:reloads+=1
                            trim_since_add=False
                            account.buy(b.o,account.equity(b.o)/4,fee,i);lastbuy=b.o
                            events.append({'ts':b.ts.isoformat(),'action':'buy','reason':'scale_in','price':b.o})
                elif eligible and i>cooldown and close<=f.ema(20)[j]-.5*atr and (lastsell is None or close<=lastsell-atr):
                    if lastsell is not None:reentries+=1
                    trim_since_add=False
                    account.buy(b.o,account.equity(b.o)/4,fee,i);lastbuy=b.o
                    events.append({'ts':b.ts.isoformat(),'action':'buy','reason':'reentry' if lastsell is not None else 'initial','price':b.o})
        holding_bars+=int(bool(account.lots))
        maxlots=max(maxlots,len(account.lots));maxexposure=max(maxexposure,account.qty*b.o/max(account.equity(b.o),1e-12))
        # Low is observable ex post and is used for drawdown only, never for order decisions.
        loweq=account.equity(b.l);maxdd=max(maxdd,1-loweq/peak)
        if i==indices[-1]:
            while account.lots:
                qty=account.lots[-1].qty;account.sell(len(account.lots)-1,b.c,fee)
                events.append({'ts':b.ts.isoformat(),'action':'sell','reason':'final_liquidation','price':b.c,'qty':qty})
        eq=account.equity(b.c);maxdd=max(maxdd,1-eq/peak);peak=max(peak,eq);account.check(b.c)
        month=b.ts.strftime('%Y-%m');monthly.setdefault(month,{'start':curve[-1]['equity'] if curve else 10000.,'end':eq})['end']=eq
        if i==indices[-1] or (i+1<len(bars) and bars[i+1].ts.date()!=b.ts.date()):curve.append({'date':b.ts.isoformat(),'equity':eq})
    returns={m:v['end']/v['start']-1 for m,v in monthly.items()}
    assert math.isclose(math.prod(1+r for r in returns.values()),account.cash/10000,abs_tol=1e-8)
    assert maxlots<=4 if name!='buy_hold' else maxlots<=1
    return {'strategy':name,'cost_bps':cost_bps,'start':start.isoformat(),'end_exclusive':end.isoformat(),'return_pct':(account.cash/10000-1)*100,'drawdown_pct':maxdd*100,'realized_pnl':account.realized,'fees_paid':account.fees,'max_lots':maxlots,'max_exposure':maxexposure,'scale_ins':scaleins,'partial_sales':partial,'rebound_sales':sum(e['reason']=='rebound_trim' for e in events),'reloads_while_holding':reloads,'holding_bar_pct':holding_bars/len(indices)*100,'reentries_after_flat':reentries,'order_count':len(events),'monthly_returns':returns,'daily_equity':curve,'events':events}

def main():
    p=argparse.ArgumentParser();p.add_argument('--output-dir',type=Path,required=True);a=p.parse_args();a.output_dir.mkdir(parents=True,exist_ok=True)
    data=ROOT/'data/historical/btcusdt_2025_2026_verified';bars=_load_local_bars(data,'BTCUSDT','5m')
    fs={k:FeatureSet(_load_local_bars(data,'BTCUSDT',k)) for k in ['15m','1h','4h']};maps={k:_map_closed_indices(bars,f.bars,k) for k,f in fs.items()}
    periods={'common_full':('2025-02-04','2026-09-01'),'2025':('2025-02-04','2026-01-01'),'2026':('2026-01-01','2026-09-01'),'recent':('2026-06-06','2026-09-01')}
    runs=[]
    for period,(start,end) in periods.items():
        start=datetime.fromisoformat(start).replace(tzinfo=UTC);end=datetime.fromisoformat(end).replace(tzinfo=UTC)
        cases=[(n,5) for n in [*CONFIGS,'buy_hold']]+([(n,9) for n in CONFIGS] if period=='common_full' else [])
        for name,cost in cases:
            r=simulate(bars,fs,maps,start,end,name,cost);r['period']=period;runs.append(r)
            print(period,name,cost,round(r['return_pct'],3),round(r['drawdown_pct'],3),r['max_lots'],r['scale_ins'],r['partial_sales'],flush=True)
    payload={'model':'new fixed unlevered spot inventory reference, not v6','initial_usdt':10000,'predeclared_configs':CONFIGS,'engine_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'manifest_sha256':hashlib.sha256((data/'manifest.json').read_bytes()).hexdigest(),'runs':runs}
    (a.output_dir/'results.json').write_text(json.dumps(payload,indent=2))
if __name__=='__main__':main()
