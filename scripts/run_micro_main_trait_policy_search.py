#!/usr/bin/env python3
from __future__ import annotations

import argparse
import itertools
import json
import sqlite3
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import median
from types import MethodType
from typing import Any

import httpx

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.services.active_contract_replay_baseline import (
    active_micro_live_symbol_contract,
    usdt_proxy_contract_symbols,
)
from app.services.micro_main_strategy_research import (
    SessionImpulseRetestResearch,
    session_impulse_retest_profile_for_symbol,
)
from app.services.report_io import atomic_write_text
from scripts.run_micro_main_raw_profile_model_search import (
    Variant,
    _apply_variant_profile,
    _evaluate_models,
    _render_markdown,
)
from scripts.run_micro_main_usdt_proxy_backtest import (
    _fetch_1m_klines,
    _resample_to_5m,
    _trade_to_row,
    canonical_symbol_for_proxy,
)


@dataclass(frozen=True, slots=True)
class TraitPolicy:
    name: str
    group_variants: dict[str, Variant]
    group_by_symbol: dict[str, str]
    notes: str = ""

    def variant_for_symbol(self, symbol: str) -> Variant:
        group = self.group_by_symbol.get(str(symbol).upper(), "balanced")
        return self.group_variants.get(group) or self.group_variants["balanced"]

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "notes": self.notes,
            "group_by_symbol": dict(sorted(self.group_by_symbol.items())),
            "group_variants": {
                group: variant.as_dict()
                for group, variant in sorted(self.group_variants.items())
            },
        }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Search trait/ontology style SessionImpulseRetest policies.")
    parser.add_argument(
        "--symbols",
        default="BTCUSDT,ETHUSDT,SOLUSDT,LINKUSDT,BNBUSDT,XRPUSDT,ADAUSDT,AVAXUSDT,BCHUSDT,LTCUSDT,NEARUSDT",
    )
    parser.add_argument("--days", type=int, default=1095)
    parser.add_argument("--max-policies", type=int, default=96)
    parser.add_argument("--baseline-backtest-path", default="")
    parser.add_argument("--search-name", default="trait_policy")
    parser.add_argument("--checkpoint-path", default="")
    parser.add_argument("--rows-db-path", default="")
    parser.add_argument("--resume-checkpoint", action="store_true")
    parser.add_argument("--max-new-symbols", type=int, default=0)
    parser.add_argument("--checkpoint-policy-interval", type=int, default=20)
    parser.add_argument("--brief-log", action="store_true")
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _trade_count(payload: dict[str, Any]) -> int:
    return sum(len(dict(item or {}).get("trades") or []) for item in dict(payload.get("results") or {}).values())


def _latest_trade_backtest_path() -> Path:
    settings = get_settings()
    base = Path(settings.validation_report_dir) / "micro_main_usdt_proxy_backtests"
    candidates = sorted(
        (
            path
            for path in base.glob("micro_main_usdt_proxy_backtest_*.json")
            if "unseen" not in path.name and "top" not in path.name
        ),
        key=lambda item: item.name,
        reverse=True,
    )
    active_symbols = active_micro_live_symbol_contract(settings)
    latest_trade_candidate: Path | None = None
    for candidate in candidates:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
        if _trade_count(payload) <= 0:
            continue
        if latest_trade_candidate is None:
            latest_trade_candidate = candidate
        if active_symbols and usdt_proxy_contract_symbols(payload) != active_symbols:
            continue
        if active_symbols:
            return candidate
    if latest_trade_candidate is not None:
        return latest_trade_candidate
    raise FileNotFoundError(f"No trade-including micro-main backtest JSON found under {base}")


def _load_trade_rows(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for item in dict(payload.get("results") or {}).values():
        rows.extend(list(dict(item or {}).get("trades") or []))
    if not rows:
        raise ValueError(f"Backtest has no trade rows: {path}")
    return rows


def _percentile(values: list[float], pct: float) -> float:
    clean = sorted(value for value in values if value == value)
    if not clean:
        return 0.0
    idx = int((len(clean) - 1) * min(max(float(pct), 0.0), 1.0))
    return float(clean[idx])


def _diagnostic_values(rows: list[dict[str, Any]], key: str) -> list[float]:
    out: list[float] = []
    for row in rows:
        diagnostics = dict(row.get("diagnostics") or {})
        if key in diagnostics:
            out.append(_safe_float(diagnostics.get(key)))
    return out


def _compact_eval_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol": row.get("symbol"),
        "entry_ts": row.get("entry_ts"),
        "exit_ts": row.get("exit_ts"),
        "r_value": row.get("r_value"),
    }


def _symbol_trait_summary(rows: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_symbol.setdefault(str(row.get("symbol") or ""), []).append(row)

    summaries: dict[str, dict[str, Any]] = {}
    groups: dict[str, str] = {}
    for symbol, bucket in sorted(by_symbol.items()):
        r_values = [_safe_float(row.get("r_value")) for row in bucket]
        trades = len(bucket)
        total = sum(r_values)
        ev = total / max(trades, 1)
        win_rate = sum(1 for value in r_values if value > 0.0) / max(trades, 1)
        volume_med = median(_diagnostic_values(bucket, "volume_factor") or [0.0])
        body_med = median(_diagnostic_values(bucket, "reclaim_body_atr") or [0.0])
        trend_med = median(_diagnostic_values(bucket, "trend_strength_atr") or [0.0])
        overshoot_med = median(_diagnostic_values(bucket, "reclaim_overshoot_atr") or [0.0])
        risk_med = median(_diagnostic_values(bucket, "risk_atr") or [0.0])
        stop_rate = sum(1 for row in bucket if str(row.get("exit_reason") or "") == "stop") / max(trades, 1)
        traits: list[str] = []
        if trades >= 550:
            traits.append("high_activity")
        elif trades < 250:
            traits.append("thin_sample")
        else:
            traits.append("medium_activity")
        if ev >= 0.70:
            traits.append("high_edge")
        elif ev < 0.60:
            traits.append("low_edge")
        else:
            traits.append("mid_edge")
        if volume_med >= 1.55:
            traits.append("high_volume_confirmed")
        elif volume_med <= 1.35:
            traits.append("low_volume_confirmed")
        if trend_med >= 0.74:
            traits.append("strong_trend")
        elif trend_med <= 0.67:
            traits.append("soft_trend")
        if overshoot_med >= 0.155:
            traits.append("deep_retest")
        elif overshoot_med <= 0.135:
            traits.append("shallow_retest")
        if stop_rate >= 0.34:
            traits.append("stop_heavy")

        if symbol == "XRPUSDC":
            group = "xrp_exception"
        elif "high_activity" in traits and "low_edge" in traits:
            group = "noisy_high_activity"
        elif "high_activity" in traits:
            group = "productive_high_activity"
        elif "high_edge" in traits:
            group = "clean_quality"
        elif "high_volume_confirmed" in traits:
            group = "high_volume_core"
        else:
            group = "balanced"
        groups[symbol] = group
        summaries[symbol] = {
            "group": group,
            "traits": traits,
            "trades": trades,
            "total_r": round(total, 4),
            "ev_r": round(ev, 4),
            "win_rate": round(win_rate, 4),
            "stop_rate": round(stop_rate, 4),
            "volume_factor_median": round(float(volume_med), 4),
            "reclaim_body_atr_median": round(float(body_med), 4),
            "trend_strength_atr_median": round(float(trend_med), 4),
            "reclaim_overshoot_atr_median": round(float(overshoot_med), 4),
            "risk_atr_median": round(float(risk_med), 4),
            "r_value_p25": round(_percentile(r_values, 0.25), 4),
            "r_value_p75": round(_percentile(r_values, 0.75), 4),
        }
    return summaries, groups


def _v(name: str, *, body: float, volume: float, trend: float, overshoot: float, exclude_xrp: bool = True) -> Variant:
    return Variant(
        name=name,
        body_delta=body,
        volume_mult=volume,
        trend_delta=trend,
        overshoot_delta=overshoot,
        exclude_symbols=("XRPUSDC",) if exclude_xrp else (),
    )


def _build_trait_policies(group_by_symbol: dict[str, str], *, max_policies: int) -> list[TraitPolicy]:
    choices: dict[str, list[Variant]] = {
        "noisy_high_activity": [
            _v("noisy_strict_body", body=0.095, volume=0.84, trend=-0.11, overshoot=0.040),
            _v("noisy_recommended", body=0.090, volume=0.83, trend=-0.12, overshoot=0.045),
            _v("noisy_deep_retest_guard", body=0.095, volume=0.84, trend=-0.12, overshoot=0.050),
            _v("noisy_trade_expand", body=0.0875, volume=0.82, trend=-0.12, overshoot=0.045),
        ],
        "productive_high_activity": [
            _v("productive_recommended", body=0.090, volume=0.83, trend=-0.12, overshoot=0.045),
            _v("productive_trade_expand", body=0.0875, volume=0.82, trend=-0.12, overshoot=0.050),
            _v("productive_quality_guard", body=0.0925, volume=0.84, trend=-0.11, overshoot=0.040),
            _v("productive_deep_retest", body=0.090, volume=0.83, trend=-0.12, overshoot=0.050),
        ],
        "clean_quality": [
            _v("clean_quality_preserve", body=0.090, volume=0.86, trend=-0.10, overshoot=0.040),
            _v("clean_recommended", body=0.090, volume=0.83, trend=-0.12, overshoot=0.045),
            _v("clean_trade_expand", body=0.0875, volume=0.82, trend=-0.12, overshoot=0.045),
            _v("clean_high_volume_relaxed", body=0.0875, volume=0.85, trend=-0.11, overshoot=0.040),
        ],
        "high_volume_core": [
            _v("core_quality_preserve", body=0.090, volume=0.86, trend=-0.10, overshoot=0.040),
            _v("core_recommended", body=0.090, volume=0.83, trend=-0.12, overshoot=0.045),
            _v("core_high_volume_relaxed", body=0.0875, volume=0.85, trend=-0.11, overshoot=0.040),
            _v("core_strict_body", body=0.095, volume=0.86, trend=-0.10, overshoot=0.035),
        ],
        "balanced": [
            _v("balanced_recommended", body=0.090, volume=0.83, trend=-0.12, overshoot=0.045),
            _v("balanced_quality", body=0.090, volume=0.85, trend=-0.10, overshoot=0.040),
        ],
        "xrp_exception": [Variant(name="xrp_current", notes="keep current XRP profile")],
    }

    policies: list[TraitPolicy] = [
        TraitPolicy(
            name="current_live_reference",
            group_variants={group: Variant(name=f"{group}_current") for group in choices},
            group_by_symbol=group_by_symbol,
            notes="original current profiles",
        ),
        TraitPolicy(
            name="ontology_common_recommended",
            group_variants={
                group: (_v("common_recommended", body=0.090, volume=0.83, trend=-0.12, overshoot=0.045) if group != "xrp_exception" else Variant(name="xrp_current"))
                for group in choices
            },
            group_by_symbol=group_by_symbol,
            notes="same recommended policy for every non-XRP group",
        ),
    ]
    seen = {policy.name for policy in policies}
    primary_groups = ["noisy_high_activity", "productive_high_activity", "clean_quality", "high_volume_core"]
    for combo in itertools.product(*(choices[group] for group in primary_groups)):
        group_variants = {
            "balanced": choices["balanced"][0],
            "xrp_exception": choices["xrp_exception"][0],
        }
        parts: list[str] = []
        for group, variant in zip(primary_groups, combo, strict=True):
            group_variants[group] = variant
            parts.append(variant.name)
        name = "ontology_" + "__".join(part.replace("_", "-") for part in parts)
        if name in seen:
            continue
        seen.add(name)
        policies.append(
            TraitPolicy(
                name=name,
                group_variants=group_variants,
                group_by_symbol=group_by_symbol,
                notes="trait group policy search candidate",
            )
        )
        if len(policies) >= max(int(max_policies), 2):
            break
    return policies


def _policy_rows_for_symbol(
    *,
    engine: SessionImpulseRetestResearch,
    proxy_symbol: str,
    canonical_symbol: str,
    profile_name: str,
    policy: TraitPolicy,
) -> list[dict[str, Any]]:
    base_profile = engine._signal_filter_profile()
    variant = policy.variant_for_symbol(canonical_symbol)
    profile = _apply_variant_profile(base_profile, symbol=canonical_symbol, variant=variant)

    def patched_profile(self: SessionImpulseRetestResearch) -> dict[str, float]:
        return dict(profile)

    original = engine._signal_filter_profile
    engine._signal_filter_profile = MethodType(patched_profile, engine)
    try:
        trades = engine.backtest()
    finally:
        engine._signal_filter_profile = original
    return [
        _compact_eval_row(_trade_to_row(
            trade=trade,
            proxy_symbol=proxy_symbol,
            canonical_symbol=canonical_symbol,
            profile_name=profile_name,
        ))
        for trade in trades
    ]


def _row_passes_profile(row: dict[str, Any], profile: dict[str, float]) -> bool:
    diagnostics = dict(row.get("diagnostics") or {})
    return (
        _safe_float(diagnostics.get("trend_strength_atr")) >= float(profile["min_trend_strength"])
        and _safe_float(diagnostics.get("volume_factor")) >= float(profile["min_volume_factor"])
        and _safe_float(diagnostics.get("reclaim_body_atr")) >= float(profile["min_reclaim_body_atr"])
        and _safe_float(diagnostics.get("reclaim_overshoot_atr")) <= float(profile["reclaim_overshoot_atr"])
    )


def _policy_rows_for_symbol_fast(
    *,
    engine: SessionImpulseRetestResearch,
    proxy_symbol: str,
    canonical_symbol: str,
    profile_name: str,
    policies: list[TraitPolicy],
) -> dict[str, list[dict[str, Any]]]:
    base_profile = engine._signal_filter_profile()
    profiles_by_policy = {
        policy.name: _apply_variant_profile(
            base_profile,
            symbol=canonical_symbol,
            variant=policy.variant_for_symbol(canonical_symbol),
        )
        for policy in policies
    }
    superset_profile = dict(base_profile)
    superset_profile["min_trend_strength"] = min(profile["min_trend_strength"] for profile in profiles_by_policy.values())
    superset_profile["min_volume_factor"] = min(profile["min_volume_factor"] for profile in profiles_by_policy.values())
    superset_profile["min_reclaim_body_atr"] = min(profile["min_reclaim_body_atr"] for profile in profiles_by_policy.values())
    superset_profile["reclaim_overshoot_atr"] = max(profile["reclaim_overshoot_atr"] for profile in profiles_by_policy.values())

    def patched_profile(self: SessionImpulseRetestResearch) -> dict[str, float]:
        return dict(superset_profile)

    original = engine._signal_filter_profile
    engine._signal_filter_profile = MethodType(patched_profile, engine)
    try:
        superset_trades = engine.backtest()
    finally:
        engine._signal_filter_profile = original

    full_rows = [
        _trade_to_row(
            trade=trade,
            proxy_symbol=proxy_symbol,
            canonical_symbol=canonical_symbol,
            profile_name=profile_name,
        )
        for trade in superset_trades
    ]
    return {
        policy.name: [
            _compact_eval_row(row)
            for row in full_rows
            if _row_passes_profile(row, profiles_by_policy[policy.name])
        ]
        for policy in policies
    }


def _checkpoint_payload(
    *,
    search_name: str,
    start_ts: datetime,
    end_ts: datetime,
    proxy_symbols: list[str],
    policies: list[TraitPolicy],
    baseline_path: Path,
    trait_summary: dict[str, dict[str, Any]],
    group_by_symbol: dict[str, str],
    rows_by_policy: dict[str, list[dict[str, Any]]],
    processed_symbols: set[str],
    policy_progress_by_symbol: dict[str, int],
) -> dict[str, Any]:
    return {
        "schema_version": "micro_main_trait_policy_checkpoint_v1",
        "search_name": search_name,
        "start_ts": start_ts.isoformat(),
        "end_ts": end_ts.isoformat(),
        "proxy_symbols": proxy_symbols,
        "policy_names": [policy.name for policy in policies],
        "baseline_trait_source": str(baseline_path),
        "trait_summary": trait_summary,
        "group_by_symbol": group_by_symbol,
        "processed_symbols": sorted(processed_symbols),
        "policy_progress_by_symbol": dict(sorted(policy_progress_by_symbol.items())),
        "rows_by_policy": rows_by_policy,
    }


def _write_checkpoint(
    path: Path,
    *,
    search_name: str,
    start_ts: datetime,
    end_ts: datetime,
    proxy_symbols: list[str],
    policies: list[TraitPolicy],
    baseline_path: Path,
    trait_summary: dict[str, dict[str, Any]],
    group_by_symbol: dict[str, str],
    rows_by_policy: dict[str, list[dict[str, Any]]] | None,
    processed_symbols: set[str],
    policy_progress_by_symbol: dict[str, int],
    rows_db_path: Path | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _checkpoint_payload(
        search_name=search_name,
        start_ts=start_ts,
        end_ts=end_ts,
        proxy_symbols=proxy_symbols,
        policies=policies,
        baseline_path=baseline_path,
        trait_summary=trait_summary,
        group_by_symbol=group_by_symbol,
        rows_by_policy=rows_by_policy or {},
        processed_symbols=processed_symbols,
        policy_progress_by_symbol=policy_progress_by_symbol,
    )
    if rows_db_path is not None:
        payload["rows_storage"] = {"type": "sqlite", "path": str(rows_db_path)}
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False))


def _connect_rows_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS rows (
            policy TEXT NOT NULL,
            proxy_symbol TEXT NOT NULL,
            symbol TEXT NOT NULL,
            entry_ts TEXT NOT NULL,
            exit_ts TEXT NOT NULL,
            r_value REAL NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rows_policy ON rows(policy)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rows_proxy ON rows(proxy_symbol)")
    conn.commit()
    return conn


def _db_row_count(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM rows").fetchone()[0])


def _migrate_checkpoint_rows_to_db(
    conn: sqlite3.Connection,
    rows_by_policy: dict[str, list[dict[str, Any]]],
) -> None:
    if not rows_by_policy or _db_row_count(conn) > 0:
        return
    with conn:
        for policy, rows in rows_by_policy.items():
            conn.executemany(
                """
                INSERT INTO rows(policy, proxy_symbol, symbol, entry_ts, exit_ts, r_value)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        str(policy),
                        str(row.get("proxy_symbol") or ""),
                        str(row.get("symbol") or ""),
                        str(row.get("entry_ts") or ""),
                        str(row.get("exit_ts") or ""),
                        _safe_float(row.get("r_value")),
                    )
                    for row in rows
                ],
            )


def _store_policy_rows(
    conn: sqlite3.Connection,
    *,
    policy: str,
    proxy_symbol: str,
    rows: list[dict[str, Any]],
) -> None:
    with conn:
        conn.execute("DELETE FROM rows WHERE policy = ? AND proxy_symbol = ?", (policy, proxy_symbol))
        conn.executemany(
            """
            INSERT INTO rows(policy, proxy_symbol, symbol, entry_ts, exit_ts, r_value)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    policy,
                    proxy_symbol,
                    str(row.get("symbol") or ""),
                    str(row.get("entry_ts") or ""),
                    str(row.get("exit_ts") or ""),
                    _safe_float(row.get("r_value")),
                )
                for row in rows
            ],
        )


def _load_rows_by_policy_from_db(conn: sqlite3.Connection, policies: list[TraitPolicy]) -> dict[str, list[dict[str, Any]]]:
    rows_by_policy: dict[str, list[dict[str, Any]]] = {policy.name: [] for policy in policies}
    for policy, symbol, entry_ts, exit_ts, r_value in conn.execute(
        "SELECT policy, symbol, entry_ts, exit_ts, r_value FROM rows ORDER BY policy, exit_ts, entry_ts, symbol"
    ):
        rows_by_policy.setdefault(str(policy), []).append(
            {
                "symbol": symbol,
                "entry_ts": entry_ts,
                "exit_ts": exit_ts,
                "r_value": r_value,
            }
        )
    return rows_by_policy


def main() -> int:
    args = _parse_args()
    settings = get_settings()
    generated_at = datetime.now(UTC)
    end_ts = generated_at.replace(second=0, microsecond=0)
    start_ts = end_ts - timedelta(days=max(int(args.days), 1))
    proxy_symbols = [item.strip().upper() for item in str(args.symbols or "").split(",") if item.strip()]
    baseline_path = Path(args.baseline_backtest_path).expanduser() if str(args.baseline_backtest_path or "").strip() else _latest_trade_backtest_path()
    if not baseline_path.is_absolute():
        baseline_path = ROOT_DIR / baseline_path
    report_dir = Path(settings.validation_report_dir) / "micro_main_raw_profile_model_searches"
    checkpoint_path = Path(args.checkpoint_path).expanduser() if str(args.checkpoint_path or "").strip() else report_dir / f"{args.search_name}_checkpoint.json"
    if not checkpoint_path.is_absolute():
        checkpoint_path = ROOT_DIR / checkpoint_path
    pause_paths = [
        checkpoint_path.with_suffix(".pause"),
        report_dir / f"{args.search_name}.pause",
    ]
    active_pause_path = next((path for path in pause_paths if path.exists()), None)
    if active_pause_path is not None:
        print(
            json.dumps(
                {
                    "status": "paused",
                    "search_name": str(args.search_name),
                    "pause_path": str(active_pause_path),
                    "checkpoint_path": str(checkpoint_path),
                },
                ensure_ascii=False,
            )
        )
        return 0
    rows_db_path = Path(args.rows_db_path).expanduser() if str(args.rows_db_path or "").strip() else checkpoint_path.with_suffix(".sqlite3")
    if not rows_db_path.is_absolute():
        rows_db_path = ROOT_DIR / rows_db_path
    rows_db = _connect_rows_db(rows_db_path)
    checkpoint: dict[str, Any] | None = None
    if args.resume_checkpoint and checkpoint_path.exists():
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        trait_summary = dict(checkpoint.get("trait_summary") or {})
        group_by_symbol = {str(key): str(value) for key, value in dict(checkpoint.get("group_by_symbol") or {}).items()}
    else:
        trait_summary, group_by_symbol = _symbol_trait_summary(_load_trade_rows(baseline_path))
    policies = _build_trait_policies(group_by_symbol, max_policies=int(args.max_policies))
    rows_by_policy: dict[str, list[dict[str, Any]]] = {policy.name: [] for policy in policies}
    processed_symbols: set[str] = set()
    policy_progress_by_symbol: dict[str, int] = {}

    if checkpoint is not None:
        expected_policy_names = [policy.name for policy in policies]
        if list(checkpoint.get("policy_names") or []) != expected_policy_names:
            raise ValueError(f"Checkpoint policy set does not match current policy set: {checkpoint_path}")
        if list(checkpoint.get("proxy_symbols") or []) != proxy_symbols:
            raise ValueError(f"Checkpoint symbol set does not match current symbol set: {checkpoint_path}")
        start_ts = datetime.fromisoformat(str(checkpoint["start_ts"]))
        end_ts = datetime.fromisoformat(str(checkpoint["end_ts"]))
        _migrate_checkpoint_rows_to_db(rows_db, dict(checkpoint.get("rows_by_policy") or {}))
        rows_by_policy = {policy.name: [] for policy in policies}
        processed_symbols = {str(item).upper() for item in list(checkpoint.get("processed_symbols") or [])}
        policy_progress_by_symbol = {
            str(symbol).upper(): int(count)
            for symbol, count in dict(checkpoint.get("policy_progress_by_symbol") or {}).items()
        }

    start_log = {
        "state": "start",
        "policies": len(policies),
        "symbol_count": len(proxy_symbols),
        "processed_count": len(processed_symbols),
        "start_ts": start_ts.isoformat(),
        "end_ts": end_ts.isoformat(),
        "baseline_trait_source": str(baseline_path),
        "checkpoint_path": str(checkpoint_path),
        "rows_db_path": str(rows_db_path),
    }
    if not args.brief_log:
        start_log["symbols"] = proxy_symbols
        start_log["processed_symbols"] = sorted(processed_symbols)
        start_log["groups"] = group_by_symbol
    print(json.dumps(start_log, ensure_ascii=False), file=sys.stderr, flush=True)

    with (
        httpx.Client(timeout=120.0, follow_redirects=True) as monthly_client,
        httpx.Client(base_url=settings.binance_rest_base_url, timeout=30.0) as rest_client,
    ):
        new_symbols_processed = 0
        for proxy_symbol in proxy_symbols:
            if proxy_symbol in processed_symbols:
                if not args.brief_log:
                    print(
                        json.dumps({"state": "resume_skip", "symbol": proxy_symbol}, ensure_ascii=False),
                        file=sys.stderr,
                        flush=True,
                    )
                continue
            canonical_symbol = canonical_symbol_for_proxy(proxy_symbol)
            if canonical_symbol is None:
                print(json.dumps({"state": "skip", "symbol": proxy_symbol, "reason": "missing_mapping"}), file=sys.stderr)
                processed_symbols.add(proxy_symbol)
                _write_checkpoint(
                    checkpoint_path,
                    search_name=str(args.search_name),
                    start_ts=start_ts,
                    end_ts=end_ts,
                    proxy_symbols=proxy_symbols,
                    policies=policies,
                    baseline_path=baseline_path,
                    trait_summary=trait_summary,
                    group_by_symbol=group_by_symbol,
                    rows_by_policy=None,
                    processed_symbols=processed_symbols,
                    policy_progress_by_symbol=policy_progress_by_symbol,
                    rows_db_path=rows_db_path,
                )
                new_symbols_processed += 1
                if args.max_new_symbols > 0 and new_symbols_processed >= args.max_new_symbols:
                    break
                continue
            candles_1m = _fetch_1m_klines(
                monthly_client,
                rest_client,
                symbol=proxy_symbol,
                start_ts=start_ts,
                end_ts=end_ts,
            )
            candles_5m = _resample_to_5m(candles_1m)
            if len(candles_1m) < 600 or len(candles_5m) < 200:
                print(
                    json.dumps(
                        {
                            "state": "skip",
                            "symbol": proxy_symbol,
                            "reason": "insufficient_candles",
                            "candles_1m": len(candles_1m),
                            "candles_5m": len(candles_5m),
                        },
                        ensure_ascii=False,
                    ),
                    file=sys.stderr,
                    flush=True,
                )
                processed_symbols.add(proxy_symbol)
                _write_checkpoint(
                    checkpoint_path,
                    search_name=str(args.search_name),
                    start_ts=start_ts,
                    end_ts=end_ts,
                    proxy_symbols=proxy_symbols,
                    policies=policies,
                    baseline_path=baseline_path,
                    trait_summary=trait_summary,
                    group_by_symbol=group_by_symbol,
                    rows_by_policy=None,
                    processed_symbols=processed_symbols,
                    policy_progress_by_symbol=policy_progress_by_symbol,
                    rows_db_path=rows_db_path,
                )
                new_symbols_processed += 1
                if args.max_new_symbols > 0 and new_symbols_processed >= args.max_new_symbols:
                    break
                continue
            profile_name = session_impulse_retest_profile_for_symbol(canonical_symbol)
            engine = SessionImpulseRetestResearch(
                symbol=canonical_symbol,
                candles_1m=candles_1m,
                candles_5m=candles_5m,
                profile_name=profile_name,
            )
            symbol_rows_by_policy = _policy_rows_for_symbol_fast(
                engine=engine,
                proxy_symbol=proxy_symbol,
                canonical_symbol=canonical_symbol,
                profile_name=profile_name,
                policies=policies,
            )
            for index, policy in enumerate(policies, start=1):
                _store_policy_rows(
                    rows_db,
                    policy=policy.name,
                    proxy_symbol=proxy_symbol,
                    rows=symbol_rows_by_policy.get(policy.name) or [],
                )
                if index == 1 or index == len(policies) or index % 20 == 0:
                    print(
                        json.dumps(
                            {
                                "state": "progress",
                                "symbol": proxy_symbol,
                                "group": group_by_symbol.get(canonical_symbol),
                                "policy_index": index,
                                "policy_count": len(policies),
                                "policy": policy.name,
                            },
                            ensure_ascii=False,
                        ),
                        file=sys.stderr,
                        flush=True,
                    )
                policy_progress_by_symbol[proxy_symbol] = index
                interval = max(int(args.checkpoint_policy_interval), 0)
                if index == len(policies) or (interval > 0 and index % interval == 0):
                    _write_checkpoint(
                        checkpoint_path,
                        search_name=str(args.search_name),
                        start_ts=start_ts,
                        end_ts=end_ts,
                        proxy_symbols=proxy_symbols,
                        policies=policies,
                        baseline_path=baseline_path,
                        trait_summary=trait_summary,
                        group_by_symbol=group_by_symbol,
                        rows_by_policy=None,
                        processed_symbols=processed_symbols,
                        policy_progress_by_symbol=policy_progress_by_symbol,
                        rows_db_path=rows_db_path,
                    )
            processed_symbols.add(proxy_symbol)
            policy_progress_by_symbol.pop(proxy_symbol, None)
            _write_checkpoint(
                checkpoint_path,
                search_name=str(args.search_name),
                start_ts=start_ts,
                end_ts=end_ts,
                proxy_symbols=proxy_symbols,
                policies=policies,
                baseline_path=baseline_path,
                trait_summary=trait_summary,
                group_by_symbol=group_by_symbol,
                rows_by_policy=None,
                processed_symbols=processed_symbols,
                policy_progress_by_symbol=policy_progress_by_symbol,
                rows_db_path=rows_db_path,
            )
            new_symbols_processed += 1
            if args.max_new_symbols > 0 and new_symbols_processed >= args.max_new_symbols:
                break

    missing_symbols = [symbol for symbol in proxy_symbols if symbol not in processed_symbols]
    if missing_symbols:
        print(
            json.dumps(
                {
                    "state": "partial_complete",
                    "processed_count": len(processed_symbols),
                    "total_symbols": len(proxy_symbols),
                    "remaining_symbols": missing_symbols,
                    "checkpoint_path": str(checkpoint_path),
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
            flush=True,
        )
        return 0

    rows_by_policy = _load_rows_by_policy_from_db(rows_db, policies)
    result = _evaluate_models(rows_by_policy, variants=policies, end_ts=end_ts)
    payload: dict[str, Any] = {
        "schema_version": f"micro_main_{args.search_name}_search_v1",
        "generated_at": generated_at.isoformat(),
        "search_name": str(args.search_name),
        "window": {"start_ts": start_ts.isoformat(), "end_ts": end_ts.isoformat(), "days": int(args.days)},
        "model_definition": "Trait ontology policy search. Symbols are grouped by entry-time diagnostics and historical signal traits; policies apply group-level filter bundles, not per-symbol one-off settings.",
        "baseline_trait_source": str(baseline_path),
        "checkpoint_path": str(checkpoint_path),
        "rows_db_path": str(rows_db_path),
        "trait_summary": trait_summary,
        "group_by_symbol": group_by_symbol,
        "variant_count": len(policies),
        **result,
    }

    if args.write_report:
        report_dir.mkdir(parents=True, exist_ok=True)
        stem = f"micro_main_{args.search_name}_{generated_at.strftime('%Y%m%dT%H%M%SZ')}"
        json_path = report_dir / f"{stem}.json"
        md_path = report_dir / f"{stem}.md"
        latest_json = report_dir / f"latest_{args.search_name}.json"
        latest_md = report_dir / f"latest_{args.search_name}.md"
        payload["report_path"] = str(json_path)
        payload["latest_report_path"] = str(latest_json)
        atomic_write_text(json_path, json.dumps(payload, ensure_ascii=False, indent=2))
        atomic_write_text(md_path, _render_markdown(payload))
        atomic_write_text(latest_json, json.dumps(payload, ensure_ascii=False, indent=2))
        atomic_write_text(latest_md, _render_markdown(payload))
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
