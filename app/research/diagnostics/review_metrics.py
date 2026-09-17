"""Descriptive calendar risk diagnostics; never a strategy acceptance gate."""
from datetime import date, timedelta
import math


def calendar_risk(rows, initial=1000.):
    if not rows or initial <= 0: raise ValueError('nonempty positive-equity series required')
    first=date.fromisoformat(rows[0]['day'])
    previous_day=first-timedelta(days=1)
    peak=previous=float(initial);peak_day=previous_day
    longest=0;completed_longest=0;recoveries=0;returns=[]
    underwater=False
    for r in rows:
        day=date.fromisoformat(r['day']);equity=float(r['equity'])
        if day!=previous_day+timedelta(days=1) or not math.isfinite(equity) or equity<=0:
            raise ValueError('continuous positive finite daily equity required')
        returns.append(equity/previous-1)
        if equity>=peak:
            if underwater:
                length=(day-peak_day).days
                completed_longest=max(completed_longest,length)
                longest=max(longest,length);recoveries+=1
            peak=equity;peak_day=day;underwater=False
        else:
            underwater=True;longest=max(longest,(day-peak_day).days)
        previous_day=day;previous=equity
    count=max(1,math.ceil(len(returns)*.05))
    return dict(calendar_days=len(rows),worst_daily_return_pct=100*min(returns),
                daily_es_5pct=100*sum(sorted(returns)[:count])/count,tail_days=count,
                longest_underwater_days=longest,longest_completed_recovery_days=completed_longest,
                current_underwater_days=(previous_day-peak_day).days if underwater else 0,
                unrecovered_at_end=underwater,completed_recoveries=recoveries,
                scope='DAILY_CLOSE_CALENDAR_INCLUDES_HALTED_CASH_DAYS')
