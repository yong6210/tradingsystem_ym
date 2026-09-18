"""E017 fixed-ledger attribution and concentration. Never reruns a strategy."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.research.data.btcusdc import load_public_bundle
from app.research.diagnostics.economics import close,dec
from app.research.diagnostics.concentration import (
    FLOW_KEYS, concentration,direction_groups,event_costs,cycle_attribution,
    daily_attribution,calendar_months,episode_flow,aggregate)
from scripts.run_direction_controls import save,load,lines,digest,test_ids
from scripts.report_btcusdc_comparison import verify_run


def main(output):
    prior=ROOT/'reports/validation/e016_economics_20260918'
    registration=load(prior/'registration.json')
    hashes=dict(registration['prior_artifact_hashes'])
    for p in sorted(prior.rglob('*')):
        if p.is_file():hashes[str(p.relative_to(ROOT))]=digest(p)
    receipt=load(prior/'verification.json')
    for name,expected in receipt['artifact_hashes'].items():
        if digest(prior/name)!=expected:raise ValueError('E016 evidence differs: '+name)
    for name,expected in hashes.items():
        if digest(ROOT/name)!=expected:raise ValueError('old evidence differs: '+name)
    sources=dict(registration['source_hashes'])
    for name in ('app/research/diagnostics/concentration.py','scripts/diagnose_profit_concentration.py',
                 'tests/test_profit_concentration.py','docs/research/experiments/E017_PROFIT_CONCENTRATION.md'):
        sources[name]=digest(ROOT/name)
    suite=unittest.defaultTestLoader.loadTestsFromNames(('tests.test_profit_concentration',
        'tests.test_economics_diagnostic','tests.test_baseline_account','tests.test_review_metrics'))
    ids=list(test_ids(suite))
    settings=registration['settings']
    save(output/'registration.json',dict(registered_at=datetime.now(timezone.utc).isoformat(),
        classification='RETROSPECTIVE_FIXED_LEDGER_CONCENTRATION_NOT_SELECTION',
        settings=dict(start=settings['start'],end=settings['end'],scenarios=['base','stress'],
                      trade_top_counts=[1,5,10],direction_group_top_counts=[1,3,5]),
        source_hashes=sources,prior_artifact_hashes=hashes,test_ids=ids,automatic_retries=0))
    for name,expected in sources.items():
        if digest(ROOT/name)!=expected:raise ValueError('source changed: '+name)
        p=output/'source_snapshot'/name;p.parent.mkdir(parents=True,exist_ok=True)
        p.write_bytes((ROOT/name).read_bytes())
    with (output/'tests.log').open('x') as stream:
        tested=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    save(output/'tests.json',dict(registered=len(ids),executed=tested.testsRun,
        failures=len(tested.failures),errors=len(tested.errors),skipped=len(tested.skipped)))
    if not tested.wasSuccessful() or tested.skipped or tested.testsRun!=len(ids):raise ValueError('tests failed')
    print('Tests passed; reading verified BTCUSDC data.',flush=True)
    bundle=load_public_bundle(ROOT,ROOT/'data/historical/btcusdc_public_20260917')
    bundle.require_complete_window(settings['start'],settings['end'])
    closes={str(stamp.date()):float(price) for stamp,price in bundle.trade.c.resample('1D').last().items()}
    funding={event['fundingTime']:event for event in bundle.funding}
    summaries,checks={},{}
    for scenario in ('base','stress'):
        folder=ROOT/'reports/validation/e014_direction_controls_20260918'/(scenario+'_T0')
        metrics=load(folder/'metrics.json')
        events,trades,daily=(lines(folder/(name+'.jsonl')) for name in ('events','trades','daily'))
        path_folder=ROOT/'reports/validation/e015_intrabar_risk_paths_20260918'/(scenario+'_T0_OHLC')
        if events!=lines(path_folder/'events.jsonl'):raise ValueError('stop reference ledger differs')
        stops={row['event_index']:row for row in lines(path_folder/'path_stops.jsonl')}
        checks[scenario]=verify_run(folder,metrics,funding)
        parts=event_costs(events,trades,stops,bundle.trade,metrics['costs'])
        cycles=cycle_attribution(events,trades,parts)
        groups=direction_groups(cycles)
        days=daily_attribution(events,daily,closes,parts)
        months=calendar_months(days)
        if len(months)!=24:raise ValueError('incomplete monthly coverage')
        total=aggregate(days,'whole window')
        bridge=load(prior/scenario/'summary.json')['cost_bridge']
        for current,old in (('net','net_profit'),('reference_mtm','reference_gross'),('fill_mtm','fill_gross'),
                            ('fees','fees'),('slippage','slippage'),('tick_rounding','tick_rounding'),
                            ('historical_funding','historical_funding_net'),('stress_funding','stress_funding')):
            close(total[current],bridge[old])
        for key in FLOW_KEYS:close(sum(dec(m[key]) for m in months),total[key])
        for ck,dk in (('net','net'),('reference_pnl','reference_mtm'),('fill_pnl','fill_mtm'),
                       ('fees','fees'),('slippage','slippage'),('tick_rounding','tick_rounding'),
                       ('historical_funding','historical_funding'),('stress_funding','stress_funding')):
            close(sum(dec(c[ck]) for c in cycles),total[dk])
        close(sum(dec(g['net']) for g in groups),total['net'])
        if sorted(i for g in groups for i in g['cycle_ids'])!=list(range(len(cycles))):
            raise ValueError('cycle omitted or duplicated in groups')
        episode=load(prior/scenario/'summary.json')['longest_daily_recovery']
        periods={label:episode_flow(days,start,end) for label,start,end in (
            ('peak_to_trough',episode['peak_day'],episode['trough_day']),
            ('trough_to_recovery',episode['trough_day'],episode['end_day']),
            ('peak_to_recovery',episode['peak_day'],episode['end_day']))}
        close(periods['peak_to_trough']['net'],dec(episode['trough_equity'])-dec(episode['peak_equity']))
        for key in FLOW_KEYS:
            close(dec(periods['peak_to_trough'][key])+dec(periods['trough_to_recovery'][key]),periods['peak_to_recovery'][key])
        summaries[scenario]=dict(cycles=concentration(cycles,(1,5,10)),
            direction_groups=concentration(groups,(1,3,5)),monthly=dict(months=24,
                positive_net=sum(m['net']>0 for m in months),negative_net=sum(m['net']<0 for m in months),
                flat_net=sum(m['net']==0 for m in months),
                negative_reference=sum(m['reference_mtm']<0 for m in months),
                positive_reference_negative_net=sum(m['reference_mtm']>0 and m['net']<0 for m in months)),
            full_window=total,longest_recovery=episode,periods=periods)
        target=output/scenario;target.mkdir()
        for name,rows in (('cycles',cycles),('direction_groups',groups),('daily',days),('monthly',months)):
            save(target/(name+'.json'),rows)
        save(target/'summary.json',summaries[scenario])
        checks[scenario].update(days=len(days),months=len(months),direction_groups=len(groups),
            attribution_sums_match=True,e016_cost_bridge_matches=True)
        print(scenario+': '+str(summaries[scenario]['cycles'])+'; monthly='+str(summaries[scenario]['monthly']),flush=True)
    save(output/'summary.json',dict(runs=summaries,new_backtests=0,strategy_adopted=False))
    for name,expected in sources.items():
        if digest(ROOT/name)!=expected:raise ValueError('source changed: '+name)
    for name,expected in hashes.items():
        if digest(ROOT/name)!=expected:raise ValueError('prior evidence changed: '+name)
    save(output/'verification.json',dict(status='PASS_SCOPED_CONCENTRATION_AND_DAILY_ATTRIBUTION',
        checks=checks,prior_artifacts_unchanged=len(hashes),sources_unchanged=len(sources),
        new_backtests=0,actual_orders=0,strategy_adopted=False,
        artifact_hashes={str(p.relative_to(output)):digest(p) for p in sorted(output.rglob('*')) if p.is_file()}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    try:main(args.output)
    except Exception as exc:
        save(args.output/'failure.json',dict(status='FAILED',exception=type(exc).__name__,reason=str(exc)))
        raise
