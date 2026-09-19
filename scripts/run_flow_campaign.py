"""Register and run E057, reporting every predeclared policy/cost/leverage."""
from pathlib import Path
import sys,json,hashlib,unittest
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import pandas as pd
import numpy as np
from app.research.data.btcusdc import load_public_bundle
from app.research.diagnostics.multiscale_profile import Profiles,context_features
from app.research.diagnostics.flow_campaign import features
from app.research.diagnostics.flow_campaign import simulate
from app.research.diagnostics.context_timing_inventory_v2 import simulate as baseline_simulate
from scripts.run_ten_slice_pilot import audit

P=ROOT/'reports/validation/e057_flow_campaign_20260919'
DATA=ROOT/'data/historical/btcusdc_aggprofiles_20260919'

def save(p,x):p.write_text(json.dumps(x,indent=2,allow_nan=False)+'\n')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    P.mkdir(parents=True,exist_ok=True)
    if (P/'registration.json').exists():raise ValueError('no overwrite')
    cp=ROOT/'configs/research/e057_flow_campaign.json';c=json.loads(cp.read_text())
    with (P/'tests.log').open('w') as fp:
        suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(n) for n in ['tests.test_multiscale_profile','tests.test_ten_slice_controller','tests.test_context_timing_v2','tests.test_flow_campaign'])
        test=unittest.TextTestRunner(stream=fp,verbosity=2).run(suite)
    assert test.wasSuccessful()
    paths=[cp,Path(__file__),ROOT/'app/research/diagnostics/multiscale_profile.py',ROOT/'app/research/diagnostics/profile_inventory.py',ROOT/'app/research/diagnostics/ten_slice_controller.py',ROOT/'app/research/diagnostics/intraday_inventory_v1.py',ROOT/'scripts/run_ten_slice_pilot.py',ROOT/'tests/test_multiscale_profile.py',ROOT/'tests/test_ten_slice_controller.py',ROOT/'app/research/data/btcusdc.py',ROOT/'app/research/data/minutes.py']
    paths += [ROOT/n for n in ['app/research/diagnostics/context_timing_inventory_v2.py','app/research/diagnostics/context_timing_signals_v2.py','tests/test_context_timing_v2.py','reports/validation/e055_multiscale_profile_20260919/summary.json']]
    paths += [ROOT/'app/research/diagnostics/flow_campaign.py',ROOT/'tests/test_flow_campaign.py',ROOT/'reports/validation/e056_context_timing_v2_20260919/summary.json']
    paths += [DATA/n for n in ['manifest.json','aggregation.json','histogram_50usdc_15min.npz','minute_volume_reconciliation.json']]
    old=ROOT/'data/historical/btcusdc_public_20260917'
    paths += [old/n for n in ['manifest.json','validated_overlay.json','gap_probe_manifest.json']]
    save(P/'registration.json',dict(registered_at=datetime.now(timezone.utc).isoformat(),config=c,source_hashes={str(p.relative_to(ROOT)):sha(p) for p in paths},orders=0))
    print('Loading public minute data and causal profiles',flush=True)
    b=load_public_bundle(ROOT,old);b.require_complete_window(c['start'],c['end'])
    z=np.load(DATA/'histogram_50usdc_15min.npz')
    start_ms=int(pd.Timestamp('2026-06-01T00:00Z').timestamp()*1000)
    profiles=Profiles(z['hist'],int(z['offset']),start_ms)
    f=features(b.trade.loc['2026-01-01':])
    mask=(b.trade.index>=pd.Timestamp(c['start']))&(b.trade.index<pd.Timestamp(c['end']))
    m=b.trade.loc[mask];mark=b.mark.reindex(m.index);f=f.reindex(m.index)
    events={((int(e['fundingTime'])+59999)//60000)*60000:dict(time_ms=int(e['fundingTime']),mark=float(e['markPrice']),rate=float(e['fundingRate'])) for e in b.funding}
    results=[];fills=0
    for policy in c['policies']:
        for leverage in c['leverages']:
            for cost in c['costs']:
                key=f'{policy}_{leverage}x_{cost}'
                if policy=='baseline':
                    result,ledger,daily,campaigns,decisions=baseline_simulate(m,mark,f.drop(columns=['flow','h_close','h_previous_close','h_open']),profiles,events,c,leverage,cost,'context_timing')
                    old_results=json.loads((ROOT/'reports/validation/e056_context_timing_v2_20260919/summary.json').read_text())
                    expected=next(x for x in old_results if x['policy']=='context_timing' and x['leverage_assumption']==leverage and x['cost']==cost)
                    for metric in ['return_pct','max_drawdown_envelope_pct','fills','holding_minute_pct']:assert result[metric]==expected[metric],metric
                    result['policy']='baseline'
                else:
                    result,ledger,daily,campaigns,decisions=simulate(m,mark,f,profiles,events,c,leverage,cost,policy)
                audit(ledger,c['initial_equity']*(1+result['return_pct']/100))
                previous=0
                for r in ledger:
                    assert r['time_ms']>=previous;previous=r['time_ms']
                    if r['kind']=='fill':
                        assert abs(r['delta_qty']/.001-round(r['delta_qty']/.001))<1e-6
                        t=pd.to_datetime(r['time_ms'],unit='ms',utc=True)
                        expected=m.loc[t.floor('min'),'c' if r['reason']=='end' else 'o']
                        assert abs(expected-r['reference'])<1e-8
                        if 'profile_cutoff_ms' in r:assert r['profile_cutoff_ms']<=r['time_ms']-60000
                        if policy=='no_add':assert r['reason'] not in ('profile_one_tenth_add','adaptive_add')
                if policy=='baseline':result['maximum_allocated_tenths']=max((r.get('allocated_units_after',0) for r in ledger),default=0)
                result['long_campaigns']=sum(x['side']==1 for x in campaigns)
                result['short_campaigns']=sum(x['side']==-1 for x in campaigns)
                result['reasons']={reason:sum(r.get('reason')==reason for r in ledger) for reason in sorted({r['reason'] for r in ledger if r['kind']=='fill'})}
                for name,rows in [('ledger',ledger),('daily',daily),('campaigns',campaigns),('decisions',decisions)]:
                    (P/f'{key}_{name}.jsonl').write_text(''.join(json.dumps(r,allow_nan=False)+'\n' for r in rows))
                results.append(result);fills+=result['fills'];print(json.dumps(result),flush=True)
    save(P/'summary.json',results)
    save(P/'verification.json',dict(accounts=len(results),fill_rows=fills,tests=test.testsRun,decimal_accounting=True,raw_reference_prices=True,chronological_ledgers=True,profile_cutoff_before_execution=True,no_add_control=True,source_hashes_unchanged=all(sha(ROOT/p)==h for p,h in json.loads((P/'registration.json').read_text())['source_hashes'].items())))

if __name__=='__main__':main()
