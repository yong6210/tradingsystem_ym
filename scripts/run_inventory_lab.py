"""Register and run all E052 hypotheses without best-result selection."""
from pathlib import Path
import sys,json,hashlib,argparse,unittest
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import pandas as pd
from app.research.data.btcusdc import load_public_bundle
from app.research.diagnostics.inventory_lab import build_features,fit_monthly_ridge,simulate,FAMILIES
P=ROOT/'reports/validation/e052_inventory_lab_20260919'
def save(p,x):p.write_text(json.dumps(x,indent=2,allow_nan=False)+'\n')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def lines(p,rows):p.write_text(''.join(json.dumps(x,allow_nan=False)+'\n' for x in rows))
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--register',action='store_true');args=parser.parse_args();P.mkdir(parents=True,exist_ok=True)
    cp=ROOT/'configs/research/e052_inventory_lab.json';c=json.loads(cp.read_text())
    sources=[cp,Path(__file__),ROOT/'app/research/diagnostics/inventory_lab.py',ROOT/'tests/test_inventory_lab.py',ROOT/'app/research/diagnostics/intraday_inventory_v1.py',ROOT/'app/research/data/btcusdc.py',ROOT/'app/research/data/minutes.py']
    data=ROOT/'data/historical/btcusdc_public_20260917';sources += [data/n for n in ['manifest.json','validated_overlay.json','gap_probe_manifest.json']]
    sources += [ROOT/'reports/validation/e051_inventory_location_20260919'/n for n in ['monthly_summary.json','verification.json']]
    if args.register:
        if (P/'registration.json').exists():raise ValueError('already registered')
        save(P/'registration.json',{'registered_at':datetime.now(timezone.utc).isoformat(),'config':c,'source_hashes':{str(p.relative_to(ROOT)):sha(p) for p in sources},'classification':'REUSED_HISTORY_EXPLORATION_ALL_SIX_FAMILIES','orders':0});print('registered');return
    reg=json.loads((P/'registration.json').read_text())
    for p,h in reg['source_hashes'].items():assert sha(ROOT/p)==h,p
    if (P/'continuous_summary.json').exists():raise ValueError('no overwrite')
    with (P/'tests.log').open('w') as fp:r=unittest.TextTestRunner(stream=fp,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromName('tests.test_inventory_lab'))
    if not r.wasSuccessful():raise ValueError('tests failed')
    print('Loading verified minute bundle',flush=True);b=load_public_bundle(ROOT,data);b.require_complete_window(c['start'],c['end'])
    print('Features and purged monthly ridge fits',flush=True);f=build_features(b.trade);logs=fit_monthly_ridge(b.trade,f,c['start'],c['end']);save(P/'ridge_training.json',logs)
    events={((int(e['fundingTime'])+59999)//60000)*60000:{'time_ms':int(e['fundingTime']),'mark':float(e['markPrice']),'rate':float(e['fundingRate'])} for e in b.funding}
    window=f.loc[(f.index>=pd.Timestamp(c['start']))&(f.index<pd.Timestamp(c['end']))]
    save(P/'data_quality.json',{'minutes':len(window),'feature_nonfinite_rows':int(window.isna().any(axis=1).sum()),'features_sha256':hashlib.sha256(pd.util.hash_pandas_object(window,index=True).values.tobytes()).hexdigest(),'ridge_models':len(logs)})
    def run(folder,key,family,policy,cost,left,right,halt=True):
        r,l,d,cs=simulate(b.trade,b.mark,f,events,c,family,policy,cost,c['monthly_operating_cost'],left,right,halt);r['case']=key
        for name,rows in [('ledger',l),('daily',d),('campaigns',cs)]:lines(folder/f'{key}_{name}.jsonl',rows)
        return r
    continuous=[]
    for family in FAMILIES:
        for policy in ['inventory','fixed_core']:
            for cost in c['costs']:
                key=f'{family}_{policy}_{cost}';print(key,flush=True);continuous.append(run(P,key,family,policy,cost,c['start'],c['end']))
    save(P/'continuous_summary.json',continuous)
    monthly=[];folder=P/'monthly_trials';folder.mkdir(exist_ok=True);months=pd.date_range(c['start'],c['end'],freq='MS')
    for left,right in zip(months[:-1],months[1:]):
        print('Month',left.isoformat(),flush=True)
        for family in FAMILIES:
            for policy in ['inventory','fixed_core']:
                for cost in c['costs']:
                    key=f'{left.strftime("%Y-%m")}_{family}_{policy}_{cost}';monthly.append(run(folder,key,family,policy,cost,left,right))
    save(P/'monthly_summary.json',monthly)
    diagnostics=[];folder=P/'diagnostic20';folder.mkdir(exist_ok=True)
    for family in FAMILIES:
        key=f'{family}_inventory_stress_diagnostic20';print(key,flush=True);diagnostics.append(run(folder,key,family,'inventory','stress','2026-08-01T00:00Z',c['end'],False))
    save(P/'diagnostic_summary.json',diagnostics);print('DONE',len(continuous),len(monthly),len(diagnostics),flush=True)
if __name__=='__main__':main()
