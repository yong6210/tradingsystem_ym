"""Descriptive signal counts and explicitly IID planning scales, not inference."""
import math
import statistics


def rolling_counts(selected, days):
    if days<=0 or len(selected)<days or any(x not in (0,1) for x in selected):
        raise ValueError('invalid binary calendar/horizon')
    prefix=[0]
    for x in selected:prefix.append(prefix[-1]+x)
    return [prefix[i+days]-prefix[i] for i in range(len(selected)-days+1)]


def planning(values, calendar_days, horizon=90):
    n=len(values)
    if calendar_days<=0 or horizon<=0 or n>calendar_days or not all(math.isfinite(x) for x in values):
        raise ValueError('invalid sample')
    count=horizon*n/calendar_days
    planned=math.floor(count+.5)
    mean=math.fsum(values)/n if n else None
    variance=math.fsum((x-mean)**2 for x in values)/(n-1) if n>1 else None
    sd=math.sqrt(variance) if variance is not None else None
    return dict(active_days=n,calendar_days=calendar_days,historical_active_fraction=n/calendar_days,
        reference_count=count,rounded_reference_count=planned,historical_mean_bps=mean,
        historical_sample_sd_bps=sd,iid_planning_standard_error_bps=sd/math.sqrt(planned) if sd is not None and planned>0 else None,
        future_confidence_interval=None,statistical_power=None)


def count_summary(counts):
    if not counts:raise ValueError('no windows')
    return dict(windows=len(counts),minimum=min(counts),median=statistics.median(counts),maximum=max(counts),
        zero_windows=sum(x==0 for x in counts),independent_windows=False)
