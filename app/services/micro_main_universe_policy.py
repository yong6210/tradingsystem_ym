from __future__ import annotations

from dataclasses import asdict, dataclass
from collections.abc import Iterable
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
        symbol="1000PEPEUSDC",
        tier="core",
        rollout_priority=13,
        risk_multiplier=0.35,
        benchmark_ev_r=1.0035,
        benchmark_win_rate=0.7543,
        rationale="Top-20 selected expansion symbol with strong USDT-proxy edge; keep a conservative risk multiplier because live evidence is new.",
    ),
    MicroMainUniverseEntry(
        symbol="ARBUSDC",
        tier="core",
        rollout_priority=14,
        risk_multiplier=0.40,
        benchmark_ev_r=0.8633,
        benchmark_win_rate=0.7132,
        rationale="Top-20 selected expansion symbol with a tradable USDC perpetual and strong proxy edge.",
    ),
    MicroMainUniverseEntry(
        symbol="1000SHIBUSDC",
        tier="core",
        rollout_priority=15,
        risk_multiplier=0.35,
        benchmark_ev_r=0.9010,
        benchmark_win_rate=0.7273,
        rationale="Top-20 selected expansion symbol with full-window proxy evidence; keep meme exposure on reduced sizing.",
    ),
    MicroMainUniverseEntry(
        symbol="FILUSDC",
        tier="core",
        rollout_priority=16,
        risk_multiplier=0.45,
        benchmark_ev_r=0.8215,
        benchmark_win_rate=0.7031,
        rationale="Top-20 selected expansion symbol with mature proxy history and a tradable USDC perpetual.",
    ),
    MicroMainUniverseEntry(
        symbol="DOGEUSDC",
        tier="core",
        rollout_priority=17,
        risk_multiplier=0.45,
        benchmark_ev_r=0.8234,
        benchmark_win_rate=0.7123,
        rationale="Top-20 selected expansion symbol with mature proxy history and good retained edge.",
    ),
    MicroMainUniverseEntry(
        symbol="AAVEUSDC",
        tier="secondary",
        rollout_priority=18,
        risk_multiplier=0.35,
        benchmark_ev_r=0.5450,
        benchmark_win_rate=0.63,
        rationale="Promising baseline edge, but history only begins in mid-2025 so it stays shadow-only for now.",
    ),
    MicroMainUniverseEntry(
        symbol="HBARUSDC",
        tier="secondary",
        rollout_priority=19,
        risk_multiplier=0.45,
        benchmark_ev_r=0.7161,
        benchmark_win_rate=0.678,
        rationale="Top-30 trust/liquidity candidate with strong retained 3y proxy edge; add it as a shadow-first candidate pending runtime evidence.",
    ),
    MicroMainUniverseEntry(
        symbol="ZECUSDC",
        tier="secondary",
        rollout_priority=20,
        risk_multiplier=0.35,
        benchmark_ev_r=0.8316,
        benchmark_win_rate=0.7054,
        rationale="Top-50 USDC-tradable expansion candidate with strong 5y proxy EV; keep shadow-first because it is new to the live route.",
    ),
    MicroMainUniverseEntry(
        symbol="UNIUSDC",
        tier="secondary",
        rollout_priority=21,
        risk_multiplier=0.40,
        benchmark_ev_r=0.7570,
        benchmark_win_rate=0.6795,
        rationale="Top-50 USDC-tradable expansion candidate with mature 5y proxy history; keep shadow-first pending live-route evidence.",
    ),
)

_USDT_RELIABLE_BALANCED_31: tuple[MicroMainUniverseEntry, ...] = (
    MicroMainUniverseEntry("BTCUSDT", "core", 1, 0.90, 0.5781, 0.6617, "USDT reliable-balanced live universe member from the 3y validation set."),
    MicroMainUniverseEntry("ETHUSDT", "core", 2, 1.00, 0.6269, 0.6649, "USDT reliable-balanced live universe member from the 3y validation set."),
    MicroMainUniverseEntry("SOLUSDT", "core", 3, 0.90, 0.6864, 0.6603, "USDT reliable-balanced live universe member from the 3y validation set."),
    MicroMainUniverseEntry("BNBUSDT", "core", 4, 0.75, 0.6755, 0.6768, "USDT reliable-balanced live universe member from the 3y validation set."),
    MicroMainUniverseEntry("XRPUSDT", "core", 5, 0.60, 0.5818, 0.6509, "USDT reliable-balanced live universe member from the 3y validation set."),
    MicroMainUniverseEntry("ADAUSDT", "core", 6, 0.55, 0.5770, 0.6373, "USDT reliable-balanced live universe member from the 3y validation set."),
    MicroMainUniverseEntry("AVAXUSDT", "core", 7, 0.35, 0.5666, 0.6248, "USDT reliable-balanced live universe member from the 3y validation set."),
    MicroMainUniverseEntry("LINKUSDT", "core", 8, 0.85, 0.6680, 0.6662, "USDT reliable-balanced live universe member from the 3y validation set."),
    MicroMainUniverseEntry("DOGEUSDT", "core", 9, 0.45, 0.8013, 0.7070, "USDT reliable-balanced live universe member from the 3y validation set."),
    MicroMainUniverseEntry("BCHUSDT", "core", 10, 0.45, 0.7377, 0.6912, "USDT reliable-balanced live universe member from the 3y validation set."),
    MicroMainUniverseEntry("LTCUSDT", "core", 11, 0.45, 0.7637, 0.7053, "USDT reliable-balanced live universe member from the 3y validation set."),
    MicroMainUniverseEntry("NEARUSDT", "core", 12, 0.40, 0.7700, 0.6791, "USDT reliable-balanced live universe member from the 3y validation set."),
    MicroMainUniverseEntry("FILUSDT", "core", 13, 0.45, 0.8333, 0.7128, "USDT reliable-balanced live universe member from the 3y validation set."),
    MicroMainUniverseEntry("DOTUSDT", "core", 14, 0.40, 0.7733, 0.6951, "USDT reliable-balanced live universe member from the 3y validation set."),
    MicroMainUniverseEntry("ATOMUSDT", "core", 15, 0.40, 0.7849, 0.7037, "USDT reliable-balanced live universe member from the 3y validation set."),
    MicroMainUniverseEntry("ETCUSDT", "core", 16, 0.40, 0.8065, 0.7214, "USDT reliable-balanced live universe member from the 3y validation set."),
    MicroMainUniverseEntry("HBARUSDT", "core", 17, 0.45, 0.7442, 0.6853, "USDT reliable-balanced live universe member from the 3y validation set."),
    MicroMainUniverseEntry("AAVEUSDT", "core", 18, 0.35, 0.6239, 0.6393, "USDT reliable-balanced live universe member from the 3y validation set."),
    MicroMainUniverseEntry("UNIUSDT", "core", 19, 0.40, 0.7563, 0.6800, "USDT reliable-balanced live universe member from the 3y validation set."),
    MicroMainUniverseEntry("SUIUSDT", "core", 20, 0.45, 0.6846, 0.6484, "USDT reliable-balanced live universe member from the 3y validation set."),
    MicroMainUniverseEntry("INJUSDT", "core", 21, 0.40, 0.7920, 0.6877, "USDT reliable-balanced live universe member from the 3y validation set."),
    MicroMainUniverseEntry("FETUSDT", "core", 22, 0.40, 0.7582, 0.6790, "USDT reliable-balanced live universe member from the 3y validation set."),
    MicroMainUniverseEntry("ARBUSDT", "core", 23, 0.40, 0.8929, 0.7255, "USDT reliable-balanced live universe member from the 3y validation set."),
    MicroMainUniverseEntry("APTUSDT", "core", 24, 0.40, 0.8859, 0.7288, "USDT reliable-balanced live universe member from the 3y validation set."),
    MicroMainUniverseEntry("RUNEUSDT", "core", 25, 0.35, 0.7489, 0.6853, "USDT reliable-balanced live universe member from the 3y validation set."),
    MicroMainUniverseEntry("PENDLEUSDT", "core", 26, 0.35, 0.9353, 0.7284, "USDT reliable-balanced live universe member from the 3y validation set."),
    MicroMainUniverseEntry("ICPUSDT", "core", 27, 0.40, 0.9029, 0.7348, "USDT reliable-balanced live universe member from the 3y validation set."),
    MicroMainUniverseEntry("XLMUSDT", "core", 28, 0.35, 0.8199, 0.7302, "USDT reliable-balanced live universe member from the 3y validation set."),
    MicroMainUniverseEntry("ZECUSDT", "core", 29, 0.35, 0.7198, 0.6695, "USDT reliable-balanced live universe member from the 3y validation set."),
    MicroMainUniverseEntry("QNTUSDT", "core", 30, 0.30, 0.6241, 0.6561, "USDT reliable-balanced live universe member from the 3y validation set."),
    MicroMainUniverseEntry("DASHUSDT", "core", 31, 0.30, 0.7136, 0.6860, "USDT reliable-balanced live universe member from the 3y validation set."),
)

_ALL_ENTRIES = _ENTRIES + _USDT_RELIABLE_BALANCED_31
_ENTRY_MAP = {entry.symbol: entry for entry in _ALL_ENTRIES}


def micro_main_universe_entry(symbol: str) -> dict[str, Any] | None:
    entry = _ENTRY_MAP.get(str(symbol or "").upper())
    return asdict(entry) if entry else None


def _entries_for_symbols(symbols: Iterable[str] | None = None) -> tuple[MicroMainUniverseEntry, ...]:
    if symbols is None:
        return _ALL_ENTRIES
    allowed = {str(item or "").upper().strip() for item in symbols if str(item or "").strip()}
    if not allowed:
        return ()
    return tuple(entry for entry in _ALL_ENTRIES if entry.symbol in allowed)


def build_micro_main_universe_policy_snapshot(*, symbols: Iterable[str] | None = None) -> dict[str, Any]:
    entries = _entries_for_symbols(symbols)
    return {
        "family": "session_impulse_retest",
        "core_symbols": [entry.symbol for entry in entries if entry.tier == "core"],
        "secondary_symbols": [entry.symbol for entry in entries if entry.tier == "secondary"],
        "allowed_symbols": [entry.symbol for entry in entries],
        "partial_activation_priority": [
            entry.symbol
            for entry in sorted(entries, key=lambda item: item.rollout_priority)
        ],
        "risk_multipliers": {
            entry.symbol: round(float(entry.risk_multiplier), 4)
            for entry in entries
        },
        "entries": [asdict(entry) for entry in entries],
        "policy_note": (
            "Core symbols are eligible for the first live rollout after shadow validation. "
            "Secondary symbols remain shadow-first and should receive lower risk caps."
        ),
        "scope": "all_known_symbols" if symbols is None else "configured_symbols",
    }


def build_micro_main_rollout_contract_snapshot(
    *,
    enabled: bool,
    shadow_only: bool,
    partial_activation_ratio: float,
    core_live_slots: int,
    secondary_live_enabled: bool,
    symbols: Iterable[str] | None = None,
) -> dict[str, Any]:
    snapshot = build_micro_main_universe_policy_snapshot(symbols=symbols)
    snapshot["rollout_contract"] = {
        "enabled": _safe_bool(enabled),
        "shadow_only": _safe_bool(shadow_only),
        "partial_activation_ratio": round(float(partial_activation_ratio), 4),
        "core_live_slots": max(int(core_live_slots), 0),
        "secondary_live_enabled": _safe_bool(secondary_live_enabled),
    }
    return snapshot
