#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.db.repositories import CandleRepository
from app.db.session import SessionLocal, init_db
from app.services.historical_walk_forward_proof import HistoricalWalkForwardProofService


COMPONENTS = ["liquidity", "fvg_displacement", "htf_alignment", "ob_freshness", "trend_proxy"]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze low-confluence false negatives on same replay timestamps.")
    parser.add_argument("--symbol", default="BTCUSDC")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--family", default="sweep_reversal")
    parser.add_argument("--entry-model", default="LIMIT")
    parser.add_argument(
        "--replay-path",
        default="reports/validation/historical_walk_forward_cache/strategy_proof_contract_live_subset.json",
    )
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def _utc_from_iso(raw: str | None) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _load_replay_rows(*, replay_path: str, symbol: str, family: str, entry_model: str, days: int) -> list[dict[str, Any]]:
    payload = json.loads(Path(replay_path).read_text(encoding="utf-8"))
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
        if float(row.get("final_exit_realized_r") or 0.0) <= 0.0:
            continue
        item = dict(row)
        item["generated_dt"] = generated_ts
        filtered.append(item)
    return sorted(filtered, key=lambda row: row["generated_dt"])


def main() -> int:
    args = _parse_args()
    replay_rows = _load_replay_rows(
        replay_path=args.replay_path,
        symbol=args.symbol,
        family=args.family,
        entry_model=args.entry_model,
        days=args.days,
    )
    if not replay_rows:
        print(json.dumps({"symbol": args.symbol.upper(), "days": int(args.days), "count": 0}, ensure_ascii=False, indent=2))
        return 0

    init_db()
    settings = get_settings()
    warmup_5m_bars = max(int(settings.auto_trading_historical_walk_forward_warmup_5m_bars), 30)
    min_15m_bars = max(int(settings.auto_trading_historical_walk_forward_min_15m_bars), 30)
    max_5m_window = max(int(settings.auto_trading_historical_walk_forward_max_5m_window_bars), warmup_5m_bars)
    max_15m_window = max(int(settings.auto_trading_historical_walk_forward_max_15m_window_bars), min_15m_bars)

    target_timestamps = {row["generated_dt"] for row in replay_rows}
    start_ts = min(target_timestamps) - timedelta(days=10)
    end_ts = max(target_timestamps) + timedelta(minutes=5)

    low_confluence_rows: list[dict[str, Any]] = []
    weakest_component_counts: Counter[str] = Counter()
    avg_component_sums: Counter[str] = Counter()
    avg_weighted_contribution_sums: Counter[str] = Counter()
    regime_counts: Counter[str] = Counter()
    transition_lock_counts: Counter[str] = Counter()
    samples: list[dict[str, Any]] = []

    with SessionLocal() as db:
        candle_repo = CandleRepository(db)
        proof = HistoricalWalkForwardProofService(candle_repo=candle_repo, settings=settings)
        candles_5m = [c for c in proof._load_symbol_candles(symbol=args.symbol.upper(), timeframe="5m", start_ts=start_ts, end_ts=end_ts) if proof._normalize_ts(c.ts) is not None]
        candles_15m = [c for c in proof._load_symbol_candles(symbol=args.symbol.upper(), timeframe="15m", start_ts=start_ts, end_ts=end_ts) if proof._normalize_ts(c.ts) is not None]
        existing_zones: list[Any] = []
        idx_15 = -1
        replay_map = {row["generated_dt"]: row for row in replay_rows}

        for idx_5, candle in enumerate(candles_5m):
            current_ts = proof._normalize_ts(candle.ts)
            assert current_ts is not None
            if current_ts not in target_timestamps:
                continue
            advanced_15m = False
            while idx_15 + 1 < len(candles_15m):
                next_ts = proof._normalize_ts(candles_15m[idx_15 + 1].ts)
                if next_ts is None or next_ts > current_ts:
                    break
                idx_15 += 1
                advanced_15m = True
            if idx_5 + 1 < warmup_5m_bars or idx_15 + 1 < min_15m_bars or not advanced_15m:
                continue

            replay_row = replay_map[current_ts]
            candles_5m_window = candles_5m[max(0, idx_5 + 1 - max_5m_window) : idx_5 + 1]
            candles_15m_window = candles_15m[max(0, idx_15 + 1 - max_15m_window) : idx_15 + 1]
            context = proof.context_engine.build_snapshot(symbol=args.symbol.upper(), candles_5m=candles_5m_window, candles_15m=candles_15m_window)
            zones = proof.zone_engine.refresh(symbol=args.symbol.upper(), candles_15m=candles_15m_window, existing=existing_zones)
            zones = proof._normalize_zone_timestamps(zones, current_ts=current_ts)
            existing_zones = zones
            active_zones = [zone for zone in zones if str(zone.state or "") != "expired"]
            profile = proof.plan_generator._regime_profile(context)
            now = current_ts

            directional: list[dict[str, Any]] = []
            for zone in active_zones:
                direction = str(proof.plan_generator._direction(zone).value).lower()
                if direction != str(replay_row.get("direction") or "").lower():
                    continue
                stats = dict(zone.stats or {})
                near_lp = proof.plan_generator._find_near_lp(zone, active_zones, context.atr15)
                score, components, _base_weights, active_weights, zone_type_multiplier = proof.plan_generator._confluence_score(
                    zone,
                    context,
                    near_lp,
                    stats,
                    profile,
                    now,
                )
                gate_reason = proof.plan_generator._hard_gate(zone, context, score, profile)
                directional.append(
                    {
                        "zone_id": zone.zone_id,
                        "zone_type": zone.type,
                        "dir_bias": zone.dir_bias,
                        "near_lp": near_lp,
                        "score": float(score),
                        "components": dict(components),
                        "active_weights": dict(active_weights),
                        "gate_reason": gate_reason,
                        "zone_type_multiplier": float(zone_type_multiplier),
                    }
                )

            if not directional:
                continue

            best = max(directional, key=lambda item: item["score"])
            if best.get("gate_reason") != "low_confluence":
                continue

            low_confluence_rows.append(
                {
                    "generated_ts": current_ts.isoformat(),
                    "direction": replay_row.get("direction"),
                    "final_exit_realized_r": float(replay_row.get("final_exit_realized_r") or 0.0),
                    "score": round(best["score"], 4),
                    "min_confluence": round(float(profile.min_confluence), 4),
                    "score_gap": round(float(profile.min_confluence) - float(best["score"]), 4),
                    "components": best["components"],
                    "active_weights": best["active_weights"],
                    "regime_profile": profile.name,
                    "transition_state": context.transition_state,
                    "transition_lock_reason": context.transition_lock_reason,
                    "zone_type": best["zone_type"],
                    "near_lp": best["near_lp"],
                    "zone_type_multiplier": round(best["zone_type_multiplier"], 4),
                }
            )

            weakest_component = min(COMPONENTS, key=lambda key: float(best["components"].get(key, 0.0)))
            weakest_component_counts[weakest_component] += 1
            for key in COMPONENTS:
                component_score = float(best["components"].get(key, 0.0))
                weight = float(best["active_weights"].get(key, 0.0))
                avg_component_sums[key] += component_score
                avg_weighted_contribution_sums[key] += component_score * weight
            regime_counts[profile.name] += 1
            transition_lock_counts[str(context.transition_lock_reason or "none")] += 1
            if len(samples) < 20:
                samples.append(low_confluence_rows[-1])

    count = len(low_confluence_rows)
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "symbol": args.symbol.upper(),
        "days": int(args.days),
        "family": args.family.lower(),
        "entry_model": args.entry_model.upper(),
        "replay_positive_count": len(replay_rows),
        "low_confluence_count": count,
        "weakest_component_counts": dict(sorted(weakest_component_counts.items(), key=lambda item: (-item[1], item[0]))),
        "average_component_scores": {
            key: round(avg_component_sums[key] / count, 4) if count else 0.0
            for key in COMPONENTS
        },
        "average_weighted_contributions": {
            key: round(avg_weighted_contribution_sums[key] / count, 4) if count else 0.0
            for key in COMPONENTS
        },
        "average_score_gap_to_min_confluence": round(
            sum(float(row["score_gap"]) for row in low_confluence_rows) / count, 4
        ) if count else 0.0,
        "regime_profile_counts": dict(sorted(regime_counts.items(), key=lambda item: (-item[1], item[0]))),
        "transition_lock_reason_counts": dict(sorted(transition_lock_counts.items(), key=lambda item: (-item[1], item[0]))),
        "sample_rows": samples,
        "notes": [
            "Each replay-positive timestamp is rebuilt with the current runtime engine.",
            "For each timestamp, the best directional active zone by confluence score is selected.",
            "This report only keeps rows where that best directional zone still fails the hard gate with low_confluence.",
        ],
    }

    if args.write_report:
        out_dir = ROOT_DIR / "reports" / "validation" / "promotion_mismatch"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / (
            f"low_confluence_component_diff_{args.symbol.upper()}_{args.family.lower()}_{args.entry_model.upper()}_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
        )
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        payload["report_path"] = str(out_path)

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
