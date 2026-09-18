"""E032 registered offline replay after a received-history snapshot repair."""
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal as D
import inspect
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.audit_microstructure_fitness import load,save,sha,check,lines
from scripts.audit_microstructure_raw_sample import timestamp_ns
from scripts.audit_flow_events import verify
from scripts.run_flow_absorption import DATES
from app.research.diagnostics import flow_absorption as original
from app.research.diagnostics import flow_absorption_v2 as repaired


def main():
    old=ROOT/'reports/validation/e032_flow_absorption_20260919'
    out=ROOT/'reports/validation/e032_flow_snapshot_repair_20260919';out.mkdir(exist_ok=False)
    reg=load(old/'registration.json');proof=load(old/'verification.json')
    check(proof['artifacts'],old);check(reg['source_hashes']);check(reg['protected_hashes']);check(reg['input_hashes'])
    protected=reg['protected_hashes']|reg['source_hashes']|reg['input_hashes']
    protected.update({str((old/n).relative_to(ROOT)):h for n,h in proof['artifacts'].items()})
    protected[str((old/'verification.json').relative_to(ROOT))]=sha(old/'verification.json')
    names=['scripts/rerun_flow_snapshot_repair.py','app/research/diagnostics/flow_absorption_v2.py','tests/test_flow_snapshot_repair.py']
    sources={n:sha(ROOT/n) for n in names}
    for name in ['signal','market_leg','events']:
        if inspect.getsource(getattr(original,name))!=inspect.getsource(getattr(repaired,name)):
            raise ValueError('strategy or cost function changed')
    save(out/'registration.json',dict(registered_at=datetime.now(timezone.utc).isoformat(),source_hashes=sources,protected_hashes=protected,
        dates=DATES,public_requests=0,actual_orders=0,repair='Replay only already received covering depth history when a later generated snapshot arrives; preserve snapshot receipt availability and 60-second warmup.',
        original_failure='2026-04-01 invalid L2 SNAPSHOT_BRIDGE_MISSING',rule_functions_identical=['signal','market_leg','events'],
        unchanged_intervals_required=7,all_eight_intervals_replayed=True,no_strategy_parameter_or_sample_change=True))
    for n in names:
        p=out/'source_snapshot'/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((ROOT/n).read_bytes())
    suite=unittest.defaultTestLoader.loadTestsFromName('tests.test_flow_snapshot_repair.RepairedFlowBoundaries')
    with (out/'tests.log').open('w') as f:test=unittest.TextTestRunner(stream=f,verbosity=2).run(suite)
    save(out/'tests.json',dict(executed=test.testsRun,failures=len(test.failures),errors=len(test.errors),skipped=len(test.skipped)))
    if not test.wasSuccessful() or test.skipped:raise ValueError('repair test failed')
    all_events=[];results={};unchanged=0
    for date in DATES:
        folder=out/date;folder.mkdir();start=timestamp_ns(date+'T00:00:00Z')
        grid,quality=repaired.grid_from_raw(old/date/'raw.ndjson',start,start+600*10**9,timestamp_ns)
        cohort=repaired.events(grid);audit=verify(grid,cohort)
        same=None
        if (old/date/'grid.jsonl').exists():
            same=grid==lines(old/date/'grid.jsonl') and cohort==lines(old/date/'events.jsonl')
            if not same:raise ValueError('previously successful interval changed: '+date)
            unchanged+=1
        for key,values in [('grid',grid),('events',cohort)]:
            (folder/(key+'.jsonl')).write_text(''.join(json.dumps(x)+'\n' for x in values))
        save(folder/'quality.json',quality);save(folder/'independent_audit.json',audit)
        results[date]=dict(status='COMPLETE_SCOPED_EVENT_DIAGNOSTIC',quality=quality,events=len(cohort),candidate_events=sum(e['candidate'] for e in cohort),previous_success_identical=same)
        all_events.extend(dict(date=date,**e) for e in cohort)
        print(date,len(cohort),sum(e['candidate'] for e in cohort),flush=True)
    if unchanged!=7:raise ValueError('unchanged interval count')
    aggregates={}
    for model in ['C0','S06B','C0_rejected_by_support']:
        selected=all_events if model=='C0' else [e for e in all_events if e['candidate']==(model=='S06B')]
        for cost in ['base','stress']:
            complete=[e['conditions'][cost] for e in selected if e['conditions'][cost]['status']=='COMPLETE_CONDITIONAL_EVENT']
            net=sum((D(e['net']) for e in complete),D(0))
            aggregates[model+'_'+cost]=dict(opportunities=len(selected),statuses=dict(Counter(e['conditions'][cost]['status'] for e in selected)),complete_events=len(complete),
                price_pnl=str(sum((D(e['price_pnl']) for e in complete),D(0))),fees=str(sum((D(e['fees']) for e in complete),D(0))),
                net_complete_only=str(net),mean_net_complete_only=str(net/len(complete)) if complete else None,
                unresolved_exits=sum(e['conditions'][cost]['status']=='EXIT_UNRESOLVED' for e in selected))
    save(out/'summary.json',dict(status='REPAIRED_OFFLINE_EVENT_DIAGNOSTIC_NOT_ADOPTION',intervals=results,aggregates=aggregates,
        failed_intervals=0,previous_successful_intervals_identical=unchanged,original_failed_run_retained=True,public_requests=0,
        representative_sample=False,performance_confirmation=False,account_return_computed=False,actual_orders=0,strategy_adopted=False,combined=False))
    (out/'all_events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in all_events))
    check(sources);check(protected)
    save(out/'verification.json',dict(status='PASS_SCOPED_REPAIR_AND_REPLAY',source_hashes_unchanged=len(sources),protected_hashes_unchanged=len(protected),tests=test.testsRun,
        artifacts={str(p.relative_to(out)):sha(p) for p in out.rglob('*') if p.is_file()}))
    print(json.dumps(aggregates,indent=2),flush=True)


if __name__=='__main__':main()
