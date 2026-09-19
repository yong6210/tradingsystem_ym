"""E039: eight fixed weekly LONG accounts with monthly operating debits."""
import argparse
from dataclasses import asdict
from datetime import datetime,timezone
import json
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import pandas as pd
from app.research.baseline.account import Costs
from app.research.baseline.risk import Risk
from app.research.data.btcusdc import load_public_bundle
from app.research.diagnostics.weekly_momentum import sessions,decisions,verify_signals
from app.research.diagnostics.operating_engine import simulate
from app.research.diagnostics.operating_audit import verify_run,near
from app.research.diagnostics.review_metrics import calendar_risk
from app.research.diagnostics.concentration import concentration
from scripts.run_direction_controls import save,load,lines,digest,verify_daily
from scripts.run_time_exit_policy import START,END,check_hashes
from scripts.run_intrabar_risk_paths import verify_stops
from scripts.run_btcusdc_comparison import annual
PRIOR=ROOT/'reports/validation/e038_weekly_momentum_20260919_v2'


def main(out):
    old=load(PRIOR/'registration.json');sources=dict(old['source_hashes'])
    names=['app/research/diagnostics/operating_account.py','app/research/diagnostics/operating_engine.py',
           'app/research/diagnostics/operating_audit.py','tests/test_operating_engine.py',
           'scripts/run_weekly_long_operations.py','docs/research/experiments/E039_WEEKLY_LONG_OPERATING_COST.md']
    sources.update({name:digest(ROOT/name) for name in names});check_hashes(sources)
    evidence=load(PRIOR/'verification.json')
    for name,h in evidence['artifacts'].items():
        if digest(PRIOR/name)!=h:raise ValueError('changed E038 artifact: '+name)
    settings=dict(start=START,end=END,model='LONG',costs=old['settings']['costs'],risk=old['settings']['risk'],
                  monthly_operating_costs=[0,2],paths=['OHLC','OLHC'],runs=8,
                  charge_timing='MONTH_START_AFTER_FUNDING_BEFORE_RISK_AND_DECISIONS',charges_continue_after_halt=True)
    save(out/'registration.json',dict(registered_at=datetime.now(timezone.utc).isoformat(),settings=settings,
         source_hashes=sources,prior_verification_sha256=digest(PRIOR/'verification.json'),actual_orders=0))
    for name in sources:
        target=out/'source_snapshot'/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes((ROOT/name).read_bytes())
    with (out/'tests.log').open('x') as f:
        tested=unittest.TextTestRunner(stream=f,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromNames(
            ['tests.test_operating_engine','tests.test_weekly_momentum','tests.test_intrabar_risk_paths']))
    if not tested.wasSuccessful() or tested.skipped:raise ValueError('focused tests failed')
    print('Loading frozen bundle; zero-charge controls first.',flush=True)
    bundle=load_public_bundle(ROOT,ROOT/'data/historical/btcusdc_public_20260917');bundle.require_complete_window(START,END)
    signals=sessions(bundle.trade,START,END)
    if signals!=load(PRIOR/'signals.json'):raise ValueError('E038 decisions changed')
    save(out/'signal_verification.json',verify_signals(bundle.trade,signals))
    decision=decisions(signals,'LONG');risk=Risk(**settings['risk'])
    months=pd.date_range(START,END,freq='MS',inclusive='left')
    if len(months)!=24:raise ValueError('charge calendar')
    indices=bundle.trade.index.get_indexer(months)
    if min(indices)<0:raise ValueError('missing charge time')
    funding={e['fundingTime']:e for e in bundle.funding};runs={};checks={}
    for amount in settings['monthly_operating_costs']:
        debits={int(i):amount for i in indices}
        for scenario,params in settings['costs'].items():
            cost=Costs(**params)
            for path in settings['paths']:
                key=f'{scenario}_op{amount}_{path}';print(key,flush=True)
                result=simulate(bundle.trade,decision,pd.Timestamp(START),pd.Timestamp(END),cost,risk,
                                funding=bundle.funding,path=path,operating_debits=debits)
                m=result['metrics'];m['annual']=annual(result['daily'],1000)
                folder=out/key;folder.mkdir()
                for name in ('events','trades','daily','rejections','path_stops'):
                    with (folder/(name+'.jsonl')).open('x') as f:
                        for row in result[name]:f.write(json.dumps(row,allow_nan=False)+'\n')
                save(folder/'metrics.json',m)
                audit=verify_run(folder,m,funding);audit['daily']=verify_daily(result,bundle.trade)
                audit['stops']=verify_stops(result,bundle.trade,path,cost,risk)
                operating=[e for e in result['events'] if e['kind']=='operating']
                expected=[dict(time=t.isoformat(),amount=amount) for t in months] if amount else []
                if [dict(time=e['time'],amount=e['amount']) for e in operating]!=expected:raise ValueError('operating calendar differs')
                near(m['operating_cost'],24*amount)
                audit['operating_calendar_verified']=len(expected)
                if amount==0:
                    oldfolder=PRIOR/f'{scenario}_LONG_{path}'
                    current=dict(m);current.pop('operating_cost')
                    if current!=load(oldfolder/'metrics.json'):raise ValueError('zero-charge metrics differ')
                    for name in ('events','trades','daily','rejections','path_stops'):
                        if result[name]!=lines(oldfolder/(name+'.jsonl')):raise ValueError('zero-charge '+name+' differs')
                    audit['exact_e038_reproduction']=True
                monthly={};previous=1000.
                for day in result['daily']:
                    label=day['day'][:7];monthly[label]=monthly.get(label,0)+day['equity']-previous;previous=day['equity']
                trades=result['trades'];net=m['final_equity']-1000
                detail=dict(calendar_risk=calendar_risk(result['daily']),monthly_net_after_operations=monthly,
                            trading_concentration=concentration([dict(id=i,net=t['net_pnl']) for i,t in enumerate(trades)],(1,5)) if trades else None,
                            net_usdc=net,trading_net_before_operations=sum(t['net_pnl'] for t in trades),
                            monthly_cost_assumption_usdc=amount,necessary_conditions_pass=net>0 and m['max_drawdown_pct']<=5)
                save(folder/'diagnostics.json',detail);save(folder/'verification.json',audit)
                runs[key]=dict(metrics=m,diagnostics=detail);checks[key]=audit
                print(json.dumps(dict(run=key,net=net,dd=m['max_drawdown_pct'],cycles=m['cycles'],halt=m['halt_time'])),flush=True)
    save(out/'summary.json',dict(settings=settings,runs=runs,operating_assumption_confirmed_by_user=False,
         source_data_reused=True,future_profit_verified=False,strategy_adopted=False,actual_orders=0))
    check_hashes(sources)
    save(out/'verification.json',dict(status='PASS_WITH_EXECUTION_AND_SELECTION_LIMITATIONS',focused_tests=tested.testsRun,
         checks=checks,source_hashes_unchanged=len(sources),
         artifacts={str(p.relative_to(out)):digest(p) for p in out.rglob('*') if p.is_file()}))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=False)
    try:main(a.output)
    except Exception as e:save(a.output/'failure.json',dict(type=type(e).__name__,reason=str(e)));raise
