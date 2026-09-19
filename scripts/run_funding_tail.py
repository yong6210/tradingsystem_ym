"""E043 registered funding-tail economics and conditional operating-account stage."""
import argparse
from datetime import datetime,timezone
from decimal import Decimal as D
import json
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import numpy as np
import pandas as pd
from app.research.baseline.account import Costs
from app.research.baseline.risk import Risk
from app.research.data.btcusdc import load_public_bundle
from app.research.multistrategy_audit import frame_features
from app.research.diagnostics.funding_tail import signals,verify_ranks,event_stats,decision_map
from app.research.diagnostics.session_reversal import event_returns
from app.research.diagnostics.operating_engine import simulate
from app.research.diagnostics.operating_audit import verify_run,near
from app.research.diagnostics.review_metrics import calendar_risk
from app.research.diagnostics.concentration import concentration
from scripts.run_direction_controls import save,load,digest,verify_daily
from scripts.run_time_exit_policy import START,END,check_hashes
from scripts.run_weekly_momentum import verify_event_costs
from scripts.run_intrabar_risk_paths import verify_stops
from scripts.run_btcusdc_comparison import annual


def verify_atr(minutes,rows):
    epoch=minutes.index.asi8//60_000_000_000
    _,starts,counts=np.unique(epoch//240,return_index=True,return_counts=True)
    previous=None;atr=None;lookup={};n=0
    high,low,close=(minutes[k].to_numpy() for k in ('h','l','c'))
    for begin,count in zip(starts,counts):
        if count!=240:continue
        stop=int(begin+count);n+=1
        h,l,c=(D(str(v)) for v in (high[begin:stop].max(),low[begin:stop].min(),close[stop-1]))
        tr=h-l if previous is None else max(h-l,abs(h-previous),abs(l-previous))
        atr=tr if atr is None else (13*atr+tr)/14
        if n>=14:lookup[int(epoch[stop-1])+1]=atr
        previous=c
    for row in rows:
        b=int(pd.Timestamp(row['boundary']).timestamp()//60)
        if abs(float(lookup[b])-row['atr'])>1e-6:raise ValueError('independent ATR mismatch')
        if row['decision_close']!=float(minutes.c.iloc[row['entry_minute']-3]):raise ValueError('decision close mismatch')
    return dict(status='PASS_DIRECT_MINUTE_BLOCKS_DECIMAL_ATR',rows=len(rows))


def account_stage(out,bundle,rows,settings):
    features=frame_features(bundle.trade,240)
    for row in rows:
        b=pd.Timestamp(row['boundary']);row['atr']=float(features.at[b,'atr'])
        row['decision_close']=float(bundle.trade.at[b-pd.Timedelta(minutes=1),'c'])
    save(out/'account_signal_verification.json',verify_atr(bundle.trade,rows))
    models={'TAIL':rows,'LONG00':[dict(r,side=1) for r in rows if r['hour']==0]}
    risk=Risk(**settings['risk']);months=pd.date_range(START,END,freq='MS',inclusive='left')
    indices=bundle.trade.index.get_indexer(months)
    if len(months)!=24 or min(indices)<0:raise ValueError('operating calendar')
    funding={e['fundingTime']:e for e in bundle.funding};runs={};checks={}
    for model,signal_rows in models.items():
        commands=decision_map(signal_rows);save(out/(model+'_decisions.json'),commands)
        allowed={r['entry_minute']:r for r in signal_rows if r['side']}
        for op in (0,2):
            debits={int(i):op for i in indices}
            for scenario,params in settings['costs'].items():
                cost=Costs(**params)
                for path in ('OHLC','OLHC'):
                    key=f'{scenario}_{model}_op{op}_{path}';print('Account',key,flush=True)
                    result=simulate(bundle.trade,commands,pd.Timestamp(START),pd.Timestamp(END),cost,risk,
                                    funding=bundle.funding,path=path,operating_debits=debits)
                    m=result['metrics'];m['annual']=annual(result['daily'],1000)
                    folder=out/key;folder.mkdir()
                    for name in ('events','trades','daily','rejections','path_stops'):
                        with (folder/(name+'.jsonl')).open('x') as f:
                            for row in result[name]:f.write(json.dumps(row,allow_nan=False)+'\n')
                    save(folder/'metrics.json',m)
                    audit=verify_run(folder,m,funding);audit['daily']=verify_daily(result,bundle.trade)
                    audit['stops']=verify_stops(result,bundle.trade,path,cost,risk)
                    operating=[dict(time=e['time'],amount=e['amount']) for e in result['events'] if e['kind']=='operating']
                    expected=[dict(time=t.isoformat(),amount=op) for t in months] if op else []
                    if operating!=expected:raise ValueError('operating calendar mismatch')
                    near(m['operating_cost'],op*24)
                    for t in result['trades']:
                        if t['entry_minute'] not in allowed or t['side']!=1:raise ValueError('unregistered entry')
                        if t['exit_minute']>allowed[t['entry_minute']]['exit_minute']:raise ValueError('late fixed exit')
                    if len({t['entry_minute'] for t in result['trades']})!=len(result['trades']):raise ValueError('same-window reentry')
                    monthly={};previous=1000.
                    for day in result['daily']:
                        label=day['day'][:7];monthly[label]=monthly.get(label,0)+day['equity']-previous;previous=day['equity']
                    net=m['final_equity']-1000;near(sum(monthly.values()),net)
                    detail=dict(calendar_risk=calendar_risk(result['daily']),monthly_net_after_operations=monthly,
                        net_usdc=net,trading_net_before_operations=sum(t['net_pnl'] for t in result['trades']),
                        concentration=concentration([dict(id=i,net=t['net_pnl']) for i,t in enumerate(result['trades'])],(1,5)) if result['trades'] else None,
                        necessary_conditions_pass=net>0 and m['max_drawdown_pct']<=5)
                    save(folder/'diagnostics.json',detail);save(folder/'verification.json',audit)
                    runs[key]=dict(metrics=m,diagnostics=detail);checks[key]=audit
                    print(json.dumps(dict(run=key,net=net,dd=m['max_drawdown_pct'],cycles=m['cycles'])),flush=True)
    return runs,checks


def main(out):
    prior=ROOT/'reports/validation/e042_extended_risk_cost_alignment_20260919'
    previous=load(prior/'registration.json');sources=dict(previous['source_hashes'])
    for name in ['app/research/diagnostics/funding_tail.py','scripts/run_funding_tail.py','tests/test_funding_tail.py',
                 'docs/research/experiments/E043_FUNDING_TAIL_REBOUND.md']:
        sources[name]=digest(ROOT/name)
    check_hashes(sources)
    for name,h in load(prior/'verification.json')['artifacts'].items():
        if digest(prior/name)!=h:raise ValueError('changed E042 artifact '+name)
    risk={**previous['settings']['risk']['S09F'],'maximum_hold_minutes':1440}
    settings=dict(start=START,end=END,window_settlements=540,tail_midrank_max=.1,entry_delay_minutes=2,
        hold_minutes=1439,overlap_policy='SKIP_UNTIL_PLANNED_EXIT',costs=previous['settings']['costs'],risk=risk,
        conditional_account_models=['TAIL','LONG00'],conditional_account_runs=16,monthly_operating_costs=[0,2],paths=['OHLC','OLHC'],
        source_market='BTCUSDC',literature_market='BTCUSDT_FUNDING_AND_SPOT',new_market_requests=0)
    save(out/'registration.json',dict(registered_at=datetime.now(timezone.utc).isoformat(),settings=settings,
        source_hashes=sources,prior_verification_sha256=digest(prior/'verification.json'),source_data_reused=True,actual_orders=0))
    for name in sources:
        p=out/'source_snapshot'/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((ROOT/name).read_bytes())
    with (out/'tests.log').open('x') as f:
        tested=unittest.TextTestRunner(stream=f,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromNames(
            ['tests.test_funding_tail','tests.test_operating_engine','tests.test_intrabar_risk_paths']))
    if not tested.wasSuccessful() or tested.skipped:raise ValueError('focused tests failed')
    print('Loading verified BTCUSDC price and funding sources.',flush=True)
    bundle=load_public_bundle(ROOT,ROOT/'data/historical/btcusdc_public_20260917');bundle.require_complete_window(START,END)
    rows=signals(bundle.funding,START,END)
    if len(rows)!=2187:raise ValueError('incomplete full-day event calendar')
    audit=verify_ranks(bundle.funding,rows)
    for row in rows:
        i,j=[int(bundle.trade.index.get_indexer([pd.Timestamp(row[k])])[0]) for k in ('entry_time','exit_time')]
        if i<0 or j-i!=1439:raise ValueError('wrong event price boundaries')
        row.update(entry_minute=i,exit_minute=j)
    save(out/'signals.json',rows);save(out/'signal_verification.json',audit)
    results={};cost_checks={}
    for scenario,params in settings['costs'].items():
        cost=Costs(**params)
        all_long=event_returns(bundle.trade,rows,bundle.funding,cost,'LONG')
        tail=event_returns(bundle.trade,rows,bundle.funding,cost,'REVERSAL')
        save(out/(scenario+'_unconditional_events.json'),all_long);save(out/(scenario+'_tail_events.json'),tail)
        cost_checks[scenario+'_all']=verify_event_costs(bundle.trade,rows,all_long,bundle.funding,cost,'LONG')
        cost_checks[scenario+'_tail']=verify_event_costs(bundle.trade,rows,tail,bundle.funding,cost,'MOMENTUM')
        results[scenario]=event_stats(rows,all_long,tail)
        print('Event economics',scenario,json.dumps(results[scenario]),flush=True)
    gate=all(v['active_events']>0 and v['mean_net_bps']>0 and v['matched_excess_bps']>0 for v in results.values())
    save(out/'event_summary.json',dict(results=results,gate_pass=gate,raw_tail_events=sum(r['tail'] for r in rows),
        overlap_suppressed=sum(r['overlap_suppressed'] for r in rows),full_event_calendar=len(rows),account_returns=False))
    runs,checks=account_stage(out,bundle,rows,settings) if gate else ({},{})
    screening={str(op):{m:all(runs[f'{c}_{m}_op{op}_{p}']['diagnostics']['necessary_conditions_pass']
        for c in settings['costs'] for p in settings['paths']) for m in settings['conditional_account_models']} for op in (0,2)} if gate else {}
    save(out/'summary.json',dict(settings=settings,event_economics=results,account_gate_pass=gate,runs=runs,screening=screening,
        account_runs=len(runs),account_drawdown_measured=bool(runs),operating_cost_integrated=bool(runs),
        operating_assumption_confirmed_by_user=False,actual_orders=0,source_data_reused=True,future_profit_verified=False,strategy_adopted=False))
    check_hashes(sources)
    save(out/'verification.json',dict(status='PASS_SCOPED_CAUSAL_SIGNAL_AND_COST_ARITHMETIC',focused_tests=tested.testsRun,
        signal_check=audit,event_cost_checks=cost_checks,account_checks=checks,source_hashes_unchanged=len(sources),
        artifacts={str(p.relative_to(out)):digest(p) for p in out.rglob('*') if p.is_file()}))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=False)
    try:main(a.output)
    except Exception as e:save(a.output/'failure.json',dict(type=type(e).__name__,reason=str(e)));raise
