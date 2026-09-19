"""Resolve the first OHLC-ambiguous zone visit with original executed trades."""
from pathlib import Path
import hashlib
import json
from zipfile import ZipFile
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/validation/frozen_zone_path_48h_20260919'


def main():
    events=[json.loads(x) for x in (OUT/'events.jsonl').read_text().splitlines()]
    event=next(e for e in events if 'both_boundaries_in_range_sequence_unknown' in e['labels'])
    end=event['bar_end_ms']; start=end-60000
    folder=ROOT/'data/historical/btcusdc_aggprofiles_20260919'
    archive=folder/'BTCUSDC-aggTrades-2026-08.zip'
    expected=next(r['sha256'] for r in json.loads((folder/'manifest.json').read_text())['archives'] if r['file']==archive.name)
    digest=hashlib.sha256()
    with archive.open('rb') as fp:
        for block in iter(lambda:fp.read(1024*1024),b''):
            digest.update(block)
    assert digest.hexdigest()==expected
    pieces=[]
    with ZipFile(archive) as z,z.open(z.namelist()[0]) as stream:
        for chunk in pd.read_csv(stream,usecols=['agg_trade_id','price','quantity','transact_time'],chunksize=400000):
            rows=chunk[(chunk.transact_time>=start)&(chunk.transact_time<end)]
            if len(rows):pieces.append(rows)
            if chunk.transact_time.iloc[-1]>=end:break
    trades=pd.concat(pieces,ignore_index=True)
    assert (trades.agg_trade_id.diff().dropna()==1).all()
    assert (trades.transact_time.diff().dropna()>=0).all()
    actual=dict(open=float(trades.price.iloc[0]),bar_high=float(trades.price.max()),
                bar_low=float(trades.price.min()),close=float(trades.price.iloc[-1]))
    assert all(abs(actual[k]-float(event[k]))<1e-8 for k in actual)
    low,high=float(event['low']),float(event['high'])
    previous=None; transitions=[]
    for row in trades.itertuples(index=False):
        state='below' if row.price<low else 'above' if row.price>high else 'inside'
        if state!=previous:
            transitions.append(dict(agg_trade_id=int(row.agg_trade_id),time_ms=int(row.transact_time),
                                    price=float(row.price),position=state))
            previous=state
    result=dict(event_available_ms=end,zone_id=event['zone_id'],trades=len(trades),
                ohlc_matches_minute=True,actual=actual,position_transitions=transitions,
                archive_sha256=expected,script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                interpretation='Executed price sequence only; neither resting liquidity nor approved trading signal.',orders=0)
    trades.to_csv(OUT/'intrabar_trades.csv',index=False)
    (OUT/'intrabar_trade_check.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))


if __name__=='__main__':main()
