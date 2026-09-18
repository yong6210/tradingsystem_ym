"""Independent Fraction signal/cohort and displayed-level cash-flow checks."""
from fractions import Fraction as F


def verify(grid,events):
    points={p['time_ns']:p for p in grid};expected=[];next_allowed=0;NS=10**9
    for p in grid:
        t=p['time_ns'];past=points.get(t-5*NS)
        if t<next_allowed or t+63*NS not in points or not past or not p['valid'] or not past['valid']:continue
        trades={x['id']:x for x in p['trades'] if t-5*NS<x['time_ns']<=t}
        if len(trades)<3:continue
        totals={True:F(0),False:F(0)}
        for x in trades.values():totals[x['buyer_maker']]+=F(x['price'])*F(x['qty'])
        total=sum(totals.values())
        if not total:continue
        sign=1 if 5*totals[True]>=4*total and F(p['mid'])>=F(past['mid']) else -1 if 5*totals[False]>=4*total and F(p['mid'])<=F(past['mid']) else 0
        if not sign:continue
        bid=sum((F(a)*F(b) for a,b in p['bids']),F(0));ask=sum((F(a)*F(b) for a,b in p['asks']),F(0))
        expected.append((t,sign,bid>=ask if sign==1 else ask>=bid));next_allowed=t+73*NS
    actual=[(e['signal_ns'],e['direction'],e['candidate']) for e in events]
    if actual!=expected:raise ValueError('independent opportunity cohort mismatch')
    checked=0
    def leg(point,side,slip):
        if not point['valid']:return 'UNAVAILABLE',None,None
        remaining=F(1,1000);value=F(0)
        for price,qty in point['asks' if side==1 else 'bids']:
            use=min(remaining,F(qty));raw=F(price)*(1+side*F(slip,10000))*10
            units=-((-raw.numerator)//raw.denominator) if side==1 else raw.numerator//raw.denominator
            value+=use*F(units,10);remaining-=use
            if not remaining:break
        if remaining:return 'INSUFFICIENT_VISIBLE_SIZE',None,None
        return 'COMPLETE_PROXY',value,value*F(1,4000)
    for e in events:
        if e['entry_ns']!=e['signal_ns']+3*NS or e['exit_ns']!=e['entry_ns']+60*NS:raise ValueError('time boundary')
        for key,slip in [('base',2),('stress',5)]:
            r=e['conditions'][key];status,en,ef=leg(points[e['entry_ns']],e['direction'],slip)
            if status!='COMPLETE_PROXY':want='ENTRY_'+status
            elif not F(50)<=en<=F(200):want='ENTRY_NOTIONAL_REJECTED'
            else:
                out,ex,xf=leg(points[e['exit_ns']],-e['direction'],slip)
                want='COMPLETE_CONDITIONAL_EVENT' if out=='COMPLETE_PROXY' else 'EXIT_UNRESOLVED'
            if r['status']!=want:raise ValueError('entry/exit outcome')
            if want=='COMPLETE_CONDITIONAL_EVENT':
                price=e['direction']*(ex-en);fees=ef+xf
                if F(r['price_pnl'])!=price or F(r['fees'])!=fees or F(r['net'])!=price-fees:
                    raise ValueError('independent conditional cash flow')
                checked+=1
            elif 'net' in r:raise ValueError('invented incomplete PnL')
    return dict(status='PASS_FRACTION_COHORT_AND_CONDITIONAL_CASH_FLOW',all_grid_points_checked=len(grid),events=len(events),completed_cost_events_checked=checked,
        scope='Independent arithmetic from stored decision grid; not independent raw L2 reconstruction or actual fills')
