"""Q004 causal PRICE construction and unit-event scoring, never an account."""
from decimal import Decimal as D, ROUND_CEILING, ROUND_FLOOR
import math
import numpy as np
import pandas as pd
from app.research.diagnostics.daily_flow_forecast import predict, PRICE


def publication_window(now, boundary):
    seconds = (now - boundary).total_seconds()
    return 'EARLY' if seconds < 5 else 'OPEN' if seconds <= 50 else 'MISSED'


def frame_from_rows(rows, start_ms, end_ms):
    if [r[0] for r in rows] != list(range(start_ms, end_ms, 60000)):
        raise ValueError('missing/duplicate/out-of-range minute')
    values = []
    for r in rows:
        if len(r) != 12 or r[6] != r[0] + 59999:
            raise ValueError('kline schema or close time')
        o, h, l, c, v = [float(x) for x in r[1:6]]
        if not all(math.isfinite(x) for x in (o, h, l, c, v)) or min(o, h, l, c) <= 0 or v < 0:
            raise ValueError('invalid price/volume')
        if h < max(o, c) or l > min(o, c) or h < l:
            raise ValueError('invalid candle geometry')
        values.append([o, h, l, c, v])
    return pd.DataFrame(values, index=pd.to_datetime([r[0] for r in rows], unit='ms', utc=True), columns=['o', 'h', 'l', 'c', 'v'])


def make_panel(old_rows, minutes, boundary):
    old = pd.DataFrame(old_rows).set_index('open_time')
    old.index = pd.to_datetime(old.index, utc=True)
    for col in ('entry_time', 'exit_time'):
        old[col] = pd.to_datetime(old[col], utc=True)
    if minutes.index.has_duplicates or not minutes.index.is_monotonic_increasing:
        raise ValueError('minute identity')
    if not (np.diff(minutes.index.asi8) == 60_000_000_000).all():
        raise ValueError('minute gap')
    if minutes.index[-1] != boundary - pd.Timedelta(minutes=1):
        raise ValueError('current features not complete')
    start = minutes.index[0].ceil('D') + pd.Timedelta(days=8)
    updates = []
    overlap_checks = 0
    for b in pd.date_range(start, boundary, freq='1D'):
        j = minutes.index.searchsorted(b)
        i = j - 1440
        closes = minutes.c.iloc[i-1:j].to_numpy()
        volatility = math.sqrt(math.fsum(math.log(float(v)/float(u))**2 for u, v in zip(closes, closes[1:])))
        vector_check = float(np.sqrt(np.square(np.diff(np.log(closes))).sum()))
        if abs(volatility - vector_check) > 1e-10:
            raise ValueError('independent volatility mismatch')
        entry, exit = b + pd.Timedelta(minutes=1), b + pd.Timedelta(days=1)
        target = (float(minutes.at[exit, 'o']) / float(minutes.at[entry, 'o']) - 1) * 10000 if entry in minutes.index and exit in minutes.index else np.nan
        row = dict(open_time=b, return_1d=float(minutes.c.iloc[j-1] / minutes.c.iloc[i-1] - 1),
            return_7d=float(minutes.c.iloc[j-1] / minutes.c.iloc[j-7*1440-1] - 1),
            realized_vol_1d=volatility, decision_close=float(minutes.c.iloc[j-1]),
            entry_time=entry, exit_time=exit, target_bps=target)
        if b in old.index:
            for key in PRICE + ['decision_close', 'target_bps']:
                if pd.notna(old.at[b, key]) and pd.notna(row[key]):
                    if abs(float(old.at[b, key]) - row[key]) > (1e-7 if key == 'target_bps' else 1e-10):
                        raise ValueError('old overlap mismatch: ' + key)
                    overlap_checks += 1
        updates.append(row)
    new = pd.DataFrame(updates).set_index('open_time')
    panel = pd.concat([old.loc[old.index < new.index[0]], new]).sort_index()
    if panel.index.has_duplicates or not (np.diff(panel.index.asi8) == 86400_000_000_000).all():
        raise ValueError('daily calendar mismatch')
    return panel, overlap_checks


def forecast(panel, boundary, funding):
    i = panel.index.get_loc(boundary)
    if i < 181 or panel.index[i-181] != boundary - pd.Timedelta(days=181):
        raise ValueError('training range')
    result = predict(panel, panel.target_bps, i, PRICE)
    if pd.Timestamp(result['training_last_target_exit']) != boundary - pd.Timedelta(days=1):
        raise ValueError('label gap')
    selected = sorted([e for e in funding if e['fundingTime'] < int(boundary.timestamp()*1000)], key=lambda e:e['fundingTime'])[-3:]
    if len(selected) != 3 or len({e['fundingTime'] for e in selected}) != 3:
        raise ValueError('past funding count')
    if int(boundary.timestamp()*1000) - selected[0]['fundingTime'] > 25*3600*1000:
        raise ValueError('stale funding')
    if any(e['symbol'] != 'BTCUSDC' or not math.isfinite(float(e['fundingRate'])) for e in selected):
        raise ValueError('funding schema')
    h = 18 + abs(sum(float(e['fundingRate']) for e in selected))*10000 + .2/float(panel.at[boundary, 'decision_close'])*10000
    p = result['prediction_bps']
    side = 1 if p > 0 else -1 if p < 0 else 0
    return dict(result, boundary=boundary.isoformat(), entry_time=(boundary+pd.Timedelta(minutes=1)).isoformat(),
        exit_time=(boundary+pd.Timedelta(days=1)).isoformat(), threshold_bps=h,
        controls=dict(MEAN180=result['intercept_bps'], ZERO=0.),
        selectors=dict(original_H=side if abs(p)>h else 0, exploratory_2H=side if abs(p)>2*h else 0),
        current_features={k:float(panel.at[boundary,k]) for k in PRICE},
        funding_times=[e['fundingTime'] for e in selected])


def validate_funding_coverage(funding, entry_ms, exit_ms):
    times = [e['fundingTime'] for e in funding]
    if not times or times != sorted(set(times)):
        raise ValueError('funding order/empty')
    if times[0] > entry_ms or times[-1] < exit_ms:
        raise ValueError('funding endpoints not bracketed')
    if any(b-a > 8*3600000+1000 for a, b in zip(times, times[1:])):
        raise ValueError('funding coverage gap')
    for e in funding:
        if e['symbol'] != 'BTCUSDC' or not math.isfinite(float(e['fundingRate'])) or not math.isfinite(float(e['markPrice'])) or float(e['markPrice']) <= 0:
            raise ValueError('funding fields')


def score_unit(entry, exit, side, funding, entry_ms, exit_ms, fee_bps, slip_bps, extra_bps):
    entry, exit = D(str(entry)), D(str(exit))
    if side not in (-1, 0, 1) or not all(p.is_finite() and p > 0 for p in (entry, exit)):
        raise ValueError('unit-event price/side')
    if exit_ms <= entry_ms or any(not D(str(x)).is_finite() or D(str(x)) < 0 for x in (fee_bps, slip_bps, extra_bps)):
        raise ValueError('unit-event interval/cost')
    if not side:
        return dict(gross_bps='0', fees_bps='0', execution_bps='0', funding_bps='0', net_bps='0')
    def fill(p, direction):
        return (p*(1+D(direction)*D(str(slip_bps))/10000)/D('.1')).to_integral_value(rounding=ROUND_CEILING if direction==1 else ROUND_FLOOR)*D('.1')
    a, b = fill(entry, side), fill(exit, -side)
    gross = D(side)*(exit-entry)
    price = D(side)*(b-a)
    fees = (a+b)*D(str(fee_bps))/10000
    paid = sum((D(e['markPrice'])*(D(side)*D(e['fundingRate'])+D(abs(side))*D(str(extra_bps))/10000)
        for e in funding if entry_ms < ((e['fundingTime']+59999)//60000)*60000 <= exit_ms), D(0))
    return {k:str(v/entry*10000) for k,v in dict(gross_bps=gross, fees_bps=fees,
        execution_bps=gross-price, funding_bps=paid, net_bps=price-fees-paid).items()}
