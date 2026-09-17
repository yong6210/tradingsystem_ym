"""Frozen-model backward-time validation on newly supplied 2023/24 data."""
from pathlib import Path
from zipfile import ZipFile
import hashlib,json,sys
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.research.multistrategy_audit import Model,feature_bank,signals
from app.research.multistrategy import Costs
from app.research.recycling_portfolio import Sleeve,simulate
from scripts.run_multistrategy_research import dump

def main():
 out=ROOT/'reports/validation/additional_btc_2023_2024_20260917';out.mkdir(exist_ok=True)
 if (out/'results.json').exists():raise SystemExit('Refuse overwrite')
 old=json.loads((ROOT/'reports/validation/recycling_portfolio_20260917/protocol.json').read_text())
 for p,sha in old['hashes'].items():assert hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==sha,p
 mp=ROOT/'data/historical/btcusdt_2023_2024_oct_additional/manifest.json';manifest=json.loads(mp.read_text());assert manifest['status']=='PASS'
 plan=dict(old)
 plan.update(status='FROZEN_MODEL_NEWLY_SUPPLIED_EARLIER_PERIOD_BACKTEST_NOT_FORWARD_OOS',
    periods={'2023':['2023-02-04','2024-01-01'],'2024_Jan_Oct':['2024-01-01','2024-11-01']},
    additional_manifest_sha256=hashlib.sha256(mp.read_bytes()).hexdigest(),
    omitted='2024-11 not supplied; 2024-12 validated separately but not bridged across missing November. Standalone December is shorter than unchanged 34-day warmup.',
    source_protocol='reports/validation/recycling_portfolio_20260917/protocol.json',
    interpretation='Models selected using later 2025/26 data: new dataset for this experiment, not chronologically forward out-of-sample.',
    runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
 dump(out/'protocol.json',plan)
 frames=[]
 for record in manifest['files']:
  p=Path(record['path']);assert hashlib.sha256(p.read_bytes()).hexdigest()==record['sha256']
  with ZipFile(p) as z:
   with z.open(p.stem+'.csv') as f:d=pd.read_csv(f,header=None,usecols=range(6),names=['ts','o','h','l','c','v'])
  if str(d.iloc[0]['ts'])=='open_time':d=d.iloc[1:].copy()
  ts=d.pop('ts').astype('int64');ts=np.where(ts>=100_000_000_000_000,ts//1000,ts)
  d.index=pd.to_datetime(ts,unit='ms',utc=True);frames.append(d.astype(float))
 minutes=pd.concat(frames)
 assert len(minutes)==manifest['row_count'] and not minutes.index.has_duplicates
 assert (np.diff(minutes.index.asi8)==60_000_000_000).all() and np.isfinite(minutes.to_numpy()).all()
 bank=feature_bank(minutes)
 names=sorted({s['model'] for c in plan['cases'] for s in c['sleeves']})
 sets={n:signals(minutes,bank,Model(n.rsplit('_v',1)[0],int(n.rsplit('_v',1)[1])),family_exits=True) for n in names}
 results={}
 for period,dates in plan['periods'].items():
  results[period]={}
  for case in plan['cases']:
   specs=[Sleeve(**s) for s in case['sleeves']]
   r=simulate(minutes,sets,bank['regime'],*dates,specs,costs=Costs(**case['costs']))
   results[period][case['name']]=r;dump(out/'partial.json',results)
   print(period,case['name'],round(r['return_pct'],4),round(r['max_drawdown_bound_pct'],4),flush=True)
 dump(out/'results.json',dict(protocol=plan,results=results))
if __name__=='__main__':main()
