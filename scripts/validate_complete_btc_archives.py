"""Validate all explicitly supplied months, including restored November 2024."""
from pathlib import Path
import json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.prepare_local_kline_archives import prepare_archives
if __name__=='__main__':
 paths=[Path('/Users/yumin/Downloads')/f'BTCUSDT-1m-{y}-{m:02d}.zip' for y in (2023,2024,2025,2026) for m in range(1,13) if y<2026 or m<=8]
 r=prepare_archives(paths,ROOT/'data/historical/btcusdt_2023_2026_complete')
 print(json.dumps({k:r[k] for k in ('status','file_count','row_count','start','end_exclusive','errors','error_examples')}))
 if r['status']!='PASS':raise SystemExit(1)
