"""E010 entry-only overlays using lagged funding and a named basis proxy."""
import numpy as np
import pandas as pd

MODELS = ('T0', 'S09F', 'S09B', 'S09FB')
FUNDING_LAG_MS = 60_000
FUNDING_MAX_AGE_MS = 12 * 3600_000
FUNDING_HISTORY = 90
BASIS_HISTORY = 180


def funding_context(times, events):
    if str(times.tz) != 'UTC' or times.has_duplicates or not times.is_monotonic_increasing:
        raise ValueError('ordered unique UTC observations required')
    if not events:
        raise ValueError('funding source required')
    stamp = np.array([e['fundingTime'] for e in events], dtype=np.int64)
    rate = np.array([float(e['fundingRate']) for e in events])
    if (any(type(e['fundingTime']) is not int or e['symbol'] != 'BTCUSDC' for e in events)
            or (np.diff(stamp) <= 0).any() or not np.isfinite(rate).all()):
        raise ValueError('invalid funding series')
    history = pd.Series(rate).shift(1).rolling(FUNDING_HISTORY)
    lo, hi = history.quantile(.1).to_numpy(), history.quantile(.9).to_numpy()
    observed = times.asi8 // 1_000_000
    locations = np.searchsorted(stamp + FUNDING_LAG_MS, observed, side='right') - 1
    valid = locations >= 0
    safe = np.maximum(locations, 0)
    data = pd.DataFrame(dict(funding_ms=np.where(valid, stamp[safe], -1),
                             funding_rate=np.where(valid, rate[safe], np.nan),
                             funding_low=np.where(valid, lo[safe], np.nan),
                             funding_high=np.where(valid, hi[safe], np.nan)), index=times)
    data['funding_ready'] = (valid & np.isfinite(data.funding_low) & np.isfinite(data.funding_high)
                             & (observed - data.funding_ms <= FUNDING_MAX_AGE_MS))
    return data


def basis_context(times, mark, index_price):
    if str(times.tz) != 'UTC' or times.has_duplicates or not times.is_monotonic_increasing:
        raise ValueError('ordered unique UTC observations required')
    if len(times) > 1 and (np.diff(times.asi8) != 240 * 60_000_000_000).any():
        raise ValueError('basis history needs a continuous four-hour clock')
    if not mark.index.equals(index_price.index) or mark.index.has_duplicates or not mark.index.is_monotonic_increasing:
        raise ValueError('mark/index alignment required')
    # The close of minute t-1 is known at t. No current-minute high/close,
    # interpolation, forward fill or future settlement mark is used.
    source = times - pd.Timedelta(minutes=1)
    m, p = (f.c.reindex(source).to_numpy() for f in (mark, index_price))
    valid = np.isfinite(m) & np.isfinite(p) & (m > 0) & (p > 0)
    ratio = np.full(len(times), np.nan)
    ratio[valid] = m[valid] / p[valid] - 1
    basis = pd.Series(ratio, index=times)
    history = basis.shift(1).rolling(BASIS_HISTORY)
    result = pd.DataFrame(dict(basis=basis, basis_low=history.quantile(.1),
                               basis_high=history.quantile(.9)), index=times)
    result['basis_ready'] = np.isfinite(result).all(axis=1)
    return result


def admission(side, row, model):
    if side not in (-1, 0, 1) or model not in MODELS:
        raise ValueError('unsupported side/model')
    if model == 'T0' or side == 0:
        return True
    if model in ('S09F', 'S09FB'):
        if not row.funding_ready:
            return False
        if ((side == 1 and row.funding_rate > max(0., row.funding_high)) or
                (side == -1 and row.funding_rate < min(0., row.funding_low))):
            return False
    if model in ('S09B', 'S09FB'):
        if not row.basis_ready:
            return False
        if ((side == 1 and row.basis > max(0., row.basis_high)) or
                (side == -1 and row.basis < min(0., row.basis_low))):
            return False
    return True


def build_crowding_policies(minutes, core, context):
    result = {m: {} for m in MODELS}
    previous_core = 0
    for i, (side, close, atr) in sorted(core.items()):
        completed = minutes.index[i] - pd.Timedelta(minutes=1)
        row = context.loc[completed]
        for model in MODELS:
            if admission(side, row, model):
                result[model][i] = (side, close, atr)
            elif side != previous_core:
                # Close an old/opposite position even when the NEW direction
                # is blocked. A veto must never prevent reducing risk.
                result[model][i] = (0, close, atr)
            # Same core direction, blocked: no new command. Existing holdings
            # keep their original protection; no spurious filter-driven exit.
        previous_core = side
    return result
