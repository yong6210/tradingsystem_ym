#!/usr/bin/env python3
"""Video-inspired scenario inventory comparison, not a verified trader replica."""
from __future__ import annotations
import argparse
from collections import Counter
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
import hashlib
import json
import math
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.research.scenario_inventory import PerpetualAccount, PassiveOrder, passive_fill, addition_capacity, recovery_quantity
from scripts.run_market_state_rotation_v6_backtest import FeatureSet, _load_local_bars, _map_closed_indices


@dataclass(frozen=True)
class Settings:
    mode: str = 'recovery'
    max_exposure: float = 1.
    exchange_leverage: float = 5.  # Research assumption, not user/exchange configuration.
    cycle_risk: float = .02
    initial_exposure: float = .25
    max_additions: int = 3
    max_hold_bars: int = 288
    maker_bps: float = 0.
    taker_bps: float = 5.
    market_slippage_bps: float = 2.
    adverse_funding_bps_8h: float = 0.
    maintenance_rate: float = .005
    liquidation_fee_bps: float = 50.
    fill_fraction: float = 1.
    penetration_bps: float = 1.
    ttl: int = 3


def run(bars, signal, higher, mapping, hmap, start, end, cfg):
    account=PerpetualAccount();pending=None;counts=Counter();events=[];daily=[];monthly={}
    peak=account.initial;dd=0.;observed_exposure=0.;entry_exposure=0.;held=0
    lastsignal=-1;cycle_balance=account.initial;stop=0.;last_entry=0.;last_trade=-100;opened=0;adds=0;cooldown=-1;initial_qty=0.;failure_cut=False
    previous_equity=account.initial;day_start=account.initial;previous_day=None
    ef=signal.ema(20);hf=higher.ema(20);hs=higher.ema(50);lows=signal.rolling_low_prev(24);highs=signal.rolling_high_prev(24)
    indices=[i for i,b in enumerate(bars) if start<=b.ts<end]

    def record(i,action,reason,price,qty):
        events.append({'ts':bars[i].ts.isoformat(),'action':action,'reason':reason,'price':price,'qty':qty,'side':account.side,'remaining_qty':account.qty,'average':account.average,'balance':account.balance,'equity':account.equity(price),'cycle_pnl':account.equity(price)-cycle_balance})

    def market_exit(i,reason):
        nonlocal pending,cooldown
        pending=None
        if account.qty:
            q=account.qty;price=bars[i].o*(1-account.side*cfg.market_slippage_bps/10000)
            account.reduce(q,price,cfg.taker_bps/10000);counts[reason]+=1;record(i,'market_close',reason,price,q)
        cooldown=i+12

    def adverse_risk(i):
        nonlocal pending,cooldown,dd
        if not account.qty:return
        b=bars[i];side=account.side
        liq=account.liquidation_price(cfg.maintenance_rate)
        threshold=max(stop,liq) if side==1 else min(stop,liq)
        adverse=b.l if side==1 else b.h
        # Record only price movement up to the modeled exit, not the later low/high.
        reached=adverse<=threshold if side==1 else adverse>=threshold
        if reached:
            liquidation=liq>=stop if side==1 else liq<=stop
            raw=min(b.o,threshold) if side==1 else max(b.o,threshold)
            price=raw*(1-side*cfg.market_slippage_bps/10000)
            q=account.qty;account.reduce(q,price,(cfg.liquidation_fee_bps if liquidation else cfg.taker_bps)/10000)
            counts['liquidations' if liquidation else 'protective_stops']+=1
            record(i,'market_close','liquidation_proxy' if liquidation else 'protective_stop',price,q)
            pending=None;cooldown=i+12
            dd=max(dd,1-account.balance/peak)
        else:
            dd=max(dd,1-account.equity(adverse)/peak)

    for i in indices:
        b=bars[i];day=b.ts.date()
        if previous_day!=day:day_start=account.equity(b.o);previous_day=day
        if account.qty and b.ts.hour%8==0 and b.ts.minute==0:
            account.funding(b.o,account.side*cfg.adverse_funding_bps_8h/10000)
        j=mapping[i];h=hmap[i]
        direction_now=(1 if hf[h]>=hs[h] else -1) if h>=50 else 0
        if pending and not pending.reduce_only and direction_now and pending.side!=direction_now:
            counts['scenario_order_cancelled']+=1;pending=None
        # All market orders decided at the open precede this bar's fill/price path.
        if account.qty:
            if direction_now and direction_now!=account.side:
                market_exit(i,'scenario_exit')
            elif account.equity(b.o)<day_start*.96:
                market_exit(i,'daily_loss_exit');cooldown=i+288
            elif i-opened>=cfg.max_hold_bars:
                market_exit(i,'time_exit')
        # A gap through the protective level exits before any resting order.
        if account.qty and account.side*(b.o-stop)<=0:
            adverse_risk(i)
        # With ambiguous OHLC ordering, reductions do not precede an adverse stop.
        if account.qty and (pending is None or pending.reduce_only):
            adverse_risk(i)
        if pending:
            order=pending
            qty,status=passive_fill(order,b,i,ttl=cfg.ttl,penetration_bps=cfg.penetration_bps,fill_fraction=cfg.fill_fraction)
            if status in ('expired','post_only_rejected'):
                counts[status]+=1;pending=None
            elif qty>0:
                if order.reduce_only:
                    qty=min(qty,account.qty)
                    if qty:
                        account.reduce(qty,order.price,cfg.maker_bps/10000)
                else:
                    if account.qty==0:
                        cycle_balance=account.balance;opened=i;adds=0;failure_cut=False
                    capacity=addition_capacity(account,order.side,order.price,stop,cycle_balance,max_exposure=cfg.max_exposure,leverage=cfg.exchange_leverage,risk_fraction=cfg.cycle_risk)
                    qty=min(qty,capacity)
                    if qty>1e-10:
                        account.add(order.side,qty,order.price,cfg.maker_bps/10000)
                        last_entry=order.price
                        entry_exposure=max(entry_exposure,account.qty*order.price/account.equity(order.price))
                        if not order.counted:
                            if order.reason=='initial':initial_qty=order.qty
                            else:adds+=1;failure_cut=False
                    else:counts['risk_capacity_block']+=1;pending=None
                if qty>1e-10:
                    order.remaining-=qty;order.fills+=1;last_trade=i
                    if not order.counted:counts[order.reason]+=1;order.counted=True
                    if order.reason=='failed_reaction_reduce':failure_cut=True
                    counts['fills']+=1
                    if order.remaining>1e-10:counts['partial_fill_events']+=1
                    record(i,'reduce' if order.reduce_only else 'add',order.reason,order.price,qty)
                    if order.remaining<=1e-10 or (order.reduce_only and account.qty==0):pending=None
            if not order.reduce_only:adverse_risk(i)
        held+=int(account.qty>0)
        # Decisions use closed higher/15m bars, and new orders cannot fill until i+1.
        if j>=50 and h>=50 and j!=lastsignal and account.balance>0:
            lastsignal=j;atr=signal.atr[j];close=signal.c[j];side=1 if hf[h]>=hs[h] else -1
            if pending is None and i>cooldown:
                if account.qty:
                    direction=account.side
                    cycle_pnl=account.equity(close)-cycle_balance
                    favorable=direction*(close-last_entry)
                    # Recovery near cycle break-even also permits reducing older losing inventory.
                    recovered=(adds>0 and cycle_pnl>=-cycle_balance*.001 and favorable>=.5*atr)
                    if favorable>=atr or recovered:
                        qty=account.qty if cfg.mode=='single' or account.qty<=initial_qty*.5 else account.qty*.5
                        pending=PassiveOrder(-direction,qty,close+direction*.1*atr,i,'rebound_reduce',True)
                    elif not failure_cut and favorable<=-1.25*atr and adds>0:
                        pending=PassiveOrder(-direction,account.qty*.5,close+direction*.1*atr,i,'failed_reaction_reduce',True)
                    elif cfg.mode!='single' and adds<cfg.max_additions and favorable<=-.75*atr and i-last_trade>=3:
                        price=close-direction*.1*atr;target=price+direction*1.5*atr
                        capacity=addition_capacity(account,direction,price,stop,cycle_balance,max_exposure=cfg.max_exposure,leverage=cfg.exchange_leverage,risk_fraction=cfg.cycle_risk)
                        wanted=initial_qty if cfg.mode=='equal' else max(initial_qty*.5,recovery_quantity(account,direction,price,target,cycle_balance,cycle_balance*.0005))
                        if wanted<=capacity and wanted<=initial_qty*2 and wanted>1e-9:
                            pending=PassiveOrder(direction,wanted,price,i,'recovery_add')
                        else:counts['recovery_unaffordable']+=1
                elif side*(close-ef[j])<=-.35*atr:
                    price=close-side*.1*atr
                    stop=min(lows[j]-.25*atr,price-2*atr) if side==1 else max(highs[j]+.25*atr,price+2*atr)
                    if stop>0:
                        cycle_balance=account.balance
                        capacity=addition_capacity(account,side,price,stop,cycle_balance,max_exposure=cfg.max_exposure,leverage=cfg.exchange_leverage,risk_fraction=cfg.cycle_risk)
                        qty=min(account.balance*cfg.initial_exposure/price,capacity)
                        if qty>1e-9:pending=PassiveOrder(side,qty,price,i,'initial')
                if pending:counts['orders_submitted']+=1
        if account.qty:
            observed_exposure=max(observed_exposure,account.qty*b.c/max(account.equity(b.c),1e-12))
        if i==indices[-1]:
            if pending:counts['end_cancelled']+=1;pending=None
            if account.qty:
                qty=account.qty;price=b.c*(1-account.side*cfg.market_slippage_bps/10000)
                account.reduce(qty,price,cfg.taker_bps/10000);record(i,'market_close','end_of_sample',price,qty);counts['end_of_sample']+=1
        account.check(b.c);equity=account.equity(b.c);dd=max(dd,1-equity/peak);peak=max(peak,equity)
        month=b.ts.strftime('%Y-%m');monthly.setdefault(month,{'start':previous_equity,'end':equity})['end']=equity;previous_equity=equity
        if i==indices[-1] or bars[i+1].ts.date()!=day:daily.append({'date':str(day),'equity':equity})
    returns={m:v['end']/v['start']-1 for m,v in monthly.items()}
    assert math.isclose(math.prod(1+x for x in returns.values()),account.balance/account.initial,abs_tol=1e-7)
    assert entry_exposure<=cfg.max_exposure+1e-7
    return {'settings':asdict(cfg),'return_pct':(account.balance/account.initial-1)*100,'max_drawdown_pct':dd*100,'final_balance':account.balance,'realized_pnl':account.realized,'fees_paid':account.fees,'funding_paid':account.funding_paid,'max_entry_exposure':entry_exposure,'max_marked_exposure':observed_exposure,'holding_pct':held/len(indices)*100,'counts':dict(counts),'monthly_returns':returns,'daily_equity':daily,'events':events}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output-dir',type=Path,required=True);args=parser.parse_args();args.output_dir.mkdir(parents=True,exist_ok=True)
    directory=ROOT/'data/historical/btcusdt_2025_2026_verified'
    bars=_load_local_bars(directory,'BTCUSDT','5m');signal=FeatureSet(_load_local_bars(directory,'BTCUSDT','15m'));higher=FeatureSet(_load_local_bars(directory,'BTCUSDT','4h'))
    mapping=_map_closed_indices(bars,signal.bars,'15m');hmap=_map_closed_indices(bars,higher.bars,'4h')
    periods={'full':('2025-02-04','2026-09-01'),'2025':('2025-02-04','2026-01-01'),'2026':('2026-01-01','2026-09-01'),'recent':('2026-06-06','2026-09-01')}
    cases=[(mode,Settings(mode=mode)) for mode in ['single','equal','recovery']]
    cases += [('recovery_2x',Settings(max_exposure=2.)),('recovery_stress',Settings(fill_fraction=.5,penetration_bps=3.,adverse_funding_bps_8h=1.,taker_bps=7.,market_slippage_bps=5.))]
    manifest={'target':'BTCUSDC perpetual (user plan)','data_proxy':'BTCUSDT user-supplied OHLCV; not actual BTCUSDC execution','strategy':'video-inspired hypothesis, not an exact trader replica','source_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),ROOT/'app/research/scenario_inventory.py',directory/'manifest.json']},'runs':[]}
    # Freeze every setting before any run; no search or winner selection.
    (args.output_dir/'experiment_plan.json').write_text(json.dumps({'periods':periods,'cases':{n:asdict(c) for n,c in cases}},indent=2))
    for period,(s,e) in periods.items():
        for name,cfg in cases:
            result=run(bars,signal,higher,mapping,hmap,datetime.fromisoformat(s).replace(tzinfo=UTC),datetime.fromisoformat(e).replace(tzinfo=UTC),cfg)
            manifest['runs'].append({'period':period,'case':name,'start':s,'end_exclusive':e,'result':result})
            (args.output_dir/'results.json').write_text(json.dumps(manifest,indent=2))
            print(period,name,round(result['return_pct'],3),round(result['max_drawdown_pct'],3),result['counts'],flush=True)
if __name__=='__main__':main()
