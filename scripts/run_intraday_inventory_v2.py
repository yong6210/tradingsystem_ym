"""E051 fixed location rules, source registration, BTC minute inventory account study."""
from pathlib import Path
import sys,json,hashlib,argparse,unittest
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import pandas as pd
from app.research.data.btcusdc import load_public_bundle
from app.research.diagnostics.intraday_inventory_v2 import features,simulate
OUT=ROOT/'reports/validation/e051_inventory_location_20260919'
CONFIG=ROOT/'configs/research/e051_inventory_location_v2.json'
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,obj):p.write_text(json.dumps(obj,indent=2,allow_nan=False)+'\n')
def lines(p,rows):p.write_text(''.join(json.dumps(r,allow_nan=False)+'\n' for r in rows))
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--register',action='store_true');args=ap.parse_args();OUT.mkdir(parents=True,exist_ok=True)
    c=json.loads(CONFIG.read_text())
    sources=[CONFIG,Path(__file__),ROOT/'app/research/diagnostics/intraday_inventory_v2.py',ROOT/'tests/test_intraday_inventory_v2.py',ROOT/'app/research/data/btcusdc.py',ROOT/'app/research/data/minutes.py']
    data=ROOT/'data/historical/btcusdc_public_20260917'
    sources+=[data/n for n in ['manifest.json','validated_overlay.json','gap_probe_manifest.json']]
    baseline=ROOT/'reports/validation/e050_inventory_intraday_20260919'
    sources += [baseline/n for n in ['continuous_summary.json','monthly_summary.json','verification.json']]
    sources += [OUT/'e050_diagnosis.json']
    if args.register:
        if (OUT/'registration.json').exists():raise ValueError('already registered')
        save(OUT/'registration.json',{'registered_at':datetime.now(timezone.utc).isoformat(),'config':c,'source_hashes':{str(p.relative_to(ROOT)):digest(p) for p in sources},'classification':'EXPLORATORY_REUSED_HISTORY','live_orders':0})
        print('registered');return
    reg=json.loads((OUT/'registration.json').read_text())
    for p,h in reg['source_hashes'].items():
        if digest(ROOT/p)!=h:raise ValueError('changed registered source '+p)
    if (OUT/'continuous_summary.json').exists():raise ValueError('existing results cannot be overwritten')
    with (OUT/'tests.log').open('w') as fp:
        r=unittest.TextTestRunner(stream=fp,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromName('tests.test_intraday_inventory_v2'))
    if not r.wasSuccessful():raise ValueError('tests failed')
    print('Loading hash-verified minute trade/mark/index bundle',flush=True)
    b=load_public_bundle(ROOT,data);b.require_complete_window(c['start'],c['end'])
    print('Computing completed 1m / 3m / 1h / 4h features',flush=True);f=features(b.trade)
    event={}
    for e in b.funding:
        stamp=((int(e['fundingTime'])+59999)//60000)*60000
        if stamp in event:raise ValueError('funding time collision')
        event[stamp]={'time_ms':int(e['fundingTime']),'mark':float(e['markPrice']),'rate':float(e['fundingRate'])}
    window=f.loc[(f.index>=pd.Timestamp(c['start']))&(f.index<pd.Timestamp(c['end']))]
    save(OUT/'data_quality.json',{'minutes':len(window),'feature_nonfinite_rows':int(window.isna().any(axis=1).sum()),'all_trade_mark_index_minutes_validated':True,'data_manifest_hash':digest(data/'manifest.json'),'features_digest':hashlib.sha256(pd.util.hash_pandas_object(window,index=True).values.tobytes()).hexdigest()})
    continuous=[];monthly=[]
    for cap in c['exposure_caps']:
        for policy in ['inventory','fixed_core']:
            for cost in c['costs']:
                for op in c['monthly_operating_costs']:
                    key=f'{policy}_{cap}x_{cost}_op{op}'; print(key,flush=True)
                    r,l,d,cs=simulate(b.trade,b.mark,f,event,c,cap,cost,op,policy,c['start'],c['end']);r['case']=key;continuous.append(r)
                    for name,rows in [('ledger',l),('daily',d),('campaigns',cs)]:lines(OUT/f'{key}_{name}.jsonl',rows)
    save(OUT/'continuous_summary.json',continuous)
    months=pd.date_range(c['start'],c['end'],freq='MS')
    folder=OUT/'monthly_trials';folder.mkdir(exist_ok=True)
    for left,right in zip(months[:-1],months[1:]):
        print('Independent month',left.isoformat(),flush=True)
        for policy in ['inventory','fixed_core']:
            for cost in c['costs']:
                for op in c['monthly_operating_costs']:
                    key=f'{left.strftime("%Y-%m")}_{policy}_{c["primary_cap"]}x_{cost}_op{op}'
                    r,l,d,cs=simulate(b.trade,b.mark,f,event,c,c['primary_cap'],cost,op,policy,left,right);r['case']=key;monthly.append(r)
                    for name,rows in [('ledger',l),('daily',d),('campaigns',cs)]:lines(folder/f'{key}_{name}.jsonl',rows)
    save(OUT/'monthly_summary.json',monthly)
    print('DONE',len(continuous),len(monthly),flush=True)
if __name__=='__main__':main()
