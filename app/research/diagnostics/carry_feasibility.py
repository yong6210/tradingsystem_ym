"""H02: two-wallet arithmetic and optimistic solvency bounds, not a trading engine."""
from decimal import Decimal as D, ROUND_FLOOR
import io
from zipfile import ZipFile
import numpy as np
import pandas as pd

HOUR_MS=3_600_000
COLUMNS=('time','o','h','l','c','v','end','quote','count','buy','buy_quote','ignore')


def parse_spot(raw,month):
    with ZipFile(io.BytesIO(raw)) as z:
        files=z.infolist()
        if len(files)!=1 or files[0].file_size>4*1024*1024: raise ValueError('archive envelope')
        data=z.read(files[0])
    f=pd.read_csv(io.BytesIO(data),header=None,names=COLUMNS)
    if f.empty or len(f.columns)!=12: raise ValueError('spot schema')
    f=f.apply(pd.to_numeric,errors='raise')
    start=pd.Timestamp(month+'-01',tz='UTC');end=start+pd.offsets.MonthBegin(1)
    scale=1000 if month>='2025-01' else 1
    times=f.time.to_numpy(dtype=np.int64);ends=f.end.to_numpy(dtype=np.int64)
    if not np.all(f.time==times) or not np.all(f.end==ends): raise ValueError('fractional clock')
    if np.any(times%(HOUR_MS*scale)) or np.any(ends!=times+HOUR_MS*scale-1): raise ValueError('clock unit/boundary')
    expected=pd.date_range(start,end,freq='h',inclusive='left')
    actual=pd.to_datetime(times//scale,unit='ms',utc=True)
    if not actual.equals(expected): raise ValueError('calendar gap/duplicate/order/month')
    vals=f[['o','h','l','c','v','quote','count','buy','buy_quote']].to_numpy()
    if not np.isfinite(vals).all() or (vals<0).any() or (f[['o','h','l','c']]<=0).any().any(): raise ValueError('invalid numbers')
    if ((f.h<f[['o','c','l']].max(axis=1))|(f.l>f[['o','c','h']].min(axis=1))).any(): raise ValueError('OHLC geometry')
    if ((f.buy>f.v+1e-8)|(f.buy_quote>f.quote+1e-6)|(f['count']!=np.floor(f['count']))).any(): raise ValueError('volume/count')
    f.index=actual
    return f[['o','h','l','c','v']],dict(rows=len(f),unit='us' if scale==1000 else 'ms',nulls=0,duplicate_times=0,gaps=0)


def quantity(spot_open):
    return float((D(400)/(D(str(spot_open))*D('1.0005')*D('1.001'))/D('.001')).to_integral_value(rounding=ROUND_FLOOR)*D('.001'))


def path(frame,funding,q,spot_fee_bps,slippage_bps,extra_funding_bps):
    """Inputs are matched hours; mark highs only test segregated futures capital."""
    if q<=0 or frame.empty or not frame.index.is_unique: raise ValueError('invalid path')
    sf,ff,slip=spot_fee_bps/10000,2.5/10000,slippage_bps/10000
    s0=float(frame.spot_open.iloc[0])*(1+slip)
    f0=float(frame.future_open.iloc[0])*(1-slip)
    spot_cost=q*s0*(1+sf)
    if spot_cost>400+1e-8: raise ValueError('spot budget exceeded')
    futures_fee=q*f0*ff
    outside_cash=1000-500-spot_cost
    n=len(frame);fund=np.zeros(n);positive=np.zeros(n)
    start_ms=int(frame.index[0].value//1_000_000);end_ms=int(frame.index[-1].value//1_000_000)+HOUR_MS
    selected=[]
    for e in funding:
        t=e['fundingTime']
        if not start_ms<t<end_ms: continue
        i=(t-start_ms)//HOUR_MS
        amount=q*float(e['markPrice'])*(float(e['fundingRate'])-extra_funding_bps/10000)
        fund[i]+=amount;positive[i]+=max(amount,0)
        selected.append(dict(time_ms=t,receipt=amount,rate=float(e['fundingRate']),mark=float(e['markPrice'])))
    cumulative=np.cumsum(fund);before=cumulative-fund
    high=frame.mark_high.to_numpy(dtype=float)
    # Even optimistic timing cannot rescue a nonpositive isolated wallet.
    optimistic=500-futures_fee+before+positive+q*(f0-high)
    cushion=q*high*(.01+ff+slip)
    spot_exit=frame.spot_close.to_numpy(dtype=float)*(1-slip)
    futures_exit=frame.future_close.to_numpy(dtype=float)*(1+slip)
    theoretical=outside_cash+q*spot_exit*(1-sf)+500-futures_fee+cumulative+q*(f0-futures_exit)-q*futures_exit*ff
    rows=[dict(hour=t.isoformat(),funding_receipt=float(fund[i]),cumulative_funding=float(cumulative[i]),
        optimistic_futures_equity_at_mark_high=float(optimistic[i]),
        hypothetical_one_pct_and_exit_reserve=float(cushion[i]),
        theoretical_pair_closeout_equity=float(theoretical[i])) for i,t in enumerate(frame.index)]
    deficits=np.flatnonzero(optimistic<=0);reserve_deficits=np.flatnonzero(optimistic<=cushion)
    return dict(rows=rows,funding=selected,summary=dict(quantity_btc=q,spot_fee_bps_assumption=spot_fee_bps,
        futures_fee_bps=2.5,slippage_bps=slippage_bps,extra_funding_bps=extra_funding_bps,
        initial_spot_cost=spot_cost,initial_futures_margin=500,outside_cash_never_transferred=outside_cash,
        first_nonpositive_isolated_equity=rows[int(deficits[0])]['hour'] if len(deficits) else None,
        hours_nonpositive_optimistic_equity=len(deficits),minimum_optimistic_futures_equity=float(optimistic.min()),
        first_hypothetical_reserve_breach=rows[int(reserve_deficits[0])]['hour'] if len(reserve_deficits) else None,
        funding_receipts_net=float(cumulative[-1]),funding_events=len(selected),
        theoretical_terminal_pair_equity=float(theoretical[-1]),
        feasible_strategy_return_reported=False,adopted=False,actual_orders=0))


def verify_decimal(frame,funding,result):
    s=result['summary'];q=D(str(s['quantity_btc']));sl=D(str(s['slippage_bps']))/10000
    sf=D(str(s['spot_fee_bps_assumption']))/10000;ff=D('.00025');extra=D(str(s['extra_funding_bps']))/10000
    spot=D(str(frame.spot_open.iloc[0]))*(1+sl);future=D(str(frame.future_open.iloc[0]))*(1-sl)
    outside=D(500)-q*spot*(1+sf);fee=q*future*ff;cum=D(0)
    grouped={}
    start=int(frame.index[0].value//1_000_000);end=int(frame.index[-1].value//1_000_000)+HOUR_MS
    for e in funding:
        if start<e['fundingTime']<end:
            hour=(e['fundingTime']-start)//HOUR_MS
            grouped.setdefault(hour,[]).append(q*D(e['markPrice'])*(D(e['fundingRate'])-extra))
    for i,(t,f) in enumerate(frame.iterrows()):
        receipts=grouped.get(i,[])
        optimistic=D(500)-fee+cum+sum((max(r,D(0)) for r in receipts),D(0))+q*(future-D(str(f.mark_high)))
        cum+=sum(receipts,D(0))
        spot_exit=D(str(f.spot_close))*(1-sl);future_exit=D(str(f.future_close))*(1+sl)
        terminal=outside+q*spot_exit*(1-sf)+D(500)-fee+cum+q*(future-future_exit)-q*future_exit*ff
        for key,value in (('optimistic_futures_equity_at_mark_high',optimistic),('theoretical_pair_closeout_equity',terminal),('cumulative_funding',cum)):
            if abs(D(str(result['rows'][i][key]))-value)>D('.000001'): raise ValueError('Decimal differs: '+key)
    return dict(status='PASS_ALL_HOURLY_DECIMAL_CASH_AND_SEPARATE_MARGIN',hours=len(frame),funding_events=sum(map(len,grouped.values())))
