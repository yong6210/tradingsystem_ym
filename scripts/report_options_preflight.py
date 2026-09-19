"""Offline Q007 source reconciliation and bounded preflight report."""
from datetime import datetime, timezone
from decimal import Decimal as D
from fractions import Fraction as F
from pathlib import Path
import hashlib
import json
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/validation/q007_options_preflight_20260919'
def load(name):return json.loads((OUT/name).read_text())
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def save(name,x):
    with (OUT/name).open('x') as f:json.dump(x,f,ensure_ascii=False,indent=2,default=str);f.write('\n')


def main():
    reg=load('registration.json');s=load('selection.json');c=load('quote_components.json')
    for name,h in reg['frozen_hashes'].items():assert sha(ROOT/name)==h,name
    receipts=sorted(OUT.glob('*_receipt.json'))
    assert len(receipts)==reg['public_get_budget']==8
    for p in receipts:
        receipt=json.loads(p.read_text())
        raw=OUT/(p.name.replace('_receipt',''))
        assert sha(raw)==receipt['sha256']
        assert receipt['status']==200
        assert receipt['requested_at_utc']>reg['registered_at_utc']
    timer=load('time_receipt.json');server=load('time.json')['serverTime']/1000
    assert timer['requested_epoch']<=server<=timer['received_epoch']
    ir=load('index_receipt.json');ix=load('index.json')
    index_age=ir['received_epoch']-ix['time']/1000
    assert -1<=index_age<=5
    # Rebuild selection from the full metadata, independent of saved selection.
    universe=load('exchange_info.json')['optionSymbols']
    expiry=[]
    for a in universe:
        t=datetime.fromtimestamp(a['expiryDate']/1000,timezone.utc)
        if a['underlying']=='BTCUSDT' and a['quoteAsset']=='USDT' and a['status']=='TRADING' and a['unit']==1 and t.weekday()==4 and t.hour==8 and t.minute==0 and t.second==0 and 7*86400000<=a['expiryDate']-s['server_time']<=14*86400000:
            expiry.append(a['expiryDate'])
    assert s['expiry']==min(expiry)
    uni=[a for a in universe if a['expiryDate']==s['expiry'] and a['underlying']=='BTCUSDT' and a['quoteAsset']=='USDT' and a['status']=='TRADING' and a['unit']==1]
    calls={F(a['strikePrice']) for a in uni if a['side']=='CALL'}
    puts={F(a['strikePrice']) for a in uni if a['side']=='PUT'}
    spot,q=F(s['index']),F(s['quantity'])
    k=min(calls&puts,key=lambda x:(abs(x-spot),x))
    lo=max(x for x in puts if x<k);hi=min(x for x in calls if x>k)
    assert [k,lo,hi]==[F(s[n]) for n in ['central','lower','upper']]
    count=0
    marks={m['symbol']:m for m in load('marks.json')}
    rational_rows=[];ages=[]
    for i,(a,row) in enumerate(zip(s['legs'],c['rows'])):
        assert a['symbol']==row['symbol']
        assert (F(a['strikePrice']),a['side'])==[(k,'CALL'),(k,'PUT'),(lo,'PUT'),(hi,'CALL')][i]
        assert F(a['minQty'])<=q<=F(a['maxQty'])
        for f in a['filters']:
            if 'stepSize' in f:assert (q/F(f['stepSize'])).denominator==1
        book=load('depth_'+str(i)+'.json');receipt=load('depth_'+str(i)+'_receipt.json')
        sign=-1 if i<2 else 1
        levels=book['bids' if i<2 else 'asks']
        cum=F(0);cash=F(0)
        for p,n in levels:
            end=cum+F(n)
            cash+=F(p)*max(F(0),min(q,end)-min(q,cum))
            cum=end
        assert cum>=q
        price=cash/q
        pf=next(f for f in a['filters'] if f['filterType']=='PRICE_FILTER')
        # Every consumed depth price must be on the current tick and within bounds.
        cum=F(0)
        for p,n in levels:
            if cum>=q:break
            assert F(pf['minPrice'])<=F(p)<=F(pf['maxPrice'])
            assert (F(p)/F(pf['tickSize'])).denominator==1
            cum+=F(n)
        tick=F(pf['tickSize']);adverse=price+sign*tick
        fee=min(spot*F('0.00024'),price/10)*q
        afee=min(spot*F('0.00024'),adverse/10)*q
        mark=F(marks[a['symbol']]['markPrice'])
        otm=max(F(a['strikePrice'])-spot if i==0 else spot-F(a['strikePrice']),F(0))
        im=(max(spot/10,spot*F('.15')-otm)+mark)*q if i<2 else F(0)
        mm=(max(spot/F(20),spot*F('.075')-otm)+mark)*q if i<2 else F(0)
        expected=dict(vwap=price,entry_fee=fee,cashflow=-sign*cash,
            adverse_cashflow=-sign*adverse*q,adverse_entry_fee=afee,
            position_initial_margin=im,position_maintenance_margin=mm)
        for key,v in expected.items():assert F(row[key])==v,(i,key);count+=1
        rational_rows.append(expected)
        age=receipt['received_epoch']-book['T']/1000
        assert age==row['message_age_seconds']
        ages.append(age)
    assert q==max(F(a['minQty']) for a in s['legs']) # Exact common minimum for this selection.
    issues=['DEPTH_AGE_'+str(i) for i,age in enumerate(ages) if not -1<=age<=5]
    assert issues==c['quality_issues']
    credit=sum(r['cashflow'] for r in rational_rows);fees=sum(r['entry_fee'] for r in rational_rows)
    totals=dict(gross_credit=credit,entry_fees=fees,after_entry_fees_credit=credit-fees,
        adverse_tick_after_entry_fees_credit=sum(r['adverse_cashflow']-r['adverse_entry_fee'] for r in rational_rows),
        max_contractual_payoff_debit=q*max(k-lo,hi-k),
        contractual_worst_pnl_before_any_fees=credit-q*max(k-lo,hi-k),
        position_initial_margin=sum(r['position_initial_margin'] for r in rational_rows),
        position_maintenance_margin=sum(r['position_maintenance_margin'] for r in rational_rows))
    for key,v in totals.items():assert F(c[key])==v,key;count+=1
    # Illustrative settlement points, not realized observations or a probability model.
    scenarios=[]
    for settlement in [F(0),lo,k,hi,hi*2]:
        intrinsic=[max(settlement-k,F(0)),max(k-settlement,F(0)),max(lo-settlement,F(0)),max(settlement-hi,F(0))]
        payout=q*sum(sign*x for sign,x in zip([-1,-1,1,1],intrinsic))
        exercise=q*sum(min(settlement*F('.00015'),x/10) for x in intrinsic)
        dec=lambda x:str(D(x.numerator)/D(x.denominator))
        scenarios.append(dict(settlement=dec(settlement),contractual_payout=dec(payout),
            illustrative_exercise_fees=dec(exercise),conditional_pnl=dec(credit-fees+payout-exercise)))
    save('settlement_arithmetic.json',dict(kind='ILLUSTRATIVE_NOT_REALIZED_NOT_EXPECTED',rows=scenarios,
        tail='For S sufficiently above U, two call exercise fees are 2*q*0.00015*S; the bounded contractual payout is not an all-cost global loss bound.'))
    test=subprocess.run([sys.executable,'-m','unittest','tests.test_options_preflight','-v'],cwd=ROOT,capture_output=True,text=True)
    with (OUT/'tests.log').open('x') as f:f.write(test.stdout+test.stderr)
    assert test.returncode==0
    save('verification.json',dict(verified_at_utc=datetime.now(timezone.utc).isoformat(),
        tests=3,public_requests=8,raw_receipts_verified=8,frozen_hashes_unchanged=len(reg['frozen_hashes']),
        independent_fraction_value_checks=count,selected_legs=4,source_clock_bracket=True,index_age_seconds=index_age,
        stale_under_registered_gate=len(issues),rules_not_changed=True,
        unchecked=['Actual account eligibility/fees','Sequential order margin and liquidation path','Mark timestamps unavailable',
                   'Simultaneous execution','Historical options chain and order books','Expected profit','Account loss limit'],
        artifacts={p.name:sha(p) for p in OUT.iterdir() if p.is_file()}))
    save('progress_addendum.json',dict(status='Q007_PREFLIGHT_COMPLETE_DATA_INSUFFICIENT_NOT_PROMOTED',
        profit_verified=False,loss_preference_verified=False,performance_runs=0,orders=0,new_schedules=0,
        next='Q004_FIRST_MATURE_SCORE_AFTER_2026_09_20_00_01_UTC; NO_OPTIONS_RETRY_OR_PERFORMANCE_RUN'))
    print(json.dumps(dict(checks=count,protected=len(reg['frozen_hashes']),issues=issues)))


if __name__=='__main__':main()
