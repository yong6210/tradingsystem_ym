"""Pinned USD-M minute taker aggregates, separate from frozen OHLCV loaders."""
import io
import json
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import pandas as pd

from .btcusdc import checked_bytes
from .minutes import validate_minutes

FIELDS = ['open_time', 'open', 'high', 'low', 'close', 'volume', 'close_time',
          'quote_volume', 'count', 'taker_buy_volume', 'taker_buy_quote_volume']
FLOW = ['v', 'quote_volume', 'count', 'taker_buy_volume', 'taker_buy_quote_volume']


def parse_flow(raw, member):
    with ZipFile(io.BytesIO(raw)) as archive:
        with archive.open(member) as source:
            f = pd.read_csv(source, usecols=FIELDS)
    f = f.apply(pd.to_numeric, errors='raise')
    if not np.isfinite(f.to_numpy()).all():
        raise ValueError('nonfinite flow source')
    opening, closing = f.pop('open_time'), f.pop('close_time')
    if ((opening % 60000 != 0) | (closing != opening + 59999)).any():
        raise ValueError('invalid minute timestamp or close time')
    f.index = pd.to_datetime(opening.to_numpy(dtype='int64'), unit='ms', utc=True)
    f = f.rename(columns=dict(open='o', high='h', low='l', close='c', volume='v'))
    validate_flow(f)
    return f


def validate_flow(f):
    validate_minutes(f[['o', 'h', 'l', 'c', 'v']])
    if not np.isfinite(f[FLOW].to_numpy()).all() or (f[FLOW] < 0).any().any():
        raise ValueError('nonfinite or negative flow')
    if (f['count'] != np.floor(f['count'])).any():
        raise ValueError('nonintegral trade count')
    if ((f.taker_buy_volume > f.v + 1e-8) |
            (f.taker_buy_quote_volume > f.quote_volume + 1e-5)).any():
        raise ValueError('taker buy exceeds total')
    zero = f.v == 0
    if (zero != (f['count'] == 0)).any() or (zero != (f.quote_volume == 0)).any():
        raise ValueError('zero volume/count inconsistency')
    if (f.loc[zero, ['taker_buy_volume', 'taker_buy_quote_volume']] != 0).any().any():
        raise ValueError('nonzero buy on empty minute')
    # Quote totals must lie within the candle's price range, separately for
    # taker buys and inferred taker sells; tolerate decimal-to-float rounding.
    for qty, quote in ((f.v, f.quote_volume), (f.taker_buy_volume, f.taker_buy_quote_volume),
                       (f.v - f.taker_buy_volume, f.quote_volume - f.taker_buy_quote_volume)):
        tolerance = 1e-5 + f.quote_volume * 1e-10
        if ((quote < qty * f.l - tolerance) | (quote > qty * f.h + tolerance)).any():
            raise ValueError('base/quote totals inconsistent with OHLC')


def profile(f):
    return dict(rows=len(f), start=f.index[0].isoformat(),
                end_exclusive=(f.index[-1] + pd.Timedelta(minutes=1)).isoformat(),
                zero_volume_minutes=int((f.v == 0).sum()),
                zero_buy_minutes=int((f.taker_buy_volume == 0).sum()),
                all_buy_minutes=int(((f.v > 0) & (f.taker_buy_volume == f.v)).sum()),
                trades=int(f['count'].sum()), volume_btc=float(f.v.sum()),
                buy_share=float(f.taker_buy_volume.sum() / f.v.sum()) if f.v.sum() else None)


def load_taker_flow(root: Path, directory: Path):
    manifest = json.loads((directory / 'manifest.json').read_text())
    if manifest['symbol'] != 'BTCUSDC':
        raise ValueError('wrong flow symbol')
    records = sorted((r for r in manifest['archives'] if r['kind'] == 'klines'),
                     key=lambda r: r['month'])
    if len(records) != 32 or len({r['month'] for r in records}) != 32:
        raise ValueError('unexpected flow archive coverage')
    frames, monthly = [], []
    for r in records:
        frame = parse_flow(checked_bytes(root, r), Path(r['path']).stem + '.csv')
        if len(frame) != r['rows']:
            raise ValueError('flow row count changed')
        monthly.append(dict(month=r['month'], sha256=r['sha256'], **profile(frame)))
        frames.append(frame)
    frame = pd.concat(frames)
    validate_flow(frame)
    return frame, dict(status='PASS_SCOPED_AGGREGATES', archives=32,
                       full_source=profile(frame), monthly=monthly,
                       limitation='Archive aggregates; no book, trade sequence, receipt latency or fill evidence')


def completed_flow(frame, period=60):
    """Volume-weighted fraction, indexed at candle completion; zero is unknown."""
    validate_flow(frame)
    grouped = frame[FLOW].resample(f'{period}min', origin='epoch', label='left', closed='left')
    count = grouped.v.count()
    result = grouped.sum().loc[count == period].copy()
    result.index += pd.Timedelta(minutes=period)
    result['buy_share'] = result.taker_buy_volume / result.v.replace(0, np.nan)
    return result
