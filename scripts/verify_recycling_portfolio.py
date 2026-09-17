"""Rebuild all sleeve ledgers from fills, independently of simulator accounts."""
from pathlib import Path
import csv,hashlib,json,math
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/validation/recycling_portfolio_20260917'
def main():
 data=json.loads((OUT/'results.json').read_text());rows=[];recycle={};run_count=0
 for path,expected in data['protocol']['hashes'].items():assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==expected,path
 for period,runs in data['results'].items():
  recycle[period]={}
  for name,r in runs.items():
   accounts={m:dict(qty=0.,avg=0.,side=0,balance=s['initial'],realized=0.,fees=0.,funding=0.) for m,s in r['sleeves'].items()}
   for e in r['events']:
    a=accounts[e['model']];price=e['price'];qty=e['qty'];action=e['action']
    if action=='funding':
     amount=qty*price*r['costs']['funding_bps']/10000;a['funding']+=amount;a['balance']-=amount
    elif action.endswith('_add'):
     assert not a['qty'] or a['side']==e['side']
     a['avg']=(a['qty']*a['avg']+qty*price)/(a['qty']+qty);a['qty']+=qty;a['side']=e['side']
    else:
     assert qty<=a['qty']+1e-8
     pnl=a['side']*qty*(price-a['avg']);a['realized']+=pnl;a['balance']+=pnl;a['qty']-=qty
     if a['qty']<1e-9:a['qty']=a['avg']=0.;a['side']=0
    if action.startswith('market_'):
     fee=qty*price*r['costs']['taker_bps']/10000;a['fees']+=fee;a['balance']-=fee
    assert math.isclose(a['balance'],e['balance'],abs_tol=1e-6),(period,name,e)
    assert math.isclose(a['qty'],e['remaining'],abs_tol=1e-8)
    assert math.isclose(a['avg'],e['average'],abs_tol=1e-6)
    if action.endswith('_add'):
     eq=sum(x['balance']+x['side']*x['qty']*(price-x['avg']) for x in accounts.values())
     assert sum(x['qty'] for x in accounts.values())*price<=eq+1e-6
   for m,a in accounts.items():
    saved=r['sleeves'][m];assert a['qty']==0
    for source,target in [('balance','final'),('realized','realized'),('fees','fees'),('funding','funding')]:
     assert math.isclose(a[source],saved[target],abs_tol=1e-6),(period,name,m,source)
    assert math.isclose(sum(x['pnl'] for x in saved['cycles']),saved['pnl'],abs_tol=1e-6)
   total=sum(a['balance'] for a in accounts.values());assert math.isclose(total,r['final_equity'],abs_tol=1e-6)
   assert math.isclose(math.prod(1+x for x in r['monthly'].values()),total/10000,abs_tol=1e-8)
   cycles=[x for s in r['sleeves'].values() for x in s['cycles']]
   recycled=[x for s in r['sleeves'].values() if 'inventory_rotation' in s['spec']['model'] for x in s['cycles'] if x['total_bought']>3*x['seed']+1e-8]
   recycle[period][name]=dict(recycled_cycles=len(recycled),cycles=len(cycles),sleeve_pnl={m:s['pnl'] for m,s in r['sleeves'].items()},
    fees=sum(s['fees'] for s in r['sleeves'].values()),funding=sum(s['funding'] for s in r['sleeves'].values()))
   rows.append(dict(period=period,case=name,return_pct=r['return_pct'],max_drawdown_bound_pct=r['max_drawdown_bound_pct'],cycles=len(cycles),recycled_cycles=len(recycled),gross_entry_exposure_peak=r['gross_entry_exposure_peak']))
   run_count+=1
 with (OUT/'summary.csv').open('w') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
 (OUT/'attribution.json').write_text(json.dumps(recycle,indent=2))
 checks=dict(runs=run_count,source_hashes='PASS',independent_event_balances_averages_quantities='PASS',fees_funding='PASS',
             gross_exposure_at_each_add='PASS',monthly_compounding='PASS',cycle_attribution='PASS',
             caveats='Accounting verified, not real exchange fill probability. Prior data reused; no independent holdout.')
 (OUT/'verification.json').write_text(json.dumps(checks,indent=2));print(json.dumps(checks))
if __name__=='__main__':main()
