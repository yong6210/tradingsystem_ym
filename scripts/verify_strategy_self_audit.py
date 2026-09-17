"""Independent saved-ledger reconciliation and baseline equivalence checks."""
import csv, hashlib, json, math
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/validation/strategy_self_audit_20260917'
def main():
 data=json.loads((OUT/'results.json').read_text())
 old=json.loads((ROOT/'reports/validation/multistrategy_20260917/results.json').read_text())
 for p,h in data['protocol']['hashes'].items(): assert hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h
 rows=[]
 for period,runs in data['results'].items():
  for name,r in runs.items():
   q=avg=pnl=fees=0.; side=0
   for e in r['events']:
    size,price=e['qty'],e['price']
    if e['action']=='maker_add':
     assert not q or side==e['side']
     avg=(q*avg+size*price)/(q+size);q+=size;side=e['side']
    else:
     assert size<=q+1e-8
     pnl+=side*size*(price-avg);q-=size
     if e['action'].startswith('market_'): fees+=size*price*r['costs']['taker_bps']/10000
     if q<1e-9:q=avg=0.;side=0
   assert q==0 and math.isclose(pnl,r['realized'],abs_tol=1e-6)
   assert math.isclose(fees,r['fees'],abs_tol=1e-6)
   assert math.isclose(10000+pnl-fees-r['funding'],r['final_equity'],abs_tol=1e-6)
   assert math.isclose(math.prod(1+x for x in r['monthly'].values()),r['final_equity']/10000,abs_tol=1e-8)
   assert math.isclose(sum(x['pnl'] for x in r['cycle_log']),r['final_equity']-10000,abs_tol=1e-6)
   if name in ('swing_baseline','rotation_baseline','breakout_baseline'):
    family={'swing_baseline':'swing_trend','rotation_baseline':'inventory_rotation','breakout_baseline':'channel_breakout'}[name]
    prior=old[period][old['selected'][family]]
    for k in ('return_pct','max_drawdown_pct','cycles'):assert math.isclose(r[k],prior[k],abs_tol=1e-10)
   rows.append(dict(period=period,case=name,**{k:r[k] for k in ('return_pct','max_drawdown_pct','cycles','fees')}))
 with (OUT/'summary.csv').open('w') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
 attribution={}
 for period,runs in data['results'].items():
  attribution[period]={}
  for label in ('swing_baseline','swing_regime_gate','swing_gate_controls','combined_baseline'):
   logs=[x for x in runs[label]['cycle_log'] if x['model'].startswith('swing_trend')]
   baseline={x['entry']:x for x in runs['swing_baseline']['cycle_log']}
   current={x['entry']:x for x in logs}
   attribution[period][label]=dict(cycles=len(logs),pnl=sum(x['pnl'] for x in logs),
      matched_entry_times=len(baseline.keys()&current.keys()),
      missing_baseline_entries=sorted(baseline.keys()-current.keys()),
      new_entry_times=sorted(current.keys()-baseline.keys()))
 (OUT/'swing_attribution.json').write_text(json.dumps(attribution,indent=2))
 (OUT/'verification.json').write_text(json.dumps(dict(runs=len(rows),hashes='PASS',independent_ledgers='PASS',monthly_and_cycle_reconciliation='PASS',six_standalone_baseline_matches='PASS',limitations='Entry timestamp overlap is not a full rejection-reason trace. Real fill probability is unverified.'),indent=2))
 print(json.dumps(attribution,indent=2))
if __name__=='__main__':main()
