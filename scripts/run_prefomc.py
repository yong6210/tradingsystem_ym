"""E045 fixed pre-FOMC calendar economics and conditional minimum-contract accounts."""
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
from app.research.diagnostics.funding_tail import decision_map
from app.research.diagnostics.prefomc import calendar,attach_inputs,stats
from app.research.diagnostics.minimum_contract import size_order
from scripts.run_minimum_contract_diagnostic import verify_minimum_fills
from decimal import ROUND_CEILING,ROUND_FLOOR
from app.research.diagnostics.session_reversal import event_returns
from app.research.diagnostics.minimum_contract_engine import simulate
from app.research.diagnostics.operating_audit import verify_run,near
from app.research.diagnostics.review_metrics import calendar_risk
from app.research.diagnostics.concentration import concentration
from scripts.run_direction_controls import save,load,digest,verify_daily
from scripts.run_time_exit_policy import START,END,check_hashes
from scripts.run_weekly_momentum import verify_event_costs
from scripts.run_intrabar_risk_paths import verify_stops
from scripts.run_btcusdc_comparison import annual


def account_stage(out,bundle,rows,settings):
    models={name:[r for r in rows if r['model']==name] for name in ('FOMC','PRIOR_WEEK')}
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
                    audit['minimum_fills']=verify_minimum_fills(result,commands,bundle.trade,cost,risk)
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


def verify_calendar(folder,rows):
    receipts=load(folder/'receipts.json')
    for r in receipts:
        if digest(folder/r['filename'])!=r['sha256']:raise ValueError('calendar source changed')
    a=(folder/'monetary20230623a.htm.txt').read_text()
    b=(folder/'monetary20240809a.htm.txt').read_text()
    current=(folder/'fomccalendars.htm').read_text()
    for token in ('September 17-18','November 6-7','December 17-18'):
        if token not in a:raise ValueError('2024 early calendar mismatch')
    years={2025:b.split('For 2025:')[1].split('For 2026:')[0],2026:b.split('For 2026:')[1]}
    for r in rows:
        t=pd.Timestamp(r['meeting']);stamp=t.strftime('%Y%m%d')
        if t.year!=2024 and t.strftime('%B ')+str(t.day) not in years[t.year]:raise ValueError('early calendar missing date')
        if 'monetary'+stamp+'a.htm' not in current:raise ValueError('actual statement date mismatch')
        if pd.Timestamp(r['known_on'],tz='UTC')>=pd.Timestamp(r['entry_time']):raise ValueError('late schedule')
    if 'statement at 2 p.m. Eastern Time on the second day' not in b:raise ValueError('unverified release clock')
    return dict(status='PASS_EARLY_ANNOUNCEMENTS_AND_ACTUAL_STATEMENT_DATES',meetings=16,rows=len(rows))


def verify_inputs(minutes,rows):
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
    for r in rows:
        i,j=r['entry_minute'],r['exit_minute'];boundary=int(epoch[i])-1
        completed=(boundary//240)*240
        if abs(float(lookup[completed])-r['atr'])>1e-6:raise ValueError('independent completed ATR')
        if r['decision_close']!=float(close[i-2]):raise ValueError('decision close lookahead')
        if pd.Timestamp(r['feature_time']).timestamp()//60!=completed or int(epoch[j]-epoch[i])!=1438:
            raise ValueError('input timing mismatch')
    return dict(status='PASS_DECIMAL_ATR_FROM_COMPLETE_MINUTE_BLOCKS_AND_INPUT_LAG',rows=len(rows))


def preflight(minutes,rows,settings):
    risk=Risk(**settings['risk']);result={}
    for name,params in settings['costs'].items():
        cost=Costs(**params);checked=[]
        for r in rows:
            price=float(minutes.o.iloc[r['entry_minute']])
            p=size_order(price,r['decision_close'],r['atr'],1,1000,False,cost,risk)
            tick,step=D(str(cost.tick)),D(str(risk.step));fee=D(str(cost.fee_bps))/10000;slip=D(str(cost.slippage_bps))/10000
            entry=(D(str(price))*(1+slip)/tick).to_integral_value(rounding=ROUND_CEILING)*tick
            quantity=(max(D('.001'),D(50)/entry)/step).to_integral_value(rounding=ROUND_CEILING)*step
            stop=((D(str(r['decision_close']))-3*D(str(r['atr'])))/tick).to_integral_value(rounding=ROUND_FLOOR)*tick
            stop_fill=(stop*(1-slip)/tick).to_integral_value(rounding=ROUND_FLOOR)*tick
            loss=quantity*(entry-stop_fill+(entry+stop_fill)*fee)
            approved=stop>0 and entry>stop and loss<=5 and quantity*entry<=1000
            if p['approved']!=approved:raise ValueError('independent initial minimum-contract eligibility')
            if approved:
                near(p['quantity'],float(quantity));near(p['planned_loss'],float(loss))
            checked.append(dict(meeting=r['meeting'],model=r['model'],approved=approved,
                minimum_quantity=str(quantity),planned_stop_loss_usdc=str(loss),proposal=p))
        result[name]=dict(status='PASS_DECIMAL_INITIAL_CAPITAL_PREFLIGHT',rows=checked,
            approved={m:sum(r['approved'] for r in checked if r['model']==m) for m in ('FOMC','PRIOR_WEEK')})
    return result


def main(out):
    prior=ROOT/'reports/validation/e044_minimum_contract_20260919';old=load(prior/'registration.json')
    sources=dict(old['source_hashes'])
    for name in ['app/research/diagnostics/prefomc.py','scripts/run_prefomc.py','tests/test_prefomc.py',
                 'docs/research/experiments/E045_PREFOMC_CALENDAR.md']:
        sources[name]=digest(ROOT/name)
    check_hashes(sources)
    for name,h in load(prior/'verification.json')['artifacts'].items():
        if digest(prior/name)!=h:raise ValueError('changed E044 artifact '+name)
    calendar_dir=ROOT/'reports/validation/e045_calendar_sources_20260919'
    input_hashes={str(p.relative_to(ROOT)):digest(p) for p in calendar_dir.iterdir() if p.is_file()}
    settings=dict(start=START,end=END,costs=old['settings']['costs'],risk=old['settings']['risk'],
        sizing='MINIMUM_LEGAL_QUANTITY_ONLY',models=['FOMC','PRIOR_WEEK'],monthly_cost_scenarios=[0,2],
        paths=['OHLC','OLHC'],hold_minutes=1438,paired_bootstrap_block_events=4,bootstrap_repetitions=2000,
        seed=19092026,source_data_reused=True,actual_operating_cost_unknown=True)
    save(out/'registration.json',dict(registered_at=datetime.now(timezone.utc).isoformat(),settings=settings,
        source_hashes=sources,input_hashes=input_hashes,prior_verification_sha256=digest(prior/'verification.json'),actual_orders=0))
    for name in sources:
        p=out/'source_snapshot'/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((ROOT/name).read_bytes())
    with (out/'tests.log').open('x') as f:
        tested=unittest.TextTestRunner(stream=f,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromNames(
            ['tests.test_prefomc','tests.test_minimum_contract','tests.test_operating_engine']))
    if not tested.wasSuccessful() or tested.skipped:raise ValueError('focused tests failed')
    rows=calendar();calendar_audit=verify_calendar(calendar_dir,rows);save(out/'calendar.json',rows)
    save(out/'calendar_verification.json',calendar_audit)
    print('Loading verified prices after calendar/rule registration.',flush=True)
    bundle=load_public_bundle(ROOT,ROOT/'data/historical/btcusdc_public_20260917');bundle.require_complete_window(START,END)
    rows=attach_inputs(bundle.trade,frame_features(bundle.trade,240),rows)
    input_audit=verify_inputs(bundle.trade,rows);save(out/'signals.json',rows);save(out/'input_verification.json',input_audit)
    availability=preflight(bundle.trade,rows,settings);save(out/'minimum_contract_preflight.json',availability)
    results={};cost_checks={}
    for scenario,params in settings['costs'].items():
        cost=Costs(**params);events={}
        for model in settings['models']:
            selected=[r for r in rows if r['model']==model]
            events[model]=event_returns(bundle.trade,selected,bundle.funding,cost,'LONG')
            save(out/(scenario+'_'+model+'_events.json'),events[model])
            cost_checks[scenario+'_'+model]=verify_event_costs(bundle.trade,selected,events[model],bundle.funding,cost,'LONG')
        results[scenario]=stats(events['FOMC'],events['PRIOR_WEEK'])
        print('Event economics',scenario,json.dumps(results[scenario]),flush=True)
    gate=all(v['mean_net_bps']>0 and v['paired_excess_bps']>0 and availability[c]['approved']['FOMC']>0 for c,v in results.items())
    save(out/'event_summary.json',dict(results=results,account_gate_pass=gate,account_returns=False))
    runs,checks=account_stage(out,bundle,rows,settings) if gate else ({},{})
    save(out/'summary.json',dict(settings=settings,event_economics=results,account_gate_pass=gate,runs=runs,
        account_runs=len(runs),availability={c:v['approved'] for c,v in availability.items()},
        account_drawdown_measured=bool(runs),operating_cost_integrated=bool(runs),actual_orders=0,
        future_profit_verified=False,strategy_adopted=False))
    check_hashes(sources);check_hashes(input_hashes)
    save(out/'verification.json',dict(status='PASS_SCOPED_CALENDAR_INPUT_AND_COST_CHECKS',focused_tests=tested.testsRun,
        calendar=calendar_audit,inputs=input_audit,event_costs=cost_checks,accounts=checks,
        source_hashes_unchanged=len(sources),artifacts={str(p.relative_to(out)):digest(p) for p in out.rglob('*') if p.is_file()}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    try:main(args.output)
    except Exception as e:save(args.output/'failure.json',dict(type=type(e).__name__,reason=str(e)));raise
