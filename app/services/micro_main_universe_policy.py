from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


def _safe_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off", "none", "null", ""}:
        return False
    return bool(default)


@dataclass(frozen=True, slots=True)
class MicroMainUniverseEntry:
    symbol: str
    tier: str
    rollout_priority: int
    risk_multiplier: float
    benchmark_ev_r: float
    benchmark_win_rate: float
    rationale: str


_ENTRIES: tuple[MicroMainUniverseEntry, ...] = (
    MicroMainUniverseEntry(
        symbol="BTCUSDC",
        tier="core",
        rollout_priority=1,
        risk_multiplier=0.90,
        benchmark_ev_r=0.3520,
        benchmark_win_rate=0.57,
        rationale="Anchor symbol, but haircut the live risk slightly because its recent loser density is higher than ETH/SOL.",
    ),
    MicroMainUniverseEntry(
        symbol="ETHUSDC",
        tier="core",
        rollout_priority=2,
        risk_multiplier=1.00,
        benchmark_ev_r=0.6187,
        benchmark_win_rate=0.66,
        rationale="Strong 1y/2y retention with deep liquidity; co-anchor with BTC.",
    ),
    MicroMainUniverseEntry(
        symbol="SOLUSDC",
        tier="core",
        rollout_priority=3,
        risk_multiplier=0.90,
        benchmark_ev_r=0.7701,
        benchmark_win_rate=0.72,
        rationale="Best combined EV and frequency in the family; slightly discounted for liquidity discipline.",
    ),
    MicroMainUniverseEntry(
        symbol="LINKUSDC",
        tier="core",
        rollout_priority=4,
        risk_multiplier=0.85,
        benchmark_ev_r=0.7118,
        benchmark_win_rate=0.68,
        rationale="Very strong 2y edge retention; promoted into the core universe.",
    ),
    MicroMainUniverseEntry(
        symbol="BNBUSDC",
        tier="core",
        rollout_priority=5,
        risk_multiplier=0.75,
        benchmark_ev_r=0.6275,
        benchmark_win_rate=0.71,
        rationale="Good 1y/2y profile with lower frequency than the top core names.",
    ),
    MicroMainUniverseEntry(
        symbol="XRPUSDC",
        tier="core",
        rollout_priority=6,
        risk_multiplier=0.60,
        benchmark_ev_r=0.5988,
        benchmark_win_rate=0.56,
        rationale="Positive long-horizon profile, but keep a larger haircut because recent loser density is the highest in the core basket.",
    ),
    MicroMainUniverseEntry(
        symbol="ADAUSDC",
        tier="core",
        rollout_priority=7,
        risk_multiplier=0.55,
        benchmark_ev_r=0.7280,
        benchmark_win_rate=0.67,
        rationale="Strong retained edge with acceptable trust/liquidity; promoted into the expanded live universe with a reduced risk multiplier.",
    ),
    MicroMainUniverseEntry(
        symbol="AVAXUSDC",
        tier="core",
        rollout_priority=8,
        risk_multiplier=0.35,
        benchmark_ev_r=0.4914,
        benchmark_win_rate=0.60,
        rationale="Weakest live symbol in the current basket by retained EV/loser density; keep it live, but haircut risk further to limit stop-cluster damage.",
    ),
    MicroMainUniverseEntry(
        symbol="SUIUSDC",
        tier="secondary",
        rollout_priority=9,
        risk_multiplier=0.45,
        benchmark_ev_r=0.7741,
        benchmark_win_rate=0.68,
        rationale="Strong 1y/2y baseline profile after full backfill, but keep it shadow-first until live execution evidence exists.",
    ),
    MicroMainUniverseEntry(
        symbol="BCHUSDC",
        tier="core",
        rollout_priority=10,
        risk_multiplier=0.45,
        benchmark_ev_r=0.7362,
        benchmark_win_rate=0.70,
        rationale="High-trust legacy major with strong long-horizon baseline edge; promoted live with conservative sizing.",
    ),
    MicroMainUniverseEntry(
        symbol="LTCUSDC",
        tier="core",
        rollout_priority=11,
        risk_multiplier=0.45,
        benchmark_ev_r=0.6338,
        benchmark_win_rate=0.66,
        rationale="Mature major coin with stable 1y/2y baseline edge; promoted into live on a conservative multiplier.",
    ),
    MicroMainUniverseEntry(
        symbol="NEARUSDC",
        tier="core",
        rollout_priority=12,
        risk_multiplier=0.40,
        benchmark_ev_r=0.6822,
        benchmark_win_rate=0.66,
        rationale="Good 2y baseline retention with acceptable liquidity profile; promoted live with reduced sizing.",
    ),
    MicroMainUniverseEntry(
        symbol="AAVEUSDC",
        tier="secondary",
        rollout_priority=13,
        risk_multiplier=0.35,
        benchmark_ev_r=0.5450,
        benchmark_win_rate=0.63,
        rationale="Promising baseline edge, but history only begins in mid-2025 so it stays shadow-only for now.",
    ),
    MicroMainUniverseEntry(
        symbol="HBARUSDC",
        tier="secondary",
        rollout_priority=14,
        risk_multiplier=0.45,
        benchmark_ev_r=0.7161,
        benchmark_win_rate=0.678,
        rationale="Top-30 trust/liquidity candidate with strong retained 3y proxy edge; add it as a shadow-first candidate pending runtime evidence.",
    ),
)

_ENTRY_MAP = {entry.symbol: entry for entry in _ENTRIES}


def micro_main_universe_entry(symbol: str) -> dict[str, Any] | None:
    entry = _ENTRY_MAP.get(str(symbol or "").upper())
    return asdict(entry) if entry else None


def build_micro_main_universe_policy_snapshot() -> dict[str, Any]:
    return {
        "family": "session_impulse_retest",
        "core_symbols": [entry.symbol for entry in _ENTRIES if entry.tier == "core"],
        "secondary_symbols": [entry.symbol for entry in _ENTRIES if entry.tier == "secondary"],
        "allowed_symbols": [entry.symbol for entry in _ENTRIES],
        "partial_activation_priority": [
            entry.symbol
            for entry in sorted(_ENTRIES, key=lambda item: item.rollout_priority)
        ],
        "risk_multipliers": {
            entry.symbol: round(float(entry.risk_multiplier), 4)
            for entry in _ENTRIES
        },
        "entries": [asdict(entry) for entry in _ENTRIES],
        "policy_note": (
            "Core symbols are eligible for the first live rollout after shadow validation. "
            "Secondary symbols remain shadow-first and should receive lower risk caps."
        ),
    }


def build_micro_main_rollout_contract_snapshot(
    *,
    enabled: bool,
    shadow_only: bool,
    partial_activation_ratio: float,
    core_live_slots: int,
    secondary_live_enabled: bool,
) -> dict[str, Any]:
    snapshot = build_micro_main_universe_policy_snapshot()
    snapshot["rollout_contract"] = {
        "enabled": _safe_bool(enabled),
        "shadow_only": _safe_bool(shadow_only),
        "partial_activation_ratio": round(float(partial_activation_ratio), 4),
        "core_live_slots": max(int(core_live_slots), 0),
        "secondary_live_enabled": _safe_bool(secondary_live_enabled),
    }
    return snapshot
