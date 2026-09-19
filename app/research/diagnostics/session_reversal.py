"""Fixed UTC same-session lag reversal; signal and risk accounting are separate."""
from decimal import Decimal
import numpy as np
import pandas as pd
from app.research.multistrategy_audit import frame_features
from app.research.comparison.funding import funding_schedule


def sessions(minutes, start, end):
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    features = frame_features(minutes, 240)
    rows = []
    for day in pd.date_range(start.normalize(), end.normalize(), freq='D'):
        for hour in (8, 20):
            boundary = day + pd.Timedelta(hours=hour)
            entry = boundary + pd.Timedelta(minutes=1)
            exit_time = boundary + pd.Timedelta(hours=12)
            if entry < start or exit_time >= end:
                continue
            old_start = boundary - pd.Timedelta(hours=24, minutes=1)
            old_end = boundary - pd.Timedelta(hours=12, minutes=1)
            p0, p1 = float(minutes.at[old_start, 'c']), float(minutes.at[old_end, 'c'])
            atr = float(features.at[boundary, 'atr'])
            close = float(minutes.at[boundary-pd.Timedelta(minutes=1), 'c'])
            if not np.isfinite([p0, p1, atr, close]).all() or min(p0, p1, atr, close) <= 0:
                raise ValueError('missing or invalid causal signal inputs')
            side = -int(np.sign(p1-p0))
            i, j = (int(minutes.index.get_indexer([t])[0]) for t in (entry, exit_time))
            if i < 0 or j < 0:
                raise ValueError('missing session boundary')
            rows.append(dict(boundary=boundary.isoformat(), entry_time=entry.isoformat(), exit_time=exit_time.isoformat(),
                             lag_start_close_time=old_start.isoformat(), lag_end_close_time=old_end.isoformat(),
                             lag_start_close=p0, lag_end_close=p1, lag_return=p1/p0-1, side=side,
                             entry_minute=i, exit_minute=j, decision_close=close, atr=atr))
    return rows


def decisions(rows, model):
    if model not in ('REVERSAL', 'LONG'):
        raise ValueError('unregistered model')
    result = {}
    for row in rows:
        side = row['side'] if model == 'REVERSAL' else 1
        result[row['entry_minute']] = (side, row['decision_close'], row['atr'])
        result[row['exit_minute']] = (0, row['decision_close'], row['atr'])
    return result


def verify_signals(minutes, rows):
    """Independently verify lag offsets and direction with integer minutes/Decimal."""
    epoch = minutes.index.asi8 // 60_000_000_000
    for row in rows:
        i, j = row['entry_minute'], row['exit_minute']
        b = int(epoch[i])-1
        assert b % 1440 in (480, 1200) and int(epoch[j])-b == 720
        old0, old1 = i-1442, i-722
        assert int(epoch[old0]) == b-1441 and int(epoch[old1]) == b-721
        p0, p1 = (Decimal(str(minutes.iloc[k].c)) for k in (old0, old1))
        expected = -1 if p1 > p0 else 1 if p1 < p0 else 0
        assert row['side'] == expected
        assert row['lag_start_close_time'] == minutes.index[old0].isoformat()
        assert row['lag_end_close_time'] == minutes.index[old1].isoformat()
        assert row['entry_time'] == minutes.index[i].isoformat()
        assert row['exit_time'] == minutes.index[j].isoformat()
        assert row['decision_close'] == float(minutes.iloc[i-2].c)
    return dict(status='PASS', sessions=len(rows), lag='PREVIOUS_DAY_SAME_SESSION_NOT_PREVIOUS_ADJACENT_SESSION')


def event_returns(minutes, rows, funding, costs, model):
    schedule = funding_schedule(minutes.index, funding)
    output = []
    for row in rows:
        i, j = row['entry_minute'], row['exit_minute']
        side = row['side'] if model == 'REVERSAL' else 1
        op, end = float(minutes.iloc[i].o), float(minutes.iloc[j].o)
        entry = costs.fill(op, side) if side else op
        exit_price = costs.fill(end, -side) if side else end
        raw = side*(end-op)
        price_pnl = side*(exit_price-entry)
        fees = (entry+exit_price)*costs.fee_bps/10000 if side else 0
        payments = []
        # Existing positions settle before exit; entry-minute funding precedes entry.
        for k in range(i+1, j+1):
            for event in schedule.get(k, ()):
                mark, rate = float(event['markPrice']), float(event['fundingRate'])
                amount = side*mark*rate + abs(side)*mark*costs.funding_bps_8h/10000
                payments.append(dict(settlement_ms=event['fundingTime'], amount_per_btc=amount))
        funding_cost = sum(p['amount_per_btc'] for p in payments)
        output.append(dict(entry_time=row['entry_time'], exit_time=row['exit_time'], side=side,
                           gross_bps=raw/op*10000, execution_bps=(raw-price_pnl)/op*10000,
                           fee_bps=fees/op*10000, funding_bps=funding_cost/op*10000,
                           net_bps=(price_pnl-fees-funding_cost)/op*10000, funding_events=payments))
    return output


def event_summary(rows):
    frame = pd.DataFrame(rows)
    values = frame.groupby(frame.entry_time.str[:10]).net_bps.mean().to_numpy()
    rng = np.random.default_rng(19092026)
    n = len(values)
    samples = []
    for _ in range(2000):
        starts = rng.integers(0, n, size=(n+27)//28)
        idx = ((starts[:, None]+np.arange(28)) % n).ravel()[:n]
        samples.append(float(values[idx].mean()))
    return dict(sessions=len(rows), mean_gross_bps=float(frame.gross_bps.mean()),
                mean_net_bps=float(frame.net_bps.mean()), mean_fee_bps=float(frame.fee_bps.mean()),
                mean_execution_bps=float(frame.execution_bps.mean()), mean_funding_bps=float(frame.funding_bps.mean()),
                daily_equal_weight_mean_net_bps=float(values.mean()),
                daily_mean_net_bps_exploratory_interval=np.quantile(samples, [.025, .975]).tolist(),
                by_year={str(y):dict(sessions=len(g), mean_net_bps=float(g.net_bps.mean()))
                         for y,g in frame.groupby(frame.entry_time.str[:4])})
