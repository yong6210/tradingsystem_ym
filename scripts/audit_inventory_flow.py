"""Independent Decimal audit of E053 inventory fills, funding and equity identity."""
from pathlib import Path
import json,hashlib
from decimal import Decimal as D, ROUND_FLOOR, ROUND_CEILING
ROOT=Path(__file__).resolve().parents[1];P=ROOT/'reports/validation/e053_inventory_flow_20260919'
def read(p):return json.loads(p.read_text())
def lines(p):return [json.loads(x) for x in p.read_text().splitlines()]
def near(a,b):
    if abs(D(str(a))-D(str(b)))>D('0.000001'):raise AssertionError((a,b))
def main():
    reg=read(P/'registration.json');c=reg['config']
    for path,h in reg['source_hashes'].items():assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==h
    originals={}
    manifest=read(ROOT/'data/historical/btcusdc_public_20260917/manifest.json')
    for item in manifest['funding_sources']:
        path=ROOT/item['path'];assert hashlib.sha256(path.read_bytes()).hexdigest()==item['sha256']
        for row in read(path):originals[row['fundingTime']]=row
    import pandas as pd
    for fit in read(P/'ridge_training.json'):
        assert pd.Timestamp(fit['last_label_maturity']) < pd.Timestamp(fit['month'])-pd.Timedelta(days=1)
    checked=[]
    for summary_file,folder in [('continuous_summary.json',P),('monthly_summary.json',P/'monthly_trials')]:
        for r in read(P/summary_file):
            rows=lines(folder/(r['case']+'_ledger.jsonl'));daily=lines(folder/(r['case']+'_daily.jsonl'))
            cash=D(1000);q=D(0);avg=D(0);gross_total=D(0);fees=D(0);funding=D(0);operating=D(0);fills=0
            slip=D(str(c['costs'][r['cost']]['slippage_bps']))/10000;tick=D(str(c['tick']));fee=D(str(c['fee_bps']))/10000
            for e in rows:
                delta=D(str(e['cash_delta']))
                if e['kind']=='fill':
                    fills+=1;old=D(str(e['old_qty']));new=D(str(e['new_qty']));change=D(str(e['delta_qty']));ref=D(str(e['reference']))
                    near(old,q);near(e['old_avg'],avg);near(new-old,change);assert old*new>=0
                    direction=1 if change>0 else -1
                    expected=(ref*(1+D(direction)*slip)/tick).to_integral_value(rounding=ROUND_CEILING if direction>0 else ROUND_FLOOR)*tick
                    near(expected,e['price']);price=D(str(e['price']));charged=abs(change)*price*fee
                    near(charged,e['fee']);fees+=charged
                    if abs(new)<abs(old):gross=abs(change)*(price-avg)*(1 if old>0 else -1)
                    else:
                        gross=D(0);avg=(abs(old)*avg+abs(change)*price)/abs(new)
                    if not new:avg=D(0)
                    near(avg,e['new_avg']);near(gross,e['gross']);near(delta,gross-charged)
                    q=new;gross_total+=gross
                    # Float storage has sub-ulp noise; no upward quantity rounding allowed.
                    units=abs(q)/D(str(c['lot_step']));near(units,units.to_integral_value())
                    if abs(new)>abs(old):assert abs(change)*ref>=D(str(c['min_notional']))-D('0.000001')
                elif e['kind']=='funding':
                    original=originals[e['time_ms']];near(original['fundingRate'],e['rate']);near(original['markPrice'],e['mark']);near(e['qty'],q)
                    expected=-q*D(str(e['mark']))*D(str(e['rate']))-abs(q)*D(str(e['mark']))*D(str(e['extra']))
                    near(delta,expected);funding+=delta
                elif e['kind']=='operating':near(delta,-r['monthly_operating_cost']);operating-=delta
                else:raise AssertionError(e['kind'])
                cash+=delta;near(cash,e['cash'])
            near(q,0);near(cash-1000,r['net_usdc']);near(gross_total,r['gross_realized_usdc']);near(fees,r['fees_usdc']);near(funding,r['funding_net_usdc']);near(operating,r['operating_cost_usdc'])
            near(gross_total-fees+funding-operating,r['net_usdc']);near(daily[-1]['equity'],cash)
            compounded=D(1)
            for v in r['monthly'].values():compounded*=D(str(v['end']))/D(str(v['start']))
            near(compounded,cash/1000)
            checked.append({'case':r['case'],'fills':fills,'status':'PASS'})
    result={'status':'PASS','accounts':len(checked),'fills':sum(x['fills'] for x in checked),'checks':checked,'scope':'Independent Decimal position-average, partial/short/flip realized PnL, adverse fills, fees, raw funding, cash and monthly compounding. Causality and state transitions tested with synthetic inputs. Not independent reconstruction of all market decisions or intraminute mark chronology; no live execution or liquidation validation.'}
    (P/'verification.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k!='checks'},indent=2))
if __name__=='__main__':main()
