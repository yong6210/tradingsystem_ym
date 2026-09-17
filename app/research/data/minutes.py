"""Read pinned monthly archives without silently filling missing minutes."""
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import pandas as pd


def validate_minutes(frame: pd.DataFrame) -> None:
    """Require ordered UTC minute OHLCV observations and valid price geometry."""
    if frame.empty or list(frame.columns) != ['o', 'h', 'l', 'c', 'v']:
        raise ValueError('expected nonempty OHLCV frame')
    if not isinstance(frame.index, pd.DatetimeIndex) or str(frame.index.tz) != 'UTC':
        raise ValueError('UTC datetime index required')
    timestamps = frame.index.asi8
    if (timestamps % 60_000_000_000 != 0).any():
        raise ValueError('unaligned minute')
    if (np.diff(timestamps) != 60_000_000_000).any():
        raise ValueError('duplicate, unordered or missing minute')
    if not np.isfinite(frame.to_numpy()).all():
        raise ValueError('nonfinite market value')
    if (frame[['o', 'h', 'l', 'c']] <= 0).any().any() or (frame.v < 0).any():
        raise ValueError('nonpositive price or negative volume')
    if ((frame.h < frame[['o', 'c']].max(axis=1)) |
            (frame.l > frame[['o', 'c']].min(axis=1))).any():
        raise ValueError('invalid OHLC geometry')


def load_verified_minutes(manifest_path: Path) -> pd.DataFrame:
    """Recheck archive bytes and the resulting continuous sequence."""
    manifest = json.loads(manifest_path.read_text())
    if manifest.get('status') != 'PASS':
        raise ValueError('quality manifest did not pass')
    frames = []
    for record in manifest['files']:
        path = Path(record['path'])
        with path.open('rb') as source:
            if hashlib.file_digest(source, 'sha256').hexdigest() != record['sha256']:
                raise ValueError(f'changed archive: {path.name}')
        with ZipFile(path) as archive:
            with archive.open(path.stem + '.csv') as source:
                frame = pd.read_csv(source, header=None, usecols=range(6),
                                    names=['timestamp', 'o', 'h', 'l', 'c', 'v'])
        if str(frame.iloc[0]['timestamp']) == 'open_time':
            frame = frame.iloc[1:].copy()
        timestamps = frame.pop('timestamp').astype('int64')
        timestamps = np.where(timestamps >= 100_000_000_000_000, timestamps // 1000, timestamps)
        frame.index = pd.to_datetime(timestamps, unit='ms', utc=True)
        frames.append(frame.astype(float))
    result = pd.concat(frames)
    validate_minutes(result)
    if len(result) != manifest['row_count']:
        raise ValueError('row count differs from manifest')
    if (result.index[0] != pd.Timestamp(manifest['start']) or
            result.index[-1] + pd.Timedelta(minutes=1) != pd.Timestamp(manifest['end_exclusive'])):
        raise ValueError('coverage differs from manifest')
    return result
