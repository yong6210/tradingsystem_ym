from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import inspect
from sqlalchemy.sql import text


@dataclass(frozen=True, slots=True)
class AltDataDatasetRequirement:
    dataset_key: str
    candidate_tables: tuple[str, ...]
    required_columns: tuple[str, ...]
    description: str


@dataclass(frozen=True, slots=True)
class AltDataFamilySpec:
    key: str
    regime_hint: str
    thesis: str
    required_datasets: tuple[str, ...]


DATASET_REQUIREMENTS: dict[str, AltDataDatasetRequirement] = {
    "funding_rate": AltDataDatasetRequirement(
        dataset_key="funding_rate",
        candidate_tables=("funding_rates", "binance_funding_rates", "perp_funding_rates"),
        required_columns=("symbol", "ts", "funding_rate"),
        description="Historical perp funding series for crowding and carry state.",
    ),
    "open_interest": AltDataDatasetRequirement(
        dataset_key="open_interest",
        candidate_tables=("open_interest", "binance_open_interest", "perp_open_interest"),
        required_columns=("symbol", "ts", "open_interest"),
        description="Historical open interest series for leverage expansion / squeeze state.",
    ),
    "basis": AltDataDatasetRequirement(
        dataset_key="basis",
        candidate_tables=("basis_snapshots", "perp_basis", "mark_index_basis"),
        required_columns=("symbol", "ts", "basis_bps"),
        description="Historical mark/index or perp/spot basis spread.",
    ),
    "liquidations": AltDataDatasetRequirement(
        dataset_key="liquidations",
        candidate_tables=("liquidation_events", "liquidations", "forced_liquidations"),
        required_columns=("symbol", "ts", "side", "notional"),
        description="Historical liquidation tape for cascade absorption / exhaustion setups.",
    ),
    "macro_events": AltDataDatasetRequirement(
        dataset_key="macro_events",
        candidate_tables=("macro_events", "economic_calendar", "scheduled_events"),
        required_columns=("event_ts", "event_code", "importance"),
        description="Scheduled event calendar for macro shock gating.",
    ),
    "cross_asset_breadth": AltDataDatasetRequirement(
        dataset_key="cross_asset_breadth",
        candidate_tables=("cross_asset_breadth", "breadth_snapshots", "pair_breadth"),
        required_columns=("ts", "leader_symbol", "confirm_symbol", "breadth_score"),
        description="Pair/breadth structure for divergence and confirmation families.",
    ),
}


def default_alt_data_family_specs() -> tuple[AltDataFamilySpec, ...]:
    return (
        AltDataFamilySpec(
            key="funding_oi_squeeze_reversal",
            regime_hint="transition",
            thesis="Crowded perp positioning unwinds after extreme funding + OI expansion.",
            required_datasets=("funding_rate", "open_interest"),
        ),
        AltDataFamilySpec(
            key="basis_dislocation_mean_reversion",
            regime_hint="intraday_reversion",
            thesis="Perp basis dislocation snaps back when spread extremes revert.",
            required_datasets=("basis",),
        ),
        AltDataFamilySpec(
            key="oi_breakout_confirmation",
            regime_hint="trend",
            thesis="Trend continuation only when breakout is confirmed by rising OI.",
            required_datasets=("open_interest",),
        ),
        AltDataFamilySpec(
            key="liquidation_cascade_absorption",
            regime_hint="transition",
            thesis="Forced liquidation burst followed by absorption reversal.",
            required_datasets=("liquidations",),
        ),
        AltDataFamilySpec(
            key="event_basis_dislocation",
            regime_hint="event_shock",
            thesis="Macro event shock filtered by concurrent basis/funding dislocation.",
            required_datasets=("macro_events", "basis", "funding_rate"),
        ),
        AltDataFamilySpec(
            key="breadth_divergence_rotation",
            regime_hint="cross_asset",
            thesis="Cross-asset breadth divergence rotates into laggard / away from failed leader.",
            required_datasets=("cross_asset_breadth",),
        ),
    )


def inspect_alt_data_feasibility(*, bind: Any) -> dict[str, Any]:
    inspector = inspect(bind)
    table_names = set(inspector.get_table_names())
    columns_by_table: dict[str, set[str]] = {}
    for table_name in table_names:
        try:
            columns_by_table[table_name] = {str(item.get("name") or "") for item in inspector.get_columns(table_name)}
        except Exception:
            columns_by_table[table_name] = set()

    datasets_payload: dict[str, Any] = {}
    for dataset_key, requirement in DATASET_REQUIREMENTS.items():
        matched_table = None
        missing_columns: list[str] = []
        for table_name in requirement.candidate_tables:
            if table_name not in table_names:
                continue
            required = set(requirement.required_columns)
            present = columns_by_table.get(table_name, set())
            if required.issubset(present):
                matched_table = table_name
                missing_columns = []
                break
            if matched_table is None:
                matched_table = table_name
                missing_columns = sorted(required - present)
        datasets_payload[dataset_key] = {
            "description": requirement.description,
            "candidate_tables": list(requirement.candidate_tables),
            "matched_table": matched_table,
            "row_count": 0,
            "available": False,
            "missing_columns": missing_columns,
        }
        if matched_table is not None and not missing_columns:
            try:
                with bind.connect() as conn:
                    row_count = int(conn.execute(text(f"SELECT COUNT(*) FROM {matched_table}")).scalar() or 0)
            except Exception:
                row_count = 0
            datasets_payload[dataset_key]["row_count"] = row_count
            datasets_payload[dataset_key]["available"] = row_count > 0

    families_payload: dict[str, Any] = {}
    for spec in default_alt_data_family_specs():
        missing_datasets = [key for key in spec.required_datasets if not bool(datasets_payload.get(key, {}).get("available", False))]
        families_payload[spec.key] = {
            "regime_hint": spec.regime_hint,
            "thesis": spec.thesis,
            "required_datasets": list(spec.required_datasets),
            "missing_datasets": missing_datasets,
            "decision": "BLOCKED_MISSING_DATA" if missing_datasets else "READY_FOR_RESEARCH",
        }

    return {
        "datasets": datasets_payload,
        "families": families_payload,
    }
