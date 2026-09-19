"""E047 delayed OI pressure, registered economic screen and conditional accounts."""
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
from app.research.diagnostics.open_interest_pressure import decisions as decision_map,signals,event_stats,parse_day
import csv
from zipfile import ZipFile
from io import TextIOWrapper
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
    models={'OI':rows,'PRICE':[dict(r,side=r['control_side']) for r in rows]}
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
                        if t['entry_minute'] not in allowed or t['side']!=-1:raise ValueError('unregistered entry')
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
        if pd.Timestamp(r['feature_time']).timestamp()//60!=completed or int(epoch[j]-epoch[i])!=1439:
            raise ValueError('input timing mismatch')
    return dict(status='PASS_DECIMAL_ATR_FROM_COMPLETE_MINUTE_BLOCKS_AND_INPUT_LAG',rows=len(rows))


def load_oi(folder):
    manifest=load(folder/'manifest.json');oi={};quality=[]
    if manifest['stopped']:raise ValueError('acquisition access/budget stop')
    acquisition=load(folder/'acquisition_registration.json');check_hashes(acquisition['source_hashes'])
    for day in manifest['days']:
        date=day['date']
        if day['status']!='VERIFIED':
            oi[date]=None;quality.append(dict(date=date,endpoint_usable=False,reason=day['status']));continue
        for rec in day['requests']:
            if digest(folder/rec['file'])!=rec['sha256']:raise ValueError('archive receipt mismatch')
        path=folder/f'BTCUSDT-metrics-{date}.zip'
        if digest(path)!=(folder/(path.name+'.CHECKSUM')).read_text().split()[0]:raise ValueError('official checksum mismatch')
        value,audit=parse_day(path,date)
        if value is not None:
            # Independent CSV-reader/Decimal endpoint check, not pandas projection.
            with ZipFile(path) as z, z.open(z.namelist()[0]) as raw:
                data=list(csv.DictReader(TextIOWrapper(raw)))
            selected=[r for r in data if r['create_time']==date+' 23:55:00']
            if len(selected)!=1 or D(selected[0]['sum_open_interest'])!=D(value):raise ValueError('independent OI endpoint')
        oi[date]=value;quality.append(audit)
    return oi,dict(days=len(quality),usable_endpoint_days=sum(r['endpoint_usable'] for r in quality),
        unsorted_days=sum(r.get('input_monotonic') is False for r in quality),
        missing_5minute_slots=sum(r.get('missing_slots',0) for r in quality),
        source_rows=sum(r.get('rows',0) for r in quality),days_audit=quality,
        availability='FULL_NEXT_ARCHIVE_DAY_ELAPSED_ASSUMPTION_NOT_VINTAGE_RECEIPTS')


def verify_signal_inputs(rows):
    for r in rows:
        b=pd.Timestamp(r['boundary']);new=pd.Timestamp(r['new_oi_date']+'T23:55Z')
        if pd.Timestamp(r['entry_time'])-new!=pd.Timedelta(days=1,minutes=6):raise ValueError('OI availability lag')
        if str((b-pd.Timedelta(days=3)).date())!=r['old_oi_date']:raise ValueError('OI change window')
        expected=0
        if r['input_valid']:
            delta=D(r['new_oi'])/D(r['old_oi'])-1
            if delta!=D(r['oi_change']):raise ValueError('OI change mismatch')
            if delta>=D('.05') and D(str(r['decision_close']))<D(str(r['previous_close'])):expected=-1
        if r['side']!=expected:raise ValueError('wrong OI signal')
        if r['side'] and r['control_side']!=-1:raise ValueError('not subset of price control')
    return dict(status='PASS_DECIMAL_THRESHOLD_AND_ARCHIVE_LAG',rows=len(rows))


def preflight(minutes,rows,settings):
    risk=Risk(**settings['risk']);result={}
    for name,params in settings['costs'].items():
        cost=Costs(**params);checked=[]
        for r in rows:
            if not r['control_side']:continue
            price=float(minutes.o.iloc[r['entry_minute']])
            proposal=size_order(price,r['decision_close'],r['atr'],-1,1000,False,cost,risk)
            tick,step=D(str(cost.tick)),D(str(risk.step));fee=D(str(cost.fee_bps))/10000;slip=D(str(cost.slippage_bps))/10000
            entry=(D(str(price))*(1-slip)/tick).to_integral_value(rounding=ROUND_FLOOR)*tick
            qty=(max(D('.001'),D(50)/entry)/step).to_integral_value(rounding=ROUND_CEILING)*step
            stop=((D(str(r['decision_close']))+3*D(str(r['atr'])))/tick).to_integral_value(rounding=ROUND_CEILING)*tick
            fill=(stop*(1+slip)/tick).to_integral_value(rounding=ROUND_CEILING)*tick
            loss=qty*(fill-entry+(entry+fill)*fee)
            approved=entry<stop and loss<=5 and qty*entry<=1000
            if proposal['approved']!=approved:raise ValueError('independent short minimum-order preflight')
            if approved:near(proposal['quantity'],float(qty));near(proposal['planned_loss'],float(loss))
            checked.append(dict(time=r['entry_time'],candidate=bool(r['side']),approved=approved,
                minimum_quantity=str(qty),planned_loss_usdc=str(loss),proposal=proposal))
        result[name]=dict(status='PASS_DECIMAL_SHORT_INITIAL_CAPITAL_PREFLIGHT',rows=checked,
            approved={'OI':sum(r['approved'] and r['candidate'] for r in checked),'PRICE':sum(r['approved'] for r in checked)})
    return result


def main(out):
    prior=ROOT/'reports/validation/e046_weekly_minimum_contract_20260919';old=load(prior/'registration.json')
    sources=dict(old['source_hashes'])
    for name in ['app/research/diagnostics/open_interest_pressure.py','scripts/run_open_interest_pressure.py',
        'scripts/fetch_open_interest_pressure.py','tests/test_open_interest_pressure.py','docs/research/experiments/E047_OPEN_INTEREST_PRESSURE.md']:
        sources[name]=digest(ROOT/name)
    check_hashes(sources)
    folder=ROOT/'data/historical/btcusdt_oi_20260919'
    input_hashes={str(p.relative_to(ROOT)):digest(p) for p in folder.iterdir() if p.is_file()}
    risk={**old['settings']['risk'],'maximum_hold_minutes':1440}
    settings=dict(start=START,end=END,costs=old['settings']['costs'],risk=risk,models=['OI','PRICE'],
        oi_growth_min=.05,oi_latest_lag_minutes=1446,sizing='MINIMUM_LEGAL_QUANTITY_ONLY',
        source_symbol='BTCUSDT',trade_symbol='BTCUSDC',paths=['OHLC','OLHC'],monthly_operating_cost_scenarios=[0,2],
        minimum_active_events=20,minimum_valid_fraction=.95,hold_minutes=1439,source_price_data_reused=True,
        actual_operating_cost_unknown=True,source_archive_revisions_not_point_in_time=True)
    save(out/'registration.json',dict(registered_at=datetime.now(timezone.utc).isoformat(),settings=settings,
        source_hashes=sources,input_hashes=input_hashes,prior_verification_sha256=digest(prior/'verification.json'),actual_orders=0))
    for name in sources:
        path=out/'source_snapshot'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes((ROOT/name).read_bytes())
    with (out/'tests.log').open('x') as stream:
        tested=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromNames(
            ['tests.test_open_interest_pressure','tests.test_minimum_contract','tests.test_operating_engine','tests.test_intrabar_risk_paths']))
    if not tested.wasSuccessful() or tested.skipped:raise ValueError('focused tests failed')
    oi,quality=load_oi(folder);save(out/'data_quality.json',quality)
    print('OI quality',json.dumps({k:v for k,v in quality.items() if k!='days_audit'}),flush=True)
    bundle=load_public_bundle(ROOT,ROOT/'data/historical/btcusdc_public_20260917');bundle.require_complete_window(START,END)
    rows=signals(bundle.trade,oi,START,END)
    if len(rows)!=729:raise ValueError('incomplete evaluation calendar')
    features=frame_features(bundle.trade,240)
    for r in rows:r.update(atr=float(features.at[pd.Timestamp(r['boundary']),'atr']),feature_time=r['boundary'])
    signal_audit=verify_signal_inputs(rows);atr_audit=verify_inputs(bundle.trade,rows)
    save(out/'signals.json',rows);save(out/'signal_verification.json',dict(signal=signal_audit,atr=atr_audit))
    availability=preflight(bundle.trade,rows,settings);save(out/'minimum_contract_preflight.json',availability)
    valid=sum(r['input_valid'] for r in rows);quality_pass=valid/len(rows)>=.95
    results={};cost_checks={}
    for scenario,params in settings['costs'].items():
        cost=Costs(**params);events={}
        for model in settings['models']:
            selected=rows if model=='OI' else [dict(r,side=r['control_side']) for r in rows]
            events[model]=event_returns(bundle.trade,selected,bundle.funding,cost,'REVERSAL')
            save(out/(scenario+'_'+model+'_events.json'),events[model])
            cost_checks[scenario+'_'+model]=verify_event_costs(bundle.trade,selected,events[model],bundle.funding,cost,'MOMENTUM')
        results[scenario]=event_stats(events['OI'],events['PRICE'])
        print('Event economics',scenario,json.dumps(results[scenario]),flush=True)
    gate_conditions={'data_quality':quality_pass,'minimum_events':sum(bool(r['side']) for r in rows)>=20,
        'positive_net_both_costs':all(r['active_mean_net_bps'] is not None and r['active_mean_net_bps']>0 for r in results.values()),
        'positive_calendar_excess_both_costs':all(r['calendar_excess_bps']>0 for r in results.values()),
        'minimum_order_possible_both_costs':all(v['approved']['OI']>0 for v in availability.values())}
    gate=all(gate_conditions.values())
    save(out/'event_summary.json',dict(results=results,gate_conditions=gate_conditions,gate_pass=gate,
        valid_input_days=valid,total_days=len(rows),account_returns=False))
    runs,checks=account_stage(out,bundle,rows,settings) if gate else ({},{})
    save(out/'summary.json',dict(settings=settings,event_economics=results,gate_conditions=gate_conditions,account_gate_pass=gate,
        runs=runs,account_runs=len(runs),valid_input_days=valid,total_days=len(rows),
        availability={c:v['approved'] for c,v in availability.items()},account_drawdown_measured=bool(runs),
        operating_cost_integrated=bool(runs),actual_orders=0,future_profit_verified=False,strategy_adopted=False))
    check_hashes(sources);check_hashes(input_hashes)
    save(out/'verification.json',dict(status='PASS_SCOPED_ARCHIVE_SIGNAL_AND_COST_CHECKS',focused_tests=tested.testsRun,
        signal=signal_audit,atr=atr_audit,event_costs=cost_checks,accounts=checks,source_hashes_unchanged=len(sources),
        artifacts={str(p.relative_to(out)):digest(p) for p in out.rglob('*') if p.is_file()}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    try:main(args.output)
    except Exception as e:save(args.output/'failure.json',dict(type=type(e).__name__,reason=str(e)));raise
