#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
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
from app.services.historical_walk_forward_split_review import HistoricalWalkForwardSplitReviewService
from scripts.run_reaction_gate_variant_backtest import VariantConfig, VariantPlanGenerator


REACTION_VALID_CLASSES = {"rejection_confirmed", "rejection_tentative"}
PLAN_CLOSED_STATES = {"CLOSED", "ARCHIVED"}
SUBMISSION_FILLED_STATES = {"PARTIALLY_FILLED", "FILLED"}


@dataclass(frozen=True, slots=True)
class RescueVariant:
    name: str
    config: VariantConfig


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze replay-vs-runtime promotion mismatch waterfall.")
    parser.add_argument("--symbol", default="BTCUSDC")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument(
        "--replay-path",
        default="reports/validation/historical_walk_forward_cache/strategy_proof_contract_live_subset.json",
    )
    parser.add_argument("--db-path", default="trading.db")
    parser.add_argument("--family", default="sweep_reversal")
    parser.add_argument("--entry-model", default="LIMIT")
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def _resolve_root_path(raw_path: str | Path) -> Path:
    path = Path(raw_path)
    return path if path.is_absolute() else ROOT_DIR / path


def _connect_readonly_sqlite(path: str | Path) -> sqlite3.Connection:
    db_path = _resolve_root_path(path).resolve()
    if not db_path.exists():
        raise FileNotFoundError(f"SQLite database not found: {db_path}")
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def _json_loads(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return default


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


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _floor_15m(ts: datetime) -> str:
    minute = (ts.minute // 15) * 15
    floored = ts.replace(minute=minute, second=0, microsecond=0)
    return floored.isoformat()


def _replay_match_key(row: dict[str, Any]) -> str:
    generated_ts = _utc_from_iso(str(row.get("generated_ts") or "")) or datetime.min.replace(tzinfo=UTC)
    return "|".join(
        [
            str(row.get("symbol") or "").upper(),
            str(row.get("direction") or "").lower(),
            str(row.get("entry_model") or "").upper(),
            _floor_15m(generated_ts),
        ]
    )


def _runtime_match_key(row: dict[str, Any]) -> str:
    generated_ts = _utc_from_iso(str(row.get("valid_from") or "")) or datetime.min.replace(tzinfo=UTC)
    return "|".join(
        [
            str(row.get("symbol") or "").upper(),
            str(row.get("direction") or "").lower(),
            str(row.get("entry_model") or "").upper(),
            _floor_15m(generated_ts),
        ]
    )


def _runtime_broad_key(row: dict[str, Any]) -> str:
    generated_ts = _utc_from_iso(str(row.get("valid_from") or "")) or datetime.min.replace(tzinfo=UTC)
    return "|".join(
        [
            str(row.get("symbol") or "").upper(),
            str(row.get("direction") or "").lower(),
            _floor_15m(generated_ts),
        ]
    )


def _replay_broad_key(row: dict[str, Any]) -> str:
    generated_ts = _utc_from_iso(str(row.get("generated_ts") or "")) or datetime.min.replace(tzinfo=UTC)
    return "|".join(
        [
            str(row.get("symbol") or "").upper(),
            str(row.get("direction") or "").lower(),
            _floor_15m(generated_ts),
        ]
    )


def _replay_symbol_direction_key(row: dict[str, Any]) -> str:
    return "|".join(
        [
            str(row.get("symbol") or "").upper(),
            str(row.get("direction") or "").lower(),
        ]
    )


def _runtime_symbol_direction_key(row: dict[str, Any]) -> str:
    return "|".join(
        [
            str(row.get("symbol") or "").upper(),
            str(row.get("direction") or "").lower(),
        ]
    )


def _minutes_apart(left: datetime | None, right: datetime | None) -> float | None:
    if left is None or right is None:
        return None
    return abs((left - right).total_seconds()) / 60.0


def _load_runtime_data(*, db_path: str, symbol: str, days: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    conn = _connect_readonly_sqlite(db_path)
    conn.row_factory = sqlite3.Row
    cutoff = (datetime.now(UTC) - timedelta(days=max(int(days), 1))).isoformat()

    plans_query = """
        SELECT plan_id, symbol, timeframe, direction, entry_model, state, valid_from, valid_until, validity
        FROM plans
        WHERE symbol = ? AND timeframe = '5m' AND (valid_from >= ? OR valid_until >= ?)
        ORDER BY valid_from DESC
    """
    intents_query = """
        SELECT intent_id, plan_id, symbol, execution_mode, approval_state, submit_decision,
               decision_reason_code, decision_reason_message, created_at, approval_snapshot
        FROM order_intents
        WHERE symbol = ? AND created_at >= ?
        ORDER BY created_at DESC
    """
    submissions_query = """
        SELECT submission_id, intent_id, plan_id, symbol, state, submit_status, execution_mode,
               requested_live, submitted_at, updated_at
        FROM order_submissions
        WHERE symbol = ? AND submitted_at >= ?
        ORDER BY submitted_at DESC
    """

    plans = [dict(row) for row in conn.execute(plans_query, (symbol.upper(), cutoff, cutoff)).fetchall()]
    intents = [dict(row) for row in conn.execute(intents_query, (symbol.upper(), cutoff)).fetchall()]
    submissions = [dict(row) for row in conn.execute(submissions_query, (symbol.upper(), cutoff)).fetchall()]
    conn.close()
    return plans, intents, submissions


def _load_replay_rows(*, replay_path: str, symbol: str, days: int, family: str, entry_model: str) -> list[dict[str, Any]]:
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
        filtered.append(dict(row))
    return filtered


def _runtime_rows_with_flags(
    *,
    plans: list[dict[str, Any]],
    family: str,
    entry_model: str,
    intents: list[dict[str, Any]],
    submissions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    latest_intent_by_plan: dict[str, dict[str, Any]] = {}
    for row in intents:
        plan_id = str(row.get("plan_id") or "")
        if plan_id and plan_id not in latest_intent_by_plan:
            latest_intent_by_plan[plan_id] = row

    latest_submission_by_plan: dict[str, dict[str, Any]] = {}
    for row in submissions:
        plan_id = str(row.get("plan_id") or "")
        if plan_id and plan_id not in latest_submission_by_plan:
            latest_submission_by_plan[plan_id] = row

    out: list[dict[str, Any]] = []
    for row in plans:
        validity = _json_loads(row.get("validity"), {})
        strategy_family = str(validity.get("strategy_family") or "").lower()
        strategy_family_reason = str(validity.get("strategy_family_reason") or "unknown")
        reaction_classification = str(validity.get("reaction_classification") or "unknown").lower()
        runtime_row = {
            **row,
            "validity": validity,
            "strategy_family": strategy_family,
            "strategy_family_reason": strategy_family_reason,
            "reaction_classification": reaction_classification,
            "raw_sweep_detected": True,
            "reaction_validated": reaction_classification in REACTION_VALID_CLASSES,
            "strategy_family_matched": strategy_family == family.lower(),
            "candidate_generated": strategy_family == family.lower() and str(row.get("entry_model") or "").upper() == entry_model.upper(),
        }
        plan_id = str(row.get("plan_id") or "")
        intent = latest_intent_by_plan.get(plan_id)
        submission = latest_submission_by_plan.get(plan_id)
        runtime_row["contract_promoted"] = bool(runtime_row["candidate_generated"])
        runtime_row["intent_created"] = bool(intent)
        runtime_row["submitted"] = bool(submission)
        runtime_row["filled"] = bool(submission and str(submission.get("state") or "").upper() in SUBMISSION_FILLED_STATES)
        runtime_row["closed"] = str(row.get("state") or "").upper() in PLAN_CLOSED_STATES
        runtime_row["policy_reason"] = str((intent or {}).get("decision_reason_code") or "")
        out.append(runtime_row)
    return out


def _compute_waterfall(*, replay_rows: list[dict[str, Any]], runtime_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    replay_closed_count = len(replay_rows)
    stages = [
        ("raw_sweep_detected", lambda _: True, lambda row: bool(row.get("raw_sweep_detected"))),
        ("reaction_validated", lambda _: True, lambda row: bool(row.get("reaction_validated"))),
        ("strategy_family_matched", lambda _: True, lambda row: bool(row.get("strategy_family_matched"))),
        ("candidate_generated", lambda _: True, lambda row: bool(row.get("candidate_generated"))),
        ("contract_promoted", lambda _: True, lambda row: bool(row.get("contract_promoted"))),
        ("intent_created", None, lambda row: bool(row.get("contract_promoted")) and bool(row.get("intent_created"))),
        ("submitted", None, lambda row: bool(row.get("contract_promoted")) and bool(row.get("submitted"))),
        ("filled", None, lambda row: bool(row.get("contract_promoted")) and bool(row.get("filled"))),
        ("closed", lambda _: True, lambda row: bool(row.get("contract_promoted")) and bool(row.get("closed"))),
    ]
    out: list[dict[str, Any]] = []
    for stage_name, replay_predicate, runtime_predicate in stages:
        replay_count = (
            sum(1 for row in replay_rows if replay_predicate(row))
            if replay_predicate is not None
            else None
        )
        runtime_count = sum(1 for row in runtime_rows if runtime_predicate(row))
        out.append(
            {
                "stage": stage_name,
                "replay_count": (int(replay_count) if replay_count is not None else None),
                "runtime_count": int(runtime_count),
                "gap": (
                    int(max(replay_count - runtime_count, 0))
                    if replay_count is not None
                    else None
                ),
                "note": (
                    "runtime-only downstream stage"
                    if replay_predicate is None
                    else (
                        "replay closed-trade window count"
                        if replay_count == replay_closed_count
                        else "replay stage count"
                    )
                ),
            }
        )
    return out


def _simulate_variant_rows(
    *,
    symbol: str,
    days: int,
    family: str,
    entry_model: str,
    variant: RescueVariant,
) -> list[dict[str, Any]]:
    init_db()
    settings = get_settings()
    review = HistoricalWalkForwardSplitReviewService(settings=settings)
    del review  # not used here but keeps imports consistent

    with SessionLocal() as db:
        candle_repo = CandleRepository(db)
        baseline_proof = HistoricalWalkForwardProofService(candle_repo=candle_repo, settings=settings)
        latest_source_ts, _, first_source_ts, _ = baseline_proof._source_ts_bounds((symbol.upper(),))
        if latest_source_ts is None or first_source_ts is None:
            return []
        start_ts = max(first_source_ts, latest_source_ts - timedelta(days=max(int(days), 1)))
        end_ts = latest_source_ts
        proof = HistoricalWalkForwardProofService(
            candle_repo=candle_repo,
            settings=settings,
            plan_generator=VariantPlanGenerator(variant.config),
        )
        payload = proof._simulate_symbol(
            symbol=symbol.upper(),
            start_ts=start_ts,
            end_ts=end_ts,
            eligible_symbols={symbol.upper()},
            eligible_families={family.lower()},
            eligible_entry_models={entry_model.upper()},
            generate_on_new_15m_only=True,
            independent_signal_mode=True,
            max_candidates_per_bar=1,
            source_mode="engine_regenerated",
            blocked_time_contract=[],
            blocked_plan_ids=set(),
        )
        rows = list(payload.get("trade_rows") or [])
        return [dict(row) for row in rows]


def _rescue_buckets(
    *,
    baseline_rows: list[dict[str, Any]],
    proof_rows: list[dict[str, Any]],
    one_bar_rows: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    baseline_keys = {_replay_match_key(row) for row in baseline_rows}
    proof_map = {_replay_match_key(row): row for row in proof_rows}
    one_bar_map = {_replay_match_key(row): row for row in one_bar_rows}
    all_keys = set(proof_map) | set(one_bar_map) | baseline_keys

    buckets: dict[str, list[dict[str, Any]]] = {
        "proof_reclaim_only": [],
        "one_bar_only": [],
        "both": [],
        "neither": [],
    }

    for key in sorted(all_keys):
        in_baseline = key in baseline_keys
        in_proof = key in proof_map
        in_one_bar = key in one_bar_map
        representative = proof_map.get(key) or one_bar_map.get(key)
        if not in_baseline and in_proof and not in_one_bar:
            buckets["proof_reclaim_only"].append(representative)
        elif not in_baseline and in_one_bar and not in_proof:
            buckets["one_bar_only"].append(representative)
        elif not in_baseline and in_proof and in_one_bar:
            buckets["both"].append(representative)
        elif in_baseline:
            buckets["neither"].append(representative or next(row for row in baseline_rows if _replay_match_key(row) == key))

    out: dict[str, dict[str, Any]] = {}
    for bucket, rows in buckets.items():
        realized = [_safe_float(row.get("final_exit_realized_r")) for row in rows]
        profitable = [value for value in realized if value > 0.0]
        out[bucket] = {
            "count": len(rows),
            "ev_r": round(sum(realized) / len(realized), 4) if realized else 0.0,
            "post_cost_profit_rate": round(len(profitable) / len(rows), 4) if rows else 0.0,
        }
    return out


def _classify_false_negatives(
    *,
    replay_rows: list[dict[str, Any]],
    runtime_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int], dict[str, Any]]:
    runtime_promoted_keys = {_runtime_match_key(row) for row in runtime_rows if row.get("contract_promoted")}
    runtime_by_broad: dict[str, list[dict[str, Any]]] = defaultdict(list)
    runtime_by_symbol_direction: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in runtime_rows:
        runtime_by_broad[_runtime_broad_key(row)].append(row)
        runtime_by_symbol_direction[_runtime_symbol_direction_key(row)].append(row)

    false_negatives: list[dict[str, Any]] = []
    reason_counts: Counter[str] = Counter()
    stage_counts: Counter[str] = Counter()
    generation_breakdown: Counter[str] = Counter()
    reaction_breakdown: Counter[str] = Counter()
    promotion_breakdown: Counter[str] = Counter()
    policy_breakdown: Counter[str] = Counter()
    for row in replay_rows:
        if _safe_float(row.get("final_exit_realized_r")) <= 0.0:
            continue
        exact_key = _replay_match_key(row)
        if exact_key in runtime_promoted_keys:
            continue
        broad_key = _replay_broad_key(row)
        broad_matches = runtime_by_broad.get(broad_key, [])
        replay_ts = _utc_from_iso(str(row.get("generated_ts") or ""))
        symbol_direction_matches = runtime_by_symbol_direction.get(_replay_symbol_direction_key(row), [])
        if not broad_matches:
            same_entry_nearby = False
            other_entry_nearby = False
            nearest_same_entry_minutes: float | None = None
            nearest_other_entry_minutes: float | None = None
            for match in symbol_direction_matches:
                match_ts = _utc_from_iso(str(match.get("valid_from") or ""))
                minutes = _minutes_apart(replay_ts, match_ts)
                if minutes is None or minutes > 15.0:
                    continue
                if str(match.get("entry_model") or "").upper() == str(row.get("entry_model") or "").upper():
                    same_entry_nearby = True
                    nearest_same_entry_minutes = minutes if nearest_same_entry_minutes is None else min(nearest_same_entry_minutes, minutes)
                else:
                    other_entry_nearby = True
                    nearest_other_entry_minutes = minutes if nearest_other_entry_minutes is None else min(nearest_other_entry_minutes, minutes)
            if same_entry_nearby:
                reason = "generation_mismatch:time_alignment_same_entry_model"
            elif other_entry_nearby:
                reason = "generation_mismatch:time_alignment_other_entry_model"
            else:
                reason = "generation_mismatch:no_runtime_plan"
            stage = "generation"
            generation_breakdown[reason] += 1
        else:
            same_entry_matches = [
                match
                for match in broad_matches
                if str(match.get("entry_model") or "").upper() == str(row.get("entry_model") or "").upper()
            ]
            if not same_entry_matches:
                reason = "generation_mismatch:same_bucket_other_entry_model_only"
                stage = "generation"
                generation_breakdown[reason] += 1
            else:
                reason_counter: Counter[str] = Counter()
                for match in same_entry_matches:
                    reaction = str(match.get("reaction_classification") or "unknown")
                    family_reason = str(match.get("strategy_family_reason") or "unknown")
                    if not match.get("reaction_validated"):
                        reason_counter[f"reaction_mismatch:{reaction}"] += 1
                    elif not match.get("strategy_family_matched"):
                        reason_counter[f"promotion_mismatch:{family_reason}"] += 1
                    elif not match.get("intent_created"):
                        policy_reason = str(match.get("policy_reason") or "no_intent_created")
                        reason_counter[f"policy_mismatch:{policy_reason}"] += 1
                    else:
                        reason_counter["contract_mismatch:unclassified"] += 1
                reason = max(reason_counter.items(), key=lambda item: (item[1], item[0]))[0]
                if reason.startswith("reaction_mismatch:"):
                    stage = "reaction"
                    reaction_breakdown[reason] += 1
                elif reason.startswith("promotion_mismatch:"):
                    stage = "promotion"
                    promotion_breakdown[reason] += 1
                elif reason.startswith("policy_mismatch:"):
                    stage = "policy"
                    policy_breakdown[reason] += 1
                else:
                    stage = "contract"
            same_entry_count = len(same_entry_matches)
            nearest_same_entry_minutes = None
            for match in same_entry_matches:
                reaction = str(match.get("reaction_classification") or "unknown")
                del reaction  # local analysis is already stored in reason_counter
                match_ts = _utc_from_iso(str(match.get("valid_from") or ""))
                minutes = _minutes_apart(replay_ts, match_ts)
                if minutes is not None:
                    nearest_same_entry_minutes = minutes if nearest_same_entry_minutes is None else min(nearest_same_entry_minutes, minutes)
        stage_counts[stage] += 1

        false_negatives.append(
            {
                "match_key": exact_key,
                "symbol": row.get("symbol"),
                "direction": row.get("direction"),
                "generated_ts": row.get("generated_ts"),
                "entry_model": row.get("entry_model"),
                "final_exit_realized_r": _safe_float(row.get("final_exit_realized_r")),
                "failure_stage": stage,
                "failure_reason": reason,
                "same_bucket_plan_count": len(broad_matches),
                "same_bucket_same_entry_model_count": (
                    same_entry_count if broad_matches else 0
                ),
                "nearest_same_entry_model_minutes": nearest_same_entry_minutes,
            }
        )
        reason_counts[reason] += 1
    diagnostics = {
        "false_negative_stage_counts": dict(stage_counts),
        "generation_mismatch_breakdown": dict(generation_breakdown),
        "reaction_mismatch_breakdown": dict(reaction_breakdown),
        "promotion_mismatch_breakdown": dict(promotion_breakdown),
        "policy_mismatch_breakdown": dict(policy_breakdown),
    }
    return false_negatives, dict(reason_counts), diagnostics


def _runtime_downstream_summary(runtime_rows: list[dict[str, Any]]) -> dict[str, float]:
    promoted = [row for row in runtime_rows if row.get("contract_promoted")]
    if not promoted:
        return {
            "contract_promoted": 0.0,
            "intent_created_rate": 0.0,
            "submitted_rate": 0.0,
            "filled_rate": 0.0,
            "closed_rate": 0.0,
        }
    total = len(promoted)
    return {
        "contract_promoted": float(total),
        "intent_created_rate": round(sum(1 for row in promoted if row.get("intent_created")) / total, 4),
        "submitted_rate": round(sum(1 for row in promoted if row.get("submitted")) / total, 4),
        "filled_rate": round(sum(1 for row in promoted if row.get("filled")) / total, 4),
        "closed_rate": round(sum(1 for row in promoted if row.get("closed")) / total, 4),
    }


def main() -> int:
    args = _parse_args()
    replay_rows = _load_replay_rows(
        replay_path=args.replay_path,
        symbol=args.symbol,
        days=args.days,
        family=args.family,
        entry_model=args.entry_model,
    )
    plans, intents, submissions = _load_runtime_data(
        db_path=args.db_path,
        symbol=args.symbol,
        days=args.days,
    )
    runtime_rows = _runtime_rows_with_flags(
        plans=plans,
        family=args.family,
        entry_model=args.entry_model,
        intents=intents,
        submissions=submissions,
    )

    waterfall = _compute_waterfall(replay_rows=replay_rows, runtime_rows=runtime_rows)
    false_negatives, reason_counts, mismatch_diagnostics = _classify_false_negatives(
        replay_rows=replay_rows,
        runtime_rows=runtime_rows,
    )

    baseline_rows = _simulate_variant_rows(
        symbol=args.symbol,
        days=args.days,
        family=args.family,
        entry_model=args.entry_model,
        variant=RescueVariant("baseline_strict", VariantConfig(name="baseline_strict")),
    )
    proof_rows = _simulate_variant_rows(
        symbol=args.symbol,
        days=args.days,
        family=args.family,
        entry_model=args.entry_model,
        variant=RescueVariant("proof_reclaim_only", VariantConfig(name="proof_reclaim_only", proof_reclaim=True)),
    )
    one_bar_rows = _simulate_variant_rows(
        symbol=args.symbol,
        days=args.days,
        family=args.family,
        entry_model=args.entry_model,
        variant=RescueVariant("one_bar_only", VariantConfig(name="one_bar_only", one_bar=True)),
    )
    rescue_buckets = _rescue_buckets(
        baseline_rows=baseline_rows,
        proof_rows=proof_rows,
        one_bar_rows=one_bar_rows,
    )

    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "symbol": args.symbol.upper(),
        "days": int(args.days),
        "family": args.family.lower(),
        "entry_model": args.entry_model.upper(),
        "replay_valid_count": len(replay_rows),
        "runtime_plan_count": len(runtime_rows),
        "waterfall": waterfall,
        "false_negative_count": len(false_negatives),
        "false_negative_reason_counts": reason_counts,
        "top_false_negative_reasons": sorted(reason_counts.items(), key=lambda item: (-item[1], item[0]))[:5],
        **mismatch_diagnostics,
        "rescue_buckets": rescue_buckets,
        "runtime_downstream": _runtime_downstream_summary(runtime_rows),
        "notes": [
            "Replay-side rescue buckets are simulated future-blind variants, not stored runtime plan fields.",
            "Runtime downstream uses plan/intent/submission availability only; post-cost profit is replay-side only.",
            "Match keys use symbol + direction + entry_model + generated 15m bucket; broad mismatch reasons fall back to symbol + direction + 15m bucket.",
            "Replay cache rows do not expose explicit proof_reclaim/one_bar stage flags, so generation/reaction mismatch is inferred from the nearest runtime plans in the same or adjacent 15m bucket.",
        ],
    }

    if args.write_report:
        out_dir = ROOT_DIR / "reports" / "validation" / "promotion_mismatch"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / (
            f"promotion_mismatch_waterfall_{args.symbol.upper()}_{args.family.lower()}_{args.entry_model.upper()}_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
        )
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        payload["report_path"] = str(out_path)

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
