"""Validate explicitly supplied 2023/24 archives, preserving gaps as failures."""
from pathlib import Path
import sys,json
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.prepare_local_kline_archives import prepare_archives

def main():
 paths=[Path('/Users/yumin/Downloads')/f'BTCUSDT-1m-{year}-{month:02d}.zip' for year in (2023,2024) for month in range(1,13) if (year,month)!=(2024,11)]
 missing=[str(p) for p in paths if not p.exists()]
 if missing:raise SystemExit(json.dumps({'missing_supplied_files':missing}))
 for label,subset in [('2023_2024_oct',paths[:-1]),('2024_dec',paths[-1:])]:
  out=ROOT/'data/historical'/f'btcusdt_{label}_additional'
  report=prepare_archives(subset,out)
  print(label,json.dumps({k:report[k] for k in ('status','file_count','row_count','start','end_exclusive','errors','error_examples')}),flush=True)
if __name__=='__main__':main()
