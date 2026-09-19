"""Source-price and volume checks beyond the independent cash-ledger audit."""
from pathlib import Path
import sys,json
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import numpy as np
import pandas as pd
from app.research.data.btcusdc import load_public_bundle
from app.research.diagnostics.inventory_lab import build_features
from app.research.diagnostics.inventory_flow import load_flow,build_flow_features

def main():
    directory=ROOT/'data/historical/btcusdc_public_20260917';b=load_public_bundle(ROOT,directory)
    source=b.trade;features=build_features(source);flow=load_flow(ROOT,directory,source.index);extended=build_flow_features(source,flow)
    summary={}
    for name,f in [('e052_inventory_lab_20260919',features),('e053_inventory_flow_20260919',extended)]:
        p=ROOT/'reports/validation'/name
        mask=(f.index>=pd.Timestamp('2024-09-01T00:00Z'))&(f.index<pd.Timestamp('2026-09-01T00:00Z'));window=f.loc[mask]
        missing=window.isna();bad=missing.any(axis=1)
        fills=0;zero_volume=[];participation=[];end_labels=0
        for file in p.rglob('*_ledger.jsonl'):
            for line in file.read_text().splitlines():
                e=json.loads(line)
                if e['kind']!='fill':continue
                fills+=1;t=pd.Timestamp(e['time_ms'],unit='ms',tz='UTC').floor('min');row=source.loc[t]
                expected=row.c if e['reason']=='end' else row.o
                if abs(expected-e['reference'])>1e-6:raise AssertionError((file.name,t,expected,e['reference']))
                if e['reason']=='end':end_labels+=1
                if row.v==0:zero_volume.append({'file':file.name,'time_ms':e['time_ms'],'reason':e['reason']})
                else:participation.append(abs(e['delta_qty'])/row.v)
        result={'fill_references_matched_to_raw_bars':fills,'end_rows_using_final_bar_open_label_with_close_price':end_labels,'zero_volume_fill_rows':zero_volume,'max_order_fraction_of_full_minute_volume':max(participation,default=0),'p95_order_fraction_of_full_minute_volume':float(np.quantile(participation,.95)) if participation else None,'orders_over_10pct_of_minute_volume':int(sum(v>.1 for v in participation)),'undefined_feature_rows':int(bad.sum()),'undefined_by_column':{k:int(v) for k,v in missing.sum().items() if v},'undefined_sample_times':window.index[bad][:10].astype(str).tolist(),'raw_rows_present_at_all_undefined_times':bool(window.index[bad].isin(source.index).all()),'note':'Undefined zero-denominator feature values remain missing; new decisions skipped, open risk still managed. Minute volume is a diagnostic, not queue depth or guaranteed capacity. End event clock is bar label; execution uses that final bar close.'}
        (p/'market_reference_audit.json').write_text(json.dumps(result,indent=2)+'\n');summary[name]={k:v for k,v in result.items() if k not in ['undefined_sample_times','note','zero_volume_fill_rows']};summary[name]['zero_volume_fill_rows']=len(zero_volume)
    print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
