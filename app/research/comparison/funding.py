"""Signed historical funding with an explicit minute-grid timing approximation."""
import math
import pandas as pd


def funding_schedule(index, events):
    result = {}
    last = -1
    for event in events:
        time = event['fundingTime']
        rate, mark = float(event['fundingRate']), float(event['markPrice'])
        if type(time) is not int or time <= last or not math.isfinite(rate) or not math.isfinite(mark) or mark <= 0:
            raise ValueError('invalid or unordered funding event')
        last = time
        timestamp = pd.Timestamp(time, unit='ms', tz='UTC')
        if timestamp < index[0]:
            continue
        i = int(index.searchsorted(timestamp, side='left'))
        if i >= len(index):
            continue
        if (index[i]-timestamp).total_seconds() >= 60:
            raise ValueError('funding processing crosses a missing minute')
        result.setdefault(i, []).append(event)
    return result


def settle(account, processing_time, event, stress_bps=0):
    if not math.isfinite(stress_bps) or stress_bps < 0:
        raise ValueError('invalid funding stress')
    if not account.quantity:
        return
    mark, rate = float(event['markPrice']), float(event['fundingRate'])
    actual = account.quantity * mark * rate
    stress = abs(account.quantity) * mark * stress_bps / 10000
    amount = actual + stress
    account.funding += amount
    account.balance -= amount
    account.record(processing_time, 'funding', amount=amount, mark=mark,
                   rate=rate, historical_amount=actual, stress_amount=stress,
                   settlement_ms=event['fundingTime'])
