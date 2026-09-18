"""Source fitness and current-filter order arithmetic; no PnL simulation."""
from decimal import Decimal as D, ROUND_FLOOR
import io
import math
from zipfile import ZipFile

import numpy as np
import pandas as pd

HOUR=3_600_000


def parse_hour_archive(raw, month):
    with ZipFile(io.BytesIO(raw)) as archive:
        files=archive.infolist()
        if len(files)!=1 or files[0].file_size>4*1024*1024:raise ValueError('archive envelope')
        frame=pd.read_csv(io.BytesIO(archive.read(files[0])),dtype=str)
    required=['open_time','open','high','low','close','volume','close_time','quote_volume','count','taker_buy_volume','taker_buy_quote_volume']
    if not set(required)<=set(frame.columns):raise ValueError('archive schema')
    frame=frame[required].apply(pd.to_numeric,errors='raise')
    if frame.empty or not np.isfinite(frame.to_numpy()).all():raise ValueError('empty/nonfinite rows')
    for column in ('open_time','close_time','count'):
        if not np.equal(frame[column],np.floor(frame[column])).all():raise ValueError('fractional integral field')
    clocks=frame.open_time.astype('int64')
    if (clocks%HOUR).any() or not (frame.close_time==clocks+HOUR-1).all():raise ValueError('clock unit/boundary')
    times=pd.to_datetime(clocks,unit='ms',utc=True)
    if times.duplicated().any() or not times.is_monotonic_increasing:raise ValueError('duplicate/unordered hours')
    start=pd.Timestamp(month+'-01',tz='UTC');end=start+pd.offsets.MonthBegin(1)
    if ((times<start)|(times>=end)).any():raise ValueError('wrong month')
    prices=frame[['open','high','low','close']]
    if (prices<=0).any().any() or (frame[['volume','quote_volume','count','taker_buy_volume','taker_buy_quote_volume']]<0).any().any():raise ValueError('invalid prices/volume')
    if ((frame.high<prices.max(axis=1))|(frame.low>prices.min(axis=1))).any():raise ValueError('OHLC geometry')
    if ((frame.taker_buy_volume>frame.volume+1e-8)|(frame.taker_buy_quote_volume>frame.quote_volume+1e-6)).any():raise ValueError('taker volume exceeds total')
    frame.index=pd.DatetimeIndex(times)
    expected=pd.date_range(start,end,freq='h',inclusive='left');missing=expected.difference(frame.index)
    return frame,dict(rows=len(frame),expected_rows=len(expected),missing_hours=[t.isoformat() for t in missing],
        duplicates=0,nonfinite=0,unit='ms')


def funding_profile(rows, start_ms, end_ms):
    times=[]
    for r in rows:
        t=r['fundingTime']
        if r['symbol']!='ETHUSDC' or type(t)is not int or not start_ms<=t<end_ms:raise ValueError('funding identity/time')
        rate,mark=D(r['fundingRate']),D(r['markPrice'])
        if not rate.is_finite() or not mark.is_finite() or mark<=0:raise ValueError('funding values')
        times.append(t)
    if times!=sorted(set(times)):raise ValueError('funding order/duplicate')
    if not times:raise ValueError('empty funding history')
    intervals=[b-a for a,b in zip(times,times[1:])]
    warnings=[]
    if times[0]-start_ms>8*HOUR+60000:warnings.append(dict(kind='start_edge',gap_ms=times[0]-start_ms))
    if end_ms-times[-1]>8*HOUR+60000:warnings.append(dict(kind='end_edge',gap_ms=end_ms-times[-1]))
    warnings.extend(dict(kind='interval',before=a,after=b,gap_ms=b-a) for a,b in zip(times,times[1:]) if b-a>8*HOUR+60000)
    return dict(events=len(rows),first_ms=times[0],last_ms=times[-1],max_interval_ms=max(intervals,default=0),
        schedule_or_gap_warnings=warnings,historical_schedule_independently_certified=False)


def contract(symbol):
    if symbol['symbol'] not in ('BTCUSDC','ETHUSDC') or symbol['contractType']!='PERPETUAL' or symbol['quoteAsset']!='USDC' or symbol['marginAsset']!='USDC' or symbol['status']!='TRADING':raise ValueError('contract identity/status')
    f={x['filterType']:x for x in symbol['filters']}
    lots=[f['LOT_SIZE'],f['MARKET_LOT_SIZE']]
    steps=[D(x['stepSize']) for x in lots]
    if min(steps)<=0:raise ValueError('nonpositive lot step')
    digits=max(-s.as_tuple().exponent for s in steps);scale=10**digits
    step=D(math.lcm(*(int(s*scale) for s in steps)))/scale
    minimum=D(f['MIN_NOTIONAL']['notional'])
    lo=max(D(x['minQty']) for x in lots);hi=min(D(x['maxQty']) for x in lots)
    if lo<=0 or hi<lo or minimum<=0:raise ValueError('invalid lot bounds')
    return dict(symbol=symbol['symbol'],step=step,min_qty=lo,max_qty=hi,min_notional=minimum,
        onboard_ms=symbol.get('onboardDate'),historical_filters_verified=False)


def size_pair(btc,eth,bc,ec):
    b,e=D(str(btc)),D(str(eth));sl=D('.0005');fee=D('.00025')
    if not all(p.is_finite() and p>0 for p in (b,e)):raise ValueError('invalid price')
    qb=(D(200)/(b*(1+sl))/bc['step']).to_integral_value(rounding=ROUND_FLOOR)*bc['step']
    nb=qb*b
    qe=(nb/e/ec['step']).to_integral_value(rounding=ROUND_FLOOR)*ec['step'];ne=qe*e
    reasons=[]
    for label,q,p,c in [('BTC',qb,b,bc),('ETH',qe,e,ec)]:
        if not c['min_qty']<=q<=c['max_qty'] or q%c['step']:reasons.append(label+'_quantity')
        if q*p*(1-sl)<c['min_notional']:reasons.append(label+'_min_notional')
        if q*p*(1+sl)>200:reasons.append(label+'_leg_cap')
        if q*p*(1+sl)*(1+fee)>400:reasons.append(label+'_initial_margin')
    mismatch=abs(nb-ne)/max(nb,ne) if max(nb,ne)>0 else D(1)
    prepared=max(nb,ne)*D('.01')+2*(nb+ne)*(fee+sl)+1
    if mismatch>D('.03'):reasons.append('notional_mismatch')
    if prepared>5:reasons.append('prepared_risk')
    return dict(btc_qty=str(qb),eth_qty=str(qe),btc_notional=str(nb),eth_notional=str(ne),
        mismatch_fraction=str(mismatch),prepared_risk_usdc=str(prepared),eligible=not reasons,reasons=reasons)
