"""Read-only Q004 evaluation; missing observations never become flat returns."""
from collections import Counter
from datetime import datetime, timedelta, timezone
from fractions import Fraction as F
import hashlib
import json
import math
from pathlib import Path
from urllib.parse import urlparse, parse_qs


def load(p): return json.loads(p.read_text())
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def stamp(s):
    t=datetime.fromisoformat(s.replace('Z','+00:00'))
    if t.tzinfo is None: raise ValueError('timezone missing')
    return t.astimezone(timezone.utc)
def need(condition, message):
    if not condition: raise ValueError(message)
def close(a,b):
    need(math.isfinite(float(a)) and math.isfinite(float(b)) and abs(float(a)-float(b))<=1e-8,'numeric mismatch')
def bound_files(folder, mapping):
    need(bool(mapping),'empty artifact map')
    for name,h in mapping.items():
        need(Path(name).name==name,'unsafe artifact name')
        need(sha(folder/name)==h,'artifact hash mismatch: '+name)


def publication(day,b,registration_hash,reg,as_of):
    p=day/'publish';r=load(p/'forecast.json');receipt=load(p/'publication_receipt.json')
    need(receipt['status']=='PUBLISHED_BEFORE_TARGET','invalid publication status')
    committed=stamp(receipt['committed_at_utc'])
    need(b+timedelta(seconds=5)<=stamp(r['created_at_utc'])<=committed<=b+timedelta(seconds=50),'late/early publication')
    need(committed<=as_of,'publication beyond assessment time')
    need(r['boundary']==b.isoformat(),'forecast boundary')
    need(stamp(r['entry_time'])==b+timedelta(minutes=1) and stamp(r['exit_time'])==b+timedelta(days=1),'target interval')
    need(receipt['target_start_utc']==r['entry_time'],'receipt target')
    need(r['registration_sha256']==registration_hash and receipt['forecast_sha256']==sha(p/'forecast.json'),'publication binding')
    need(not r['actual_order'] and not r['outcome_observed'],'forecast scope')
    bound_files(p,r['input_hashes'])
    need(set(r['controls'])=={'MEAN180','ZERO'} and r['controls']['ZERO']==0,'controls')
    prediction=float(r['prediction_bps']);threshold=float(r['threshold_bps'])
    need(math.isfinite(prediction) and math.isfinite(threshold) and threshold>0,'forecast values')
    need(set(r['selectors'])==set(reg['policy']['event_selectors']),'selector set')
    for name,m in reg['policy']['event_selectors'].items():
        side=(1 if prediction>0 else -1) if abs(prediction)>m*threshold else 0
        need(r['selectors'][name]==side,'selector changed')
    audit=load(day/'verification.json')
    need(audit['status']=='PASS' and audit['boundary']==b.isoformat(),'publication audit')
    for key,file in [('registration',day.parent/'registration.json'),('forecast',p/'forecast.json'),('publication_receipt',p/'publication_receipt.json')]:
        need(audit['artifacts'][key]==sha(file),'publication audit binding')
    return r,receipt


def audit_outcome(day,b,record,receipt,reg,as_of):
    folder=day/'score';out=load(folder/'outcome.json')
    mature=b+timedelta(days=1,minutes=1)
    need(mature<=stamp(out['scored_at_utc'])<=as_of,'premature/future score')
    need(out['status']=='UNIT_EVENT_PROXY_NOT_ACCOUNT_OR_REAL_FILL' and out['boundary']==b.isoformat(),'outcome identity')
    need(out['forecast_sha256']==receipt['forecast_sha256'],'outcome forecast binding')
    bound_files(folder,out['artifacts'])
    receipts=sorted(folder.glob('*.receipt.json'))
    need(len(receipts)==out['requests']==4,'score request count')
    need(set(out['artifacts'])=={p.name for p in receipts}|{p.name.replace('.receipt.','.raw.') for p in receipts},'score artifact coverage')
    prices={};funding=None;clocks=0
    entry=int((b+timedelta(minutes=1)).timestamp()*1000);exit=int((b+timedelta(days=1)).timestamp()*1000)
    for rp in receipts:
        r=load(rp);raw=rp.with_name(rp.name.replace('.receipt.','.raw.'));data=load(raw)
        need(r['status']==200 and sha(raw)==r['sha256'],'raw receipt')
        need(mature.timestamp()<=r['requested_epoch']<=r['received_epoch']<=stamp(out['scored_at_utc']).timestamp(),'request timing')
        need(abs(r['wall_monotonic_drift_seconds'])<=.1,'clock drift')
        url=urlparse(r['url']);params=parse_qs(url.query)
        need(url.scheme=='https' and url.netloc=='fapi.binance.com','source host')
        if url.path=='/fapi/v1/time':
            need(data['serverTime']>=int(mature.timestamp()*1000),'server maturity')
            need(abs(data['serverTime']/1000-(r['requested_epoch']+r['received_epoch'])/2)<=1 and r['elapsed_seconds']<=3,'server clock')
            clocks+=1
        elif url.path=='/fapi/v1/klines':
            need(params['symbol']==['BTCUSDC'] and params['interval']==['1m'],'price identity')
            start=int(params['startTime'][0]);end=int(params['endTime'][0])
            need(start in (entry,exit) and start not in prices and end==start+59999,'price target')
            need(len(data)==1 and len(data[0])==12 and data[0][0]==start and data[0][6]==end,'price row')
            o,h,l,c=[F(x) for x in data[0][1:5]]
            need(min(o,h,l,c)>0 and l<=min(o,c)<=max(o,c)<=h,'price geometry')
            prices[start]=o
        elif url.path=='/fapi/v1/fundingRate':
            need(funding is None and params['symbol']==['BTCUSDC'],'funding identity')
            need(int(params['startTime'][0])==entry-86400000 and int(params['endTime'][0])==exit+59999,'funding range')
            funding=data
        else: raise ValueError('unexpected endpoint')
    need(clocks==1 and set(prices)=={entry,exit} and funding is not None,'outcome sources incomplete')
    times=[e['fundingTime'] for e in funding]
    need(0<len(times)<1000 and times==sorted(set(times)),'funding order/count')
    need(entry-86400000<=times[0]<=entry and exit<=times[-1]<=exit+59999,'funding endpoints')
    need(all(v-u<=28801000 for u,v in zip(times,times[1:])),'funding gap')
    for e in funding:
        need(e['symbol']=='BTCUSDC' and F(e['markPrice'])>0,'funding fields')
        F(e['fundingRate'])
    a,z=prices[entry],prices[exit];target=(z/a-1)*10000
    close(out['target_bps'],target)
    estimates=dict(PRICE=record['prediction_bps'],**record['controls'])
    need(set(out['prediction_errors'])==set(estimates),'error set')
    for key,p in estimates.items():close(out['prediction_errors'][key],F(str(p))-target)
    need(set(out['events'])==set(record['selectors']),'event set')
    net={}
    for name,side in record['selectors'].items():
        need(set(out['events'][name])==set(reg['policy']['cost_scenarios']),'cost set')
        net[name]={}
        for cost,policy in reg['policy']['cost_scenarios'].items():
            fee=F(str(policy['fee_bps']))/10000;slip=F(str(policy['slippage_bps']))/10000;extra=F(str(policy['extra_funding_bps_per_settlement']))/10000
            tick=F(reg['policy']['price_tick'])
            def fill(p,d):
                units=p*(1+d*slip)/tick
                return (math.ceil(units) if d>0 else math.floor(units))*tick
            pa,pz=fill(a,side),fill(z,-side)
            gross=side*(z-a);execution=gross-side*(pz-pa);fees=(pa+pz)*fee
            paid=sum((F(e['markPrice'])*(side*F(e['fundingRate'])+extra) for e in funding if entry<((e['fundingTime']+59999)//60000)*60000<=exit),F(0))
            expected=dict(gross_bps=gross,execution_bps=execution,fees_bps=fees,funding_bps=paid,net_bps=gross-execution-fees-paid)
            if not side:expected={key:F(0) for key in expected}
            need(set(out['events'][name][cost])==set(expected),'cost components')
            for key,val in expected.items():close(out['events'][name][cost][key],val/a*10000)
            net[name][cost]=float(expected['net_bps']/a*10000)
    return dict(boundary=b.isoformat(),target_bps=float(target),estimates=estimates,selectors=record['selectors'],net_bps=net)


def aggregate(rows,selectors,costs):
    n=len(rows);models={};events={}
    for model in ('PRICE','MEAN180','ZERO'):
        errors=[float(r['estimates'][model])-r['target_bps'] for r in rows]
        models[model]=dict(n=n,mse_bps2=math.fsum(x*x for x in errors)/n if n else None,
            mae_bps=math.fsum(abs(x) for x in errors)/n if n else None,
            mean_prediction_minus_target_bps=math.fsum(errors)/n if n else None)
    for selector in selectors:
        active=[r for r in rows if r['selectors'][selector]!=0]
        events[selector]=dict(scored_days=n,active_events=len(active),flat_days=n-len(active),costs={})
        for cost in costs:
            values=[r['net_bps'][selector][cost] for r in rows]
            events[selector]['costs'][cost]=dict(sum_unit_event_bps=math.fsum(values) if n else None,
                mean_per_scored_day_bps=math.fsum(values)/n if n else None,
                mean_per_active_event_bps=math.fsum(r['net_bps'][selector][cost] for r in active)/len(active) if active else None)
    return dict(forecast_metrics=models,event_metrics=events,
        price_mse_minus_control_bps2={m:models['PRICE']['mse_bps2']-models[m]['mse_bps2'] if n else None for m in ('MEAN180','ZERO')},
        units='Unit-event bp sums are not compounded returns or account USDC profit.')


def evaluate(root,folder,as_of):
    reg=load(folder/'registration.json');registration_hash=sha(folder/'registration.json')
    need(load(folder/'ready.json')['registration_sha256']==registration_hash,'registration ready binding')
    for name,h in {**reg['protected_hashes'],**reg['source_hashes']}.items():need(sha(root/name)==h,'frozen source mismatch')
    first=stamp(reg['policy']['first_boundary_utc']);states=[];rows=[]
    for i in range(reg['policy']['calendar_days']):
        b=first+timedelta(days=i);day=folder/b.strftime('%Y-%m-%d')
        state='FUTURE' if as_of<b else 'PUBLICATION_WINDOW' if as_of<=b+timedelta(seconds=50) else 'MISSED_PUBLICATION'
        item=dict(boundary=b.isoformat(),status=state)
        if (day/'publish/publication_receipt.json').exists():
            try:r,receipt=publication(day,b,registration_hash,reg,as_of)
            except (ValueError,KeyError,OSError,TypeError) as e:item.update(status='INVALID_PUBLICATION',reason=str(e))
            else:
                item['status']='PENDING_OUTCOME' if as_of<b+timedelta(days=1,minutes=1) else 'UNRESOLVED_OUTCOME'
                if (day/'score/outcome.json').exists():
                    try:row=audit_outcome(day,b,r,receipt,reg,as_of)
                    except (ValueError,KeyError,OSError,TypeError,ZeroDivisionError) as e:item.update(status='INVALID_OUTCOME',reason=str(e))
                    else:rows.append(row);item['status']='SCORED_VERIFIED_UNIT_PROXY'
        elif (day/'score/outcome.json').exists():item.update(status='INVALID_OUTCOME',reason='outcome without publication')
        states.append(item)
    counts=dict(Counter(x['status'] for x in states))
    return dict(checked_at_utc=as_of.isoformat(),scheduled_boundaries=reg['policy']['calendar_days'],counts=counts,
        observed_scored_days=len(rows),integrity_errors=sum(v for k,v in counts.items() if k.startswith('INVALID')),
        states=states,metrics=aggregate(rows,reg['policy']['event_selectors'],reg['policy']['cost_scenarios']),
        automatic_adoption=False,account_profit_usdc=None,loss_5pct_verified=False,
        rule_end_unchanged=True,automatic_schedule_created=False)
