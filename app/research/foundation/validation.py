"""Strict design validation. Does not load price rows or run strategies."""
import hashlib
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .contracts import (
    CostAssumptions,
    EvaluationWindow,
    FileReference,
    MatchingDesign,
    ResearchDesign,
)


class DesignError(ValueError):
    """The design or one of its pinned references is invalid."""


def _object(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DesignError(f'{label}: expected an object')
    missing = keys - value.keys()
    unknown = value.keys() - keys
    if missing or unknown:
        raise DesignError(f'{label}: missing={sorted(missing)}, unknown={sorted(unknown)}')
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DesignError(f'{label}: expected nonempty text')
    return value


def _integer(value: Any, label: str, minimum: int = 1) -> int:
    if type(value) is not int or value < minimum:
        raise DesignError(f'{label}: expected integer >= {minimum}')
    return value


def _number(value: Any, label: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise DesignError(f'{label}: expected finite nonnegative number')
    return float(value)


def _utc(value: Any, label: str) -> datetime:
    try:
        result = datetime.fromisoformat(_text(value, label).replace('Z', '+00:00'))
    except ValueError as exc:
        raise DesignError(f'{label}: invalid ISO timestamp') from exc
    if result.tzinfo is None or result.utcoffset() != timedelta(0):
        raise DesignError(f'{label}: timezone-aware UTC required')
    if result.hour or result.minute or result.second or result.microsecond:
        raise DesignError(f'{label}: evaluation boundaries must be UTC midnight')
    return result.astimezone(timezone.utc)


def _list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list) or not value:
        raise DesignError(f'{label}: expected nonempty list')
    return value


def _reference(value: Any, label: str) -> FileReference:
    obj = _object(value, {'path', 'sha256'}, label)
    digest = _text(obj['sha256'], f'{label}.sha256')
    if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
        raise DesignError(f'{label}: expected lowercase SHA-256')
    return FileReference(_text(obj['path'], f'{label}.path'), digest)


def _edges(value: Any, label: str) -> tuple[float, ...]:
    edges = tuple(_number(item, label) for item in _list(value, label))
    if len(edges) < 2 or edges[0] != 0 or any(a >= b for a, b in zip(edges, edges[1:])):
        raise DesignError(f'{label}: bins must start at zero and increase strictly')
    return edges


def parse_design(raw: Any) -> ResearchDesign:
    """Reject misspelled keys, ambiguous units and invalid experimental windows."""
    obj = _object(raw, set(ResearchDesign.__dataclass_fields__), 'design')
    if type(obj['schema_version']) is not int or obj['schema_version'] != 1:
        raise DesignError('unsupported schema_version')
    if obj['status'] != 'design':
        raise DesignError('this checker accepts design only, not registration or execution')
    if obj['previously_inspected'] is not True or obj['evidence_kind'] != 'retrospective_diagnostic':
        raise DesignError('current dataset must be disclosed as previously inspected retrospective evidence')
    references = tuple(_reference(item, 'reference') for item in _list(obj['references'], 'references'))
    if len({item.path for item in references}) != len(references):
        raise DesignError('duplicate reference path')
    horizons = tuple(_integer(item, 'horizon') for item in _list(obj['horizons_minutes'], 'horizons_minutes'))
    if tuple(sorted(set(horizons))) != horizons:
        raise DesignError('horizons must be unique and increasing')
    primary = _integer(obj['primary_horizon_minutes'], 'primary_horizon_minutes')
    if primary not in horizons:
        raise DesignError('primary horizon is not measured')
    windows = []
    for value in _list(obj['windows'], 'windows'):
        item = _object(value, {'name', 'start', 'end'}, 'window')
        window = EvaluationWindow(
            name=_text(item['name'], 'window.name'),
            start=_utc(item['start'], 'window.start'),
            end=_utc(item['end'], 'window.end'),
        )
        if window.start >= window.end:
            raise DesignError('window must have positive duration')
        if windows and window.start < windows[-1].end:
            raise DesignError('windows must be ordered and non-overlapping')
        windows.append(window)
    if len({window.name for window in windows}) != len(windows):
        raise DesignError('duplicate window name')
    match = _object(obj['matching'], set(MatchingDesign.__dataclass_fields__), 'matching')
    if match['volatility_open_upper_bin'] is not True:
        raise DesignError('volatility bins require an explicit open upper interval')
    matching = MatchingDesign(
        lookback_days=_integer(match['lookback_days'], 'lookback_days'),
        controls_per_signal=_integer(match['controls_per_signal'], 'controls_per_signal'),
        random_seed=_integer(match['random_seed'], 'random_seed', minimum=0),
        utc_bucket_hours=_integer(match['utc_bucket_hours'], 'utc_bucket_hours'),
        efficiency_ratio_edges=_edges(match['efficiency_ratio_edges'], 'efficiency_ratio_edges'),
        volatility_ratio_edges=_edges(match['volatility_ratio_edges'], 'volatility_ratio_edges'),
        volatility_open_upper_bin=True,
    )
    if 24 % matching.utc_bucket_hours or matching.utc_bucket_hours > 24:
        raise DesignError('UTC buckets must divide a 24-hour day')
    if matching.lookback_days * 1440 <= max(horizons):
        raise DesignError('control lookback must exceed the outcome embargo')
    warmup = _integer(obj['warmup_days'], 'warmup_days')
    if warmup < matching.lookback_days:
        raise DesignError('warmup is shorter than control history')
    delay = _integer(obj['decision_delay_minutes'], 'decision_delay_minutes')
    if matching.lookback_days * 1440 <= delay + max(horizons):
        raise DesignError('control history cannot cover decision delay and outcome embargo')
    for window in windows:
        if (window.end - window.start).total_seconds() <= (delay + max(horizons)) * 60:
            raise DesignError('window cannot contain a complete outcome')
    costs_raw = _object(obj['costs'], set(CostAssumptions.__dataclass_fields__), 'costs')
    costs = CostAssumptions(
        taker_fee_bps=_number(costs_raw['taker_fee_bps'], 'taker_fee_bps'),
        slippage_bps=_number(costs_raw['slippage_bps'], 'slippage_bps'),
        interpretation=_text(costs_raw['interpretation'], 'cost interpretation'),
    )
    if costs.taker_fee_bps >= 10000 or costs.slippage_bps >= 10000:
        raise DesignError('per-side costs must be below 10000 basis points')
    return ResearchDesign(
        schema_version=1,
        experiment_id=_text(obj['experiment_id'], 'experiment_id'),
        status='design',
        question=_text(obj['question'], 'question'),
        evidence_kind='retrospective_diagnostic',
        previously_inspected=True,
        dataset=_reference(obj['dataset'], 'dataset'),
        references=references,
        signal_name=_text(obj['signal_name'], 'signal_name'),
        warmup_days=warmup,
        decision_delay_minutes=delay,
        horizons_minutes=horizons,
        primary_horizon_minutes=primary,
        windows=tuple(windows),
        matching=matching,
        bootstrap_block_days=_integer(obj['bootstrap_block_days'], 'bootstrap_block_days'),
        bootstrap_repetitions=_integer(obj['bootstrap_repetitions'], 'bootstrap_repetitions'),
        costs=costs,
    )


def _verify_file(root: Path, reference: FileReference) -> Path:
    relative = Path(reference.path)
    path = (root / relative).resolve()
    if relative.is_absolute() or not path.is_relative_to(root):
        raise DesignError(f'reference must stay inside project: {reference.path}')
    if not path.is_file():
        raise DesignError(f'missing reference: {reference.path}')
    if hashlib.sha256(path.read_bytes()).hexdigest() != reference.sha256:
        raise DesignError(f'changed reference: {reference.path}')
    return path


def validate_references(design: ResearchDesign, project_root: Path) -> None:
    """Verify pinned evidence and coverage, not exchange authenticity or price rows."""
    root = project_root.resolve()
    manifest_path = _verify_file(root, design.dataset)
    for reference in design.references:
        _verify_file(root, reference)
    manifest = json.loads(manifest_path.read_text())
    if manifest.get('status') != 'PASS' or manifest.get('errors'):
        raise DesignError('dataset quality report did not pass')
    if manifest.get('symbol') != 'BTCUSDT' or manifest.get('source_grain') != '1m':
        raise DesignError('E001 requires the declared BTCUSDT 1-minute proxy')
    start = _utc(manifest.get('start'), 'dataset.start')
    end = _utc(manifest.get('end_exclusive'), 'dataset.end_exclusive')
    expected_minutes = int((end - start).total_seconds() / 60)
    if manifest.get('row_count') != expected_minutes or manifest.get('unique_minutes') != expected_minutes:
        raise DesignError('manifest row count does not support complete minute coverage')
    for window in design.windows:
        if window.start < start + timedelta(days=design.warmup_days) or window.end > end:
            raise DesignError(f'window exceeds dataset or warmup coverage: {window.name}')


def load_design(path: Path, project_root: Path) -> ResearchDesign:
    """Read a UTF-8 JSON design, reject duplicate keys, and verify its references."""
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result = {}
        for key, value in pairs:
            if key in result:
                raise DesignError(f'duplicate JSON key: {key}')
            result[key] = value
        return result

    design = parse_design(json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique_object))
    validate_references(design, project_root)
    return design
