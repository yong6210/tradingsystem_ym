"""Immutable, explicitly typed inputs for the first research design.

Times are timezone-aware UTC. Windows are start-inclusive, end-exclusive.
Fees and slippage are per-side basis points, never percentage fractions.
"""
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class FileReference:
    path: str
    sha256: str


@dataclass(frozen=True)
class EvaluationWindow:
    name: str
    start: datetime
    end: datetime


@dataclass(frozen=True)
class MatchingDesign:
    lookback_days: int
    controls_per_signal: int
    random_seed: int
    utc_bucket_hours: int
    efficiency_ratio_edges: tuple[float, ...]
    volatility_ratio_edges: tuple[float, ...]
    volatility_open_upper_bin: bool


@dataclass(frozen=True)
class CostAssumptions:
    taker_fee_bps: float
    slippage_bps: float
    interpretation: str


@dataclass(frozen=True)
class ResearchDesign:
    schema_version: int
    experiment_id: str
    status: str
    question: str
    evidence_kind: str
    previously_inspected: bool
    dataset: FileReference
    references: tuple[FileReference, ...]
    signal_name: str
    warmup_days: int
    decision_delay_minutes: int
    horizons_minutes: tuple[int, ...]
    primary_horizon_minutes: int
    windows: tuple[EvaluationWindow, ...]
    matching: MatchingDesign
    bootstrap_block_days: int
    bootstrap_repetitions: int
    costs: CostAssumptions
