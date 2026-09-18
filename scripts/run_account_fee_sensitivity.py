"""E024: four T0 accounts at the user-reported taker fee, no tuning."""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal as D
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import pandas as pd
from app.research.baseline.account import Costs
from app.research.baseline.risk import Risk
from app.research.baseline.engine import policies
from app.research.data.btcusdc import load_public_bundle
from app.research.multistrategy_audit import frame_features
from app.research.diagnostics.account_fee import reported_taker_costs
from app.research.diagnostics.intrabar_engine import simulate
from app.research.diagnostics.direction_controls import verify_t0_from_minutes
from scripts.run_direction_controls import save,load,lines,digest,test_ids,verify_daily
from scripts.run_intrabar_risk_paths import verify_stops
from scripts.report_btcusdc_comparison import verify_run
from scripts.run_btcusdc_comparison import annual
from scripts.run_time_exit_policy import START,END,TESTS,check_hashes,diagnostics,verify_window

PRIOR = ROOT/'reports/validation/e023_time_exit_policy_20260919'
CONTEXT = 'configs/research/account_cost_context_20260919.json'


def main(output):
    old_reg = load(PRIOR/'registration.json')
    old_check = load(PRIOR/'verification.json')
    for name,expected in old_check['artifact_hashes'].items():
        if digest(PRIOR/name)!=expected: raise ValueError('E023 evidence changed: '+name)
    sources = dict(old_reg['source_hashes'])
    for name in (CONTEXT,'app/research/diagnostics/account_fee.py','tests/test_account_fee.py',
                 'scripts/run_account_fee_sensitivity.py','docs/research/experiments/E024_ACCOUNT_FEE_SENSITIVITY.md'):
        sources[name] = digest(ROOT/name)
    old_hashes = dict(old_reg['prior_artifact_hashes'])
    for file in sorted(PRIOR.rglob('*')):
        if file.is_file():old_hashes[str(file.relative_to(ROOT))] = digest(file)
    check_hashes(sources);check_hashes(old_hashes)
    context = load(ROOT/CONTEXT)
    old_costs = {'base':Costs(),'stress':Costs(7,5,1)}
    costs = {key:reported_taker_costs(context,cost) for key,cost in old_costs.items()}
    settings = dict(start=START,end=END,model='T0',risk=asdict(Risk()),
                    costs={k:asdict(v) for k,v in costs.items()},
                    reference_costs={k:asdict(v) for k,v in old_costs.items()},
                    paths=['OHLC','OLHC'],new_account_runs=4,reused_control_accounts=4,
                    operating_cost=None,fee_source='USER_REPORTED_CURRENT_RATE_NOT_HISTORICAL_SCHEDULE')
    suite = unittest.defaultTestLoader.loadTestsFromNames(('tests.test_account_fee',*TESTS))
    ids = list(test_ids(suite))
    save(output/'registration.json',dict(registered_at=datetime.now(timezone.utc).isoformat(),
        classification='RETROSPECTIVE_ACCOUNT_FEE_SENSITIVITY_NOT_STRATEGY_SELECTION',settings=settings,
        source_hashes=sources,prior_artifact_hashes=old_hashes,test_ids=ids,automatic_retries=0,
        primary='new fee final equity minus frozen control, matched execution scenario and path',
        stop_rule='Any test, data, ledger, source or reference mismatch stops the run'))
    for name in sources:
        path=output/'source_snapshot'/name;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes((ROOT/name).read_bytes())
    with (output/'tests.log').open('x') as stream:
        tested=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    save(output/'tests.json',dict(registered=len(ids),executed=tested.testsRun,
        failures=len(tested.failures),errors=len(tested.errors),skipped=len(tested.skipped)))
    if not tested.wasSuccessful() or tested.skipped or tested.testsRun!=len(ids):raise ValueError('tests failed')
    print('Tests passed; loading verified BTCUSDC data.',flush=True)
    bundle=load_public_bundle(ROOT,ROOT/'data/historical/btcusdc_public_20260917')
    bundle.require_complete_window(START,END);verify_window(bundle.trade.index,START,END)
    signals=policies(bundle.trade,{240:frame_features(bundle.trade,240)})['T0']
    save(output/'signal_verification.json',verify_t0_from_minutes(bundle.trade,signals))
    funding={e['fundingTime']:e for e in bundle.funding}
    closes={str(t.date()):float(p) for t,p in bundle.trade.c.resample('1D').last().items()}
    references,checks,runs,differences={},{},{},{}
    # Reverify all frozen reference ledgers before new simulations.
    for scenario,cost in old_costs.items():
        for path in settings['paths']:
            key=scenario+'_'+path;folder=PRIOR/(scenario+'_control_'+path)
            old={name:lines(folder/(name+'.jsonl')) for name in ('events','trades','daily','rejections','path_stops')}
            old['metrics']=load(folder/'metrics.json')
            if old['metrics']['costs']!=asdict(cost) or old['metrics']['risk']!=asdict(Risk()):
                raise ValueError('control assumptions differ')
            audit=verify_run(folder,old['metrics'],funding)
            audit['daily']=verify_daily(old,bundle.trade)
            audit['stops']=verify_stops(old,bundle.trade,path,cost,Risk())
            detail=diagnostics(old,bundle.trade,closes)
            if detail!=load(folder/'diagnostics.json'):raise ValueError('control diagnostics differ')
            references[key]=dict(metrics=old['metrics'],diagnostics=detail)
            checks['reference_'+key]=audit
    for scenario,cost in costs.items():
        for path in settings['paths']:
            key=scenario+'_'+path
            result=simulate(bundle.trade,signals,pd.Timestamp(START),pd.Timestamp(END),cost,Risk(),funding=bundle.funding,path=path)
            metrics=result['metrics'];metrics['annual']=annual(result['daily'],1000)
            folder=output/key;folder.mkdir()
            for name in ('events','trades','daily','rejections','path_stops'):
                with (folder/(name+'.jsonl')).open('x') as stream:
                    for row in result[name]:stream.write(json.dumps(row,allow_nan=False)+'\n')
            save(folder/'metrics.json',metrics)
            audit=verify_run(folder,metrics,funding);audit['daily']=verify_daily(result,bundle.trade)
            audit['stops']=verify_stops(result,bundle.trade,path,cost,Risk())
            detail=diagnostics(result,bundle.trade,closes)
            save(folder/'diagnostics.json',detail);save(folder/'verification.json',audit)
            runs[key]=dict(metrics=metrics,diagnostics=detail);checks['new_'+key]=audit
            old=references[key];old_folder=PRIOR/(scenario+'_control_'+path)
            old_events=lines(old_folder/'events.jsonl');old_trades=lines(old_folder/'trades.jsonl')
            reduction=D(str(old_costs[scenario].fee_bps))-D(str(cost.fee_bps))
            arithmetic=sum((D(str(e['qty']))*D(str(e['price']))*reduction/10000
                            for e in old_events if e['kind'] in ('entry','exit')),D(0))
            delta=metrics['final_equity']-old['metrics']['final_equity']
            trajectory=lambda rows:[tuple(t[k] for k in ('entry_time','exit_time','side','quantity','entry_price','stop','reason')) for t in rows]
            differences[key]=dict(final_equity_usdc=delta,
                fixed_old_fills_arithmetic_fee_saving_usdc=float(arithmetic),
                difference_from_fixed_path_arithmetic_usdc=delta-float(arithmetic),
                trade_path_equal=trajectory(result['trades'])==trajectory(old_trades),
                cost_bridge={k:detail['cost_bridge'][k]-v for k,v in old['diagnostics']['cost_bridge'].items()})
            print(json.dumps(dict(run=key,return_pct=metrics['return_pct'],dd=metrics['max_drawdown_pct'],
                cycles=metrics['cycles'],improvement_usdc=delta)),flush=True)
    save(output/'summary.json',dict(settings=settings,runs=runs,references=references,differences=differences,
        previously_observed_data=True,maker_fills_simulated=False,operating_cost_included=False,
        historical_fee_schedule_verified=False,strategy_adopted=False))
    check_hashes(sources);check_hashes(old_hashes)
    save(output/'verification.json',dict(status='PASS_SCOPED_FEE_LEDGER_DAILY_STOP_AND_ATTRIBUTION_CHECKS',
        checks=checks,completed_new_runs=len(runs),reverified_reference_runs=len(references),
        checked_events=sum(v['events'] for v in checks.values()),checked_cycles=sum(v['cycles'] for v in checks.values()),
        sources_unchanged=len(sources),prior_artifacts_unchanged=len(old_hashes),actual_orders=0,strategy_adopted=False,
        artifact_hashes={str(p.relative_to(output)):digest(p) for p in sorted(output.rglob('*')) if p.is_file()}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    try:main(args.output)
    except Exception as exc:
        save(args.output/'failure.json',dict(status='FAILED',exception=type(exc).__name__,reason=str(exc)))
        raise
