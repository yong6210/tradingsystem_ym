"""Stored simulated-account dependence; never sums accounts into a portfolio."""
from collections import defaultdict
from decimal import Decimal as D
from datetime import date,timedelta
import math

EPS=D('1e-9')


def longest_underwater(daily,initial=D(1000)):
    if not daily:raise ValueError('empty daily series')
    peak=initial; peak_i=-1; active=False; periods=[]
    def append(end,recovered):
        periods.append(dict(start_index=peak_i+1,end_index=end,days=end-peak_i,
            peak_day=(date.fromisoformat(daily[0]['day'])-timedelta(days=1)).isoformat() if peak_i<0 else daily[peak_i]['day'],
            start= daily[peak_i+1]['day'],end=daily[end]['day'],recovered=recovered,
            peak_equity=str(peak),end_equity=str(D(str(daily[end]['equity'])))))
    for i,row in enumerate(daily):
        equity=D(str(row['equity']))
        if equity>=peak:
            if active:append(i,True)
            peak=equity;peak_i=i;active=False
        else:active=True
    if active:append(len(daily)-1,False)
    return max(periods,key=lambda p:p['days']) if periods else None


def account_summary(daily,trades,metrics):
    initial=D(str(metrics['initial']));previous=initial;pnl=[];returns=[];monthly=defaultdict(lambda:D(0))
    for row in daily:
        equity=D(str(row['equity']));change=equity-previous
        if previous<=0:raise ValueError('nonpositive daily denominator')
        pnl.append(change);returns.append(float(change/previous));monthly[row['day'][:7]]+=change;previous=equity
    net=previous-initial
    side={k:sum((D(str(t['net_pnl'])) for t in trades if t['side']==k),D(0)) for k in (-1,1)}
    operating=D(str(metrics['operating_cost']))
    if abs(net-(D(str(metrics['final_equity']))-initial))>D('1e-6'):raise ValueError('daily/final bridge')
    if abs(side[-1]+side[1]-operating-net)>D('1e-6'):raise ValueError('trade/operating bridge')
    if len(trades)!=metrics['cycles']:raise ValueError('cycle count')
    ordered=sorted([(k,v) for k,v in monthly.items() if v>EPS],key=lambda a:(-a[1],a[0]))
    positive=sum((v for _,v in ordered),D(0))
    top1=sum((v for _,v in ordered[:1]),D(0));top2=sum((v for _,v in ordered[:2]),D(0))
    output=dict(net_usdc=float(net),long_trade_net_usdc=float(side[1]),short_trade_net_usdc=float(side[-1]),
        operating_usdc=float(operating),trades=len(trades),positive_months=len(ordered),
        monthly_pnl_usdc={k:float(v) for k,v in monthly.items()},top_positive_months=[dict(month=k,pnl_usdc=float(v)) for k,v in ordered[:2]],
        net_less_top1_month_usdc=float(net-top1),net_less_top2_months_usdc=float(net-top2),
        top1_share_positive_month_pnl=float(top1/positive) if positive else None,
        top2_share_positive_month_pnl=float(top2/positive) if positive else None,
        longest_underwater=longest_underwater(daily,initial),max_drawdown_pct=metrics['max_drawdown_pct'])
    return output,pnl,returns


def pair_stats(a,b,ra,rb):
    if not (len(a)==len(b)==len(ra)==len(rb)) or not a:raise ValueError('unaligned pair')
    n=len(a);ma=math.fsum(ra)/n;mb=math.fsum(rb)/n
    x=[v-ma for v in ra];y=[v-mb for v in rb]
    va=math.fsum(v*v for v in x);vb=math.fsum(v*v for v in y)
    corr=math.fsum(u*v for u,v in zip(x,y))/math.sqrt(va*vb) if va and vb else None
    ia=[i for i,p in enumerate(a) if p < -EPS];ib=[i for i,p in enumerate(b) if p < -EPS]
    both=len(set(ia)&set(ib))
    return dict(daily_return_correlation=corr,loss_days_a=len(ia),loss_days_b=len(ib),simultaneous_loss_days=both,
        simultaneous_loss_fraction_all=both/n,simultaneous_given_a_loss=both/len(ia) if ia else None,
        simultaneous_given_b_loss=both/len(ib) if ib else None,
        b_pnl_on_a_loss_days_usdc=float(sum((b[i] for i in ia),D(0))),
        a_pnl_on_b_loss_days_usdc=float(sum((a[i] for i in ib),D(0))))


def position_overlap(a,b):
    i=j=0;same=opposite=0
    while i<len(a) and j<len(b):
        x,y=a[i],b[j]
        length=max(0,min(x['exit_minute'],y['exit_minute'])-max(x['entry_minute'],y['entry_minute']))
        if x['side']==y['side']:same+=length
        else:opposite+=length
        if x['exit_minute']<=y['exit_minute']:i+=1
        else:j+=1
    return dict(same_direction_overlap_minutes=same,opposite_direction_overlap_minutes=opposite,
        total_overlap_minutes=same+opposite)
