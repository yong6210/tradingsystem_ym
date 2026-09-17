"""Verified public BTCUSDC bundle. Missing mark/index prices remain NaN."""
from dataclasses import dataclass
import hashlib
import io
import json
from pathlib import Path
from zipfile import ZipFile
import numpy as np
import pandas as pd
from .minutes import validate_minutes


@dataclass
class PublicBundle:
    trade: pd.DataFrame
    mark: pd.DataFrame
    index_price: pd.DataFrame
    funding: list[dict]

    def require_complete_window(self, start, end):
        """Reject a full-price run with any gap. Never erase open risk at a gap.

        No forced pre-gap exit: knowing a future data outage would be lookahead.
        Trade-only diagnostics must explicitly bypass this full-price contract.
        """
        start, end = pd.Timestamp(start), pd.Timestamp(end)
        if start.tzinfo is None or end.tzinfo is None or start >= end:
            raise ValueError('invalid UTC-aware window')
        for frame in (self.trade, self.mark, self.index_price):
            selected = frame.loc[(frame.index >= start) & (frame.index < end)]
            validate_minutes(selected)
            if selected.index[0] != start or selected.index[-1] + pd.Timedelta(minutes=1) != end:
                raise ValueError('incomplete requested window')


def checked_bytes(root, record):
    raw = (root / record['path']).read_bytes()
    if hashlib.sha256(raw).hexdigest() != record['sha256']:
        raise ValueError('changed source: ' + record['path'])
    return raw


def frame_from_csv(raw, member):
    with ZipFile(io.BytesIO(raw)) as archive:
        with archive.open(member) as source:
            frame = pd.read_csv(source, usecols=['open_time','open','high','low','close','volume'])
    frame = frame.rename(columns=dict(open='o',high='h',low='l',close='c',volume='v'))
    times = pd.to_numeric(frame.pop('open_time'), errors='raise')
    if (times != np.floor(times)).any():
        raise ValueError('nonintegral timestamp')
    frame.index = pd.to_datetime(times.astype('int64'), unit='ms', utc=True)
    return frame[['o','h','l','c','v']].astype(float)


def align_prices(frame, index):
    if frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
        raise ValueError('duplicate or unordered prices')
    # Validate every observed row without declaring absent rows present.
    if frame.empty or not np.isfinite(frame.to_numpy()).all():
        raise ValueError('empty or nonfinite observed source')
    if (frame.index.asi8 % 60_000_000_000).any() or (frame[['o','h','l','c']] <= 0).any().any():
        raise ValueError('invalid time or price')
    if ((frame.h < frame[['o','c']].max(axis=1)) | (frame.l > frame[['o','c']].min(axis=1))).any():
        raise ValueError('invalid price geometry')
    return frame.reindex(index)


def load_public_bundle(root: Path, directory: Path) -> PublicBundle:
    manifest = json.loads((directory/'manifest.json').read_text())
    if manifest['symbol'] != 'BTCUSDC' or len(manifest['archives']) != 96:
        raise ValueError('unexpected dataset')
    grouped = {kind: [] for kind in ('klines','markPriceKlines','indexPriceKlines')}
    for record in manifest['archives']:
        raw = checked_bytes(root, record)
        frame = frame_from_csv(raw, Path(record['path']).stem + '.csv')
        if len(frame) != record['rows']:
            raise ValueError('changed row count')
        grouped[record['kind']].append(frame)
    overlay = json.loads((directory/'validated_overlay.json').read_text())
    if hashlib.sha256((directory/'gap_probe_manifest.json').read_bytes()).hexdigest() != overlay['source_manifest_sha256']:
        raise ValueError('changed overlay provenance')
    for record in overlay['supplements']:
        rows = json.loads(checked_bytes(root, record))
        if [r[0] for r in rows] != list(range(record['start_ms'],record['end_exclusive_ms'],60000)):
            raise ValueError('incomplete supplement')
        frame = pd.DataFrame([r[1:6] for r in rows], columns=['o','h','l','c','v'],
                             index=pd.to_datetime([r[0] for r in rows],unit='ms',utc=True)).astype(float)
        validate_minutes(frame)
        grouped[record['kind']].append(frame)
    frames = {kind: pd.concat(parts).sort_index() for kind, parts in grouped.items()}
    validate_minutes(frames['klines'])
    trade = frames['klines']
    mark = align_prices(frames['markPriceKlines'], trade.index)
    index_price = align_prices(frames['indexPriceKlines'], trade.index)
    funding = []
    for record in manifest['funding_sources']:
        funding.extend(json.loads(checked_bytes(root, record)))
    times = [r['fundingTime'] for r in funding]
    if times != sorted(set(times)) or len(times) != manifest['funding_summary']['events']:
        raise ValueError('funding ordering or count mismatch')
    for row in funding:
        if row['symbol'] != 'BTCUSDC' or not np.isfinite(float(row['fundingRate'])) or not np.isfinite(float(row['markPrice'])) or float(row['markPrice']) <= 0:
            raise ValueError('invalid funding')
    return PublicBundle(trade, mark, index_price, funding)
