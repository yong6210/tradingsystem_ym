"""E040 fixed daily walk-forward flow forecast: economics before account work."""
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
from app.research.data.btcusdc import load_public_bundle
from app.research.data.taker_flow import load_taker_flow
from app.research.diagnostics.daily_flow_forecast import daily_panel,signals,verify_features,interval
from app.research.diagnostics.session_reversal import event_returns
from scripts.run_weekly_momentum import verify_event_costs
from scripts.run_direction_controls import save,load,digest
from scripts.run_time_exit_policy import START,END,check_hashes


def main(out):
    prior=ROOT/'reports/validation/e039_weekly_long_operations_20260919'
    sources=dict(load(prior/'registration.json')['source_hashes'])
    names=['app/research/diagnostics/daily_flow_forecast.py','scripts/run_daily_flow_forecast.py',
           'tests/test_daily_flow_forecast.py','docs/research/experiments/E040_DAILY_FLOW_FORECAST.md',
           'app/research/data/taker_flow.py','tests/test_taker_flow.py','app/research/candidate_accounts/flow.py',
           'app/research/candidate_accounts/policies.py']
    sources.update({n:digest(ROOT/n) for n in names});check_hashes(sources)
    settings=dict(start=START,end=END,models=['PRICE','FLOW'],train_days=180,purge_days=1,
         penalty='n=180; standardized train-only inputs; unpenalized intercept',cost_threshold_bps=18,
         costs={k:vars(v) for k,v in dict(base=Costs(2.5,2,0),stress=Costs(2.5,5,1)).items()},
         first_stage='NONOVERLAPPING_DAILY_EVENT_RETURNS_NOT_ACCOUNT',market_requests=0)
    save(out/'registration.json',dict(registered_at=datetime.now(timezone.utc).isoformat(),settings=settings,
         source_hashes=sources,source_data_reused=True,actual_orders=0))
    for name in sources:
        p=out/'source_snapshot'/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((ROOT/name).read_bytes())
    with (out/'tests.log').open('x') as f:
        tested=unittest.TextTestRunner(stream=f,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromNames(
            ['tests.test_daily_flow_forecast','tests.test_taker_flow']))
    if not tested.wasSuccessful() or tested.skipped:raise ValueError('focused tests failed')
    print('Loading price/funding and archived taker-flow sources.',flush=True)
    directory=ROOT/'data/historical/btcusdc_public_20260917'
    bundle=load_public_bundle(ROOT,directory);bundle.require_complete_window(START,END)
    flow,quality=load_taker_flow(ROOT,directory);save(out/'flow_quality.json',quality)
    panel=daily_panel(bundle.trade,flow);save(out/'feature_verification.json',verify_features(bundle.trade,flow,panel))
    panel.to_json(out/'daily_features_and_targets.json',orient='table',date_format='iso',double_precision=15)
    prediction=signals(panel,bundle.funding,START,END)
    for model,rows in prediction.items():
        if len(rows)!=729:raise ValueError('incomplete event calendar')
        for row in rows:
            i,j=[int(bundle.trade.index.get_indexer([pd.Timestamp(row[k])])[0]) for k in ('entry_time','exit_time')]
            if i<0 or j-i!=1439:raise ValueError('wrong event bounds')
            row.update(entry_minute=i,exit_minute=j)
            boundary=pd.Timestamp(row['boundary'])
            if bundle.trade.index[i-2]!=boundary-pd.Timedelta(minutes=1):raise ValueError('feature availability')
            actual=(D(str(bundle.trade.o.iloc[j]))/D(str(bundle.trade.o.iloc[i]))-1)*10000
            row['target_bps']=float(actual)
            if abs(float(actual)-panel.loc[boundary,'target_bps'])>1e-7:raise ValueError('label prices differ')
            past=[e for e in bundle.funding if e['fundingTime']<int(boundary.timestamp()*1000)][-3:]
            if [e['fundingTime'] for e in past]!=row['past_funding_times']:raise ValueError('past funding mismatch')
            threshold=D(18)+abs(sum((D(e['fundingRate']) for e in past),D(0)))*10000+D('.2')/D(str(row['decision_close']))*10000
            if abs(float(threshold)-row['threshold_bps'])>1e-9:raise ValueError('threshold mismatch')
        save(out/(model+'_signals.json'),rows)
    results={};raw={};audits={}
    for model,rows in prediction.items():
        for scenario,params in settings['costs'].items():
            key=scenario+'_'+model;cost=Costs(**params)
            # The legacy helper's REVERSAL label selects supplied row.side; it
            # does not invert directions. These sides come from causal forecasts.
            values=event_returns(bundle.trade,rows,bundle.funding,cost,'REVERSAL')
            save(out/(key+'_events.json'),values);raw[key]=values
            audits[key]=verify_event_costs(bundle.trade,rows,values,bundle.funding,cost,'MOMENTUM')
            frame=pd.DataFrame(values);active=frame.side!=0
            actual=np.array([r['target_bps'] for r in rows]);pred=np.array([r['prediction_bps'] for r in rows])
            results[key]=dict(days=len(frame),active_days=int(active.sum()),long_days=int((frame.side==1).sum()),
                short_days=int((frame.side==-1).sum()),mean_net_bps_all_days=float(frame.net_bps.mean()),
                mean_net_bps_active_days=float(frame.loc[active,'net_bps'].mean()) if active.any() else None,
                mean_gross_bps_active_days=float(frame.loc[active,'gross_bps'].mean()) if active.any() else None,
                mean_cost_bps_active_days=float((frame.loc[active,'gross_bps']-frame.loc[active,'net_bps']).mean()) if active.any() else None,
                forecast_mse_bps_squared=float(np.mean((actual-pred)**2)),
                uncertainty=interval(frame.net_bps),
                by_year={str(y):dict(days=len(g),active_days=int((g.side!=0).sum()),mean_net_bps_all_days=float(g.net_bps.mean()))
                         for y,g in frame.groupby(frame.entry_time.str[:4])})
            print(key,json.dumps(results[key]),flush=True)
    paired={c:interval([f['net_bps']-p['net_bps'] for f,p in zip(raw[c+'_FLOW'],raw[c+'_PRICE'],strict=True)]) for c in settings['costs']}
    gate=all(results[c+'_FLOW']['mean_net_bps_all_days']>0 and paired[c]['mean_bps']>0 for c in settings['costs'])
    save(out/'summary.json',dict(settings=settings,results=results,paired_flow_minus_price=paired,
         account_gate_pass=gate,decision='ACCOUNT_STAGE_ELIGIBLE_NOT_ADOPTED' if gate else 'STOP_NO_COST_NET_INCREMENTAL_EDGE',
         accounts_run=0,operating_cost_included=False,account_drawdown_measured=False,
         real_world_5pct_guarantee=False,source_data_reused=True,future_profit_verified=False,models_adopted=[]))
    check_hashes(sources)
    save(out/'verification.json',dict(status='PASS_FEATURE_TRAINING_AND_EVENT_ARITHMETIC',focused_tests=tested.testsRun,
         feature_rows=len(panel),forecasts=2*729,event_checks=audits,source_hashes_unchanged=len(sources),
         artifacts={str(p.relative_to(out)):digest(p) for p in out.rglob('*') if p.is_file()}))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=False)
    try:main(a.output)
    except Exception as e:save(a.output/'failure.json',dict(type=type(e).__name__,reason=str(e)));raise
