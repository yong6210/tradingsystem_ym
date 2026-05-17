#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta
from math import isfinite
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.db.repositories import CandleRepository
from app.db.session import SessionLocal, init_db
from app.services.historical_walk_forward_proof import HistoricalWalkForwardProofService


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rebuild runtime snapshots at replay timestamps and diff input/generation alignment.")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--family", default="sweep_reversal")
    parser.add_argument("--entry-model", default="LIMIT")
    parser.add_argument(
        "--replay-path",
        default="reports/validation/historical_walk_forward_cache/strategy_proof_contract_live_subset.json",
    )
    parser.add_argument("--positive-only", action="store_true", default=True)
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def _resolve_root_path(raw_path: str | Path) -> Path:
    path = Path(raw_path)
    return path if path.is_absolute() else ROOT_DIR / path


def _utc_from_iso(raw: str | None) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _sorted_counts(counter: Counter[str]) -> dict[str, int]:
    return dict(sorted(counter.items(), key=lambda item: (-item[1], item[0])))


def _dominant_reason(mapping: dict[str, int] | None, default: str) -> str:
    if not mapping:
        return default
    return max(mapping.items(), key=lambda item: (item[1], item[0]))[0]


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return float(default)
    return parsed if isfinite(parsed) else float(default)


def _safe_int(value: Any, default: int = 0) -> int:
    return int(_safe_float(value, float(default)))


def _load_replay_rows(*, replay_path: str, symbol: str, family: str, entry_model: str, days: int, positive_only: bool) -> list[dict[str, Any]]:
    payload = json.loads(_resolve_root_path(replay_path).read_text(encoding="utf-8"))
    rows = list(payload.get("trade_rows") or [])
    latest_source_ts = _utc_from_iso(str(payload.get("latest_source_ts") or "")) or datetime.now(UTC)
    cutoff = latest_source_ts - timedelta(days=max(int(days), 1))
    filtered: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("symbol") or "").upper() != symbol.upper():
            continue
        if str(row.get("strategy_family") or "").lower() != family.lower():
            continue
        if str(row.get("entry_model") or "").upper() != entry_model.upper():
            continue
        generated_ts = _utc_from_iso(str(row.get("generated_ts") or ""))
        if generated_ts is None or generated_ts < cutoff:
            continue
        if positive_only and _safe_float(row.get("final_exit_realized_r")) <= 0.0:
            continue
        item = dict(row)
        item["generated_dt"] = generated_ts
        filtered.append(item)
    return sorted(filtered, key=lambda row: row["generated_dt"])


def _contract_matches_snapshot_row(
    *,
    row: dict[str, Any],
    family: str,
    entry_model: str,
    direction: str,
) -> bool:
    validity = dict(row.get("validity") or {})
    return (
        str(validity.get("strategy_family") or "").lower() == family.lower()
        and str(row.get("entry_model") or "").upper() == entry_model.upper()
        and str(row.get("direction") or "").lower() == direction.lower()
    )


def _rebuild_runtime_snapshots(
    *,
    symbol: str,
    replay_rows: list[dict[str, Any]],
    family: str,
    entry_model: str,
) -> dict[str, dict[str, Any]]:
    if not replay_rows:
        return {}

    init_db()
    settings = get_settings()
    warmup_5m_bars = max(_safe_int(settings.auto_trading_historical_walk_forward_warmup_5m_bars, 300), 30)
    min_15m_bars = max(_safe_int(settings.auto_trading_historical_walk_forward_min_15m_bars, 60), 30)
    max_5m_window = max(_safe_int(settings.auto_trading_historical_walk_forward_max_5m_window_bars, 300), warmup_5m_bars)
    max_15m_window = max(_safe_int(settings.auto_trading_historical_walk_forward_max_15m_window_bars, 300), min_15m_bars)

    target_timestamps = {row["generated_dt"] for row in replay_rows}
    start_ts = min(target_timestamps) - timedelta(days=10)
    end_ts = max(target_timestamps) + timedelta(minutes=5)

    with SessionLocal() as db:
        candle_repo = CandleRepository(db)
        proof = HistoricalWalkForwardProofService(candle_repo=candle_repo, settings=settings)
        candles_5m = [c for c in proof._load_symbol_candles(symbol=symbol, timeframe="5m", start_ts=start_ts, end_ts=end_ts) if proof._normalize_ts(c.ts) is not None]
        candles_15m = [c for c in proof._load_symbol_candles(symbol=symbol, timeframe="15m", start_ts=start_ts, end_ts=end_ts) if proof._normalize_ts(c.ts) is not None]
        snapshots: dict[str, dict[str, Any]] = {}
        existing_zones: list[Any] = []
        idx_15 = -1

        for idx_5, candle in enumerate(candles_5m):
            current_ts = proof._normalize_ts(candle.ts)
            if current_ts is None:
                continue
            advanced_15m = False
            while idx_15 + 1 < len(candles_15m):
                next_ts = proof._normalize_ts(candles_15m[idx_15 + 1].ts)
                if next_ts is None or next_ts > current_ts:
                    break
                idx_15 += 1
                advanced_15m = True
            if idx_5 + 1 < warmup_5m_bars or idx_15 + 1 < min_15m_bars:
                continue
            if not advanced_15m:
                continue
            if current_ts not in target_timestamps:
                continue

            candles_5m_window = candles_5m[max(0, idx_5 + 1 - max_5m_window) : idx_5 + 1]
            candles_15m_window = candles_15m[max(0, idx_15 + 1 - max_15m_window) : idx_15 + 1]
            context = proof.context_engine.build_snapshot(symbol=symbol, candles_5m=candles_5m_window, candles_15m=candles_15m_window)
            zones = proof.zone_engine.refresh(symbol=symbol, candles_15m=candles_15m_window, existing=existing_zones)
            zones = proof._normalize_zone_timestamps(zones, current_ts=current_ts)
            existing_zones = zones
            active_zones = [zone for zone in zones if str(zone.state or "") != "expired"]
            ranked = proof.plan_generator.generate(
                symbol=symbol,
                zones=active_zones,
                context=context,
                candles_5m=candles_5m_window,
                active_thesis_clusters=0,
                now=current_ts,
            )
            diagnostics = proof.plan_generator.generation_diagnostics(
                symbol=symbol,
                zones=active_zones,
                context=context,
                candles_5m=candles_5m_window,
            )
            contract_ranked = [
                item.plan
                for item in ranked
                if str((item.plan.validity or {}).get("strategy_family") or "").lower() == family.lower()
                and str(item.plan.entry_model or "").upper() == entry_model.upper()
            ]
            generated_family_counts: Counter[str] = Counter(
                str((item.plan.validity or {}).get("strategy_family") or "unknown").lower()
                for item in ranked
            )
            generated_entry_model_counts: Counter[str] = Counter(
                str(item.plan.entry_model or "").upper()
                for item in ranked
            )
            generated_direction_counts: Counter[str] = Counter(
                str(item.plan.direction or "").lower()
                for item in ranked
            )
            key = current_ts.isoformat()
            snapshots[key] = {
                "generated_ts": key,
                "active_zone_count": len(active_zones),
                "generated_plan_count": len(ranked),
                "contract_generated_count": len(contract_ranked),
                "top_generated_families": _sorted_counts(generated_family_counts),
                "top_generated_entry_models": _sorted_counts(generated_entry_model_counts),
                "top_generated_directions": _sorted_counts(generated_direction_counts),
                "regime_profile": diagnostics.get("regime_profile"),
                "transition_state": diagnostics.get("transition_state"),
                "transition_lock_reason": diagnostics.get("transition_lock_reason"),
                "post_hard_gate_zone_count": int(diagnostics.get("post_hard_gate_zone_count") or 0),
                "pre_generation_candidate_count": int(diagnostics.get("pre_generation_candidate_count") or 0),
                "hard_gate_block_counts": dict(diagnostics.get("hard_gate_block_counts") or {}),
                "reaction_unavailable_reason_counts": dict(diagnostics.get("reaction_unavailable_reason_counts") or {}),
                "reaction_skip_counts": dict(diagnostics.get("reaction_skip_counts") or {}),
                "legacy_router_reason_counts": dict(diagnostics.get("legacy_router_reason_counts") or {}),
                "router_block_counts": dict(diagnostics.get("router_block_counts") or {}),
                "generic_setup_block_counts": dict(diagnostics.get("generic_setup_block_counts") or {}),
                "mode_block_counts": dict(diagnostics.get("mode_block_counts") or {}),
                "reaction_shadow_proof_reclaim_counts": dict(diagnostics.get("reaction_shadow_proof_reclaim_counts") or {}),
                "reaction_shadow_one_bar_counts": dict(diagnostics.get("reaction_shadow_one_bar_counts") or {}),
                "matching_contract_direction_counts": _sorted_counts(
                    Counter(str(plan.direction or "").lower() for plan in contract_ranked)
                ),
            }
    return snapshots


def _classify_snapshot_gap(
    replay_row: dict[str, Any],
    snapshot: dict[str, Any] | None,
) -> str:
    if snapshot is None:
        return "snapshot_missing"
    direction = str(replay_row.get("direction") or "").lower()
    direction_count = int((snapshot.get("matching_contract_direction_counts") or {}).get(direction, 0))
    if direction_count > 0:
        return "contract_present_same_direction"
    if int(snapshot.get("active_zone_count") or 0) == 0:
        return "zone_state:no_active_zone"
    if int(snapshot.get("post_hard_gate_zone_count") or 0) == 0:
        return f"hard_gate:{_dominant_reason(snapshot.get('hard_gate_block_counts'), 'unknown')}"
    if int(snapshot.get("pre_generation_candidate_count") or 0) == 0:
        if snapshot.get("reaction_unavailable_reason_counts"):
            return f"reaction_input_unavailable:{_dominant_reason(snapshot.get('reaction_unavailable_reason_counts'), 'unknown')}"
        if snapshot.get("reaction_skip_counts"):
            return f"reaction_skip:{_dominant_reason(snapshot.get('reaction_skip_counts'), 'unknown')}"
        if snapshot.get("legacy_router_reason_counts"):
            return f"router_legacy:{_dominant_reason(snapshot.get('legacy_router_reason_counts'), 'unknown')}"
        if snapshot.get("router_block_counts"):
            return f"router_block:{_dominant_reason(snapshot.get('router_block_counts'), 'unknown')}"
        if snapshot.get("generic_setup_block_counts"):
            return f"generic_setup_block:{_dominant_reason(snapshot.get('generic_setup_block_counts'), 'unknown')}"
        if snapshot.get("mode_block_counts"):
            return f"mode_block:{_dominant_reason(snapshot.get('mode_block_counts'), 'unknown')}"
        return "pre_generation_zero:unknown"
    if int(snapshot.get("contract_generated_count") or 0) == 0:
        entry_counts = snapshot.get("top_generated_entry_models") or {}
        family_counts = snapshot.get("top_generated_families") or {}
        if entry_counts:
            return f"contract_mismatch:other_entry_model:{_dominant_reason(entry_counts, 'unknown')}"
        if family_counts:
            return f"contract_mismatch:other_family:{_dominant_reason(family_counts, 'unknown')}"
        return "contract_mismatch:no_matching_contract_generated"
    return "contract_present_other_direction"


def main() -> int:
    args = _parse_args()
    replay_rows = _load_replay_rows(
        replay_path=args.replay_path,
        symbol=args.symbol,
        family=args.family,
        entry_model=args.entry_model,
        days=args.days,
        positive_only=bool(args.positive_only),
    )
    snapshots = _rebuild_runtime_snapshots(
        symbol=args.symbol.upper(),
        replay_rows=replay_rows,
        family=args.family,
        entry_model=args.entry_model,
    )

    reason_counts: Counter[str] = Counter()
    sample_rows: list[dict[str, Any]] = []
    for row in replay_rows:
        key = row["generated_dt"].isoformat()
        snapshot = snapshots.get(key)
        reason = _classify_snapshot_gap(row, snapshot)
        reason_counts[reason] += 1
        if len(sample_rows) < 20:
            sample_rows.append(
                {
                    "generated_ts": key,
                    "direction": row.get("direction"),
                    "final_exit_realized_r": _safe_float(row.get("final_exit_realized_r")),
                    "raw_signal_features": dict(row.get("raw_signal_features") or {}),
                    "reason": reason,
                    "snapshot": snapshot,
                }
            )

    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "symbol": args.symbol.upper(),
        "days": int(args.days),
        "family": args.family.lower(),
        "entry_model": args.entry_model.upper(),
        "replay_positive_count": len(replay_rows),
        "runtime_snapshot_count": len(snapshots),
        "top_input_diff_reasons": sorted(reason_counts.items(), key=lambda item: (-item[1], item[0]))[:10],
        "input_diff_reason_counts": dict(sorted(reason_counts.items(), key=lambda item: (-item[1], item[0]))),
        "sample_rows": sample_rows,
        "notes": [
            "This script replays the current runtime engine on the exact replay timestamps and compares same-candle generation state.",
            "It does not depend on stored runtime plans; it rebuilds context, zones, ranked plans, and generation diagnostics from raw candles.",
            "Reasons are direction-aware for the target contract: BTCUSDC + sweep_reversal + chosen entry model.",
        ],
    }

    if args.write_report:
        out_dir = ROOT_DIR / "reports" / "validation" / "promotion_mismatch"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / (
            f"replay_runtime_input_diff_{args.symbol.upper()}_{args.family.lower()}_{args.entry_model.upper()}_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
        )
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        payload["report_path"] = str(out_path)

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
