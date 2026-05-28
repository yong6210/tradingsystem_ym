#!/usr/bin/env python3
from __future__ import annotations

import argparse
import itertools
import json
import math
import random
import statistics
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.report_io import atomic_write_text
from scripts import analyze_multi_asset_rotation_walkforward as wf


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Research-only PBO audit for a causal walk-forward selector rule.")
    parser.add_argument("--reports", nargs="+", required=True)
    parser.add_argument("--period", choices=("year", "quarter", "month"), default="quarter")
    parser.add_argument("--selector-mode", choices=("balanced", "calmar", "consistency", "minimax"), default="calmar")
    parser.add_argument("--test-fraction", type=float, default=0.5)
    parser.add_argument("--max-splits", type=int, default=5000)
    parser.add_argument("--sample-seed", type=int, default=1729)
    parser.add_argument("--max-full-sample-dd-pct", type=float, default=45.0)
    parser.add_argument("--max-train-worst-year-pct", type=float, default=-100.0)
    parser.add_argument("--max-train-period-dd-pct", type=float, default=100.0)
    parser.add_argument("--min-train-positive-fraction", type=float, default=0.0)
    parser.add_argument("--max-pbo-proxy", type=float, default=0.25)
    parser.add_argument("--report-dir", default="reports/validation/walkforward_selector_pbo")
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def _period_field(period: str) -> str:
    return {
        "year": "by_year_return_pct",
        "quarter": "by_quarter_return_pct",
        "month": "by_month_return_pct",
    }[period]


def _returns_by_candidate(candidates: list[dict[str, Any]], period: str) -> dict[str, dict[str, float]]:
    field = _period_field(period)
    out: dict[str, dict[str, float]] = {}
    for candidate in candidates:
        summary = dict(candidate.get("summary") or {})
        candidate_id = str(candidate.get("candidate_id") or summary.get("model_id") or "")
        returns = {
            str(key): wf._as_float(value, math.nan)
            for key, value in dict(summary.get(field) or {}).items()
        }
        if candidate_id and returns:
            out[candidate_id] = returns
    return out


def _selector_score(
    returns: dict[str, float],
    periods: list[str],
    args: argparse.Namespace,
) -> float:
    return wf._train_score(
        returns,
        periods,
        max_train_worst_year_pct=float(args.max_train_worst_year_pct),
        max_train_period_dd_pct=float(args.max_train_period_dd_pct),
        min_train_positive_fraction=float(args.min_train_positive_fraction),
        selector_mode=str(args.selector_mode),
    )


def _rank_pct(scores: dict[str, float], candidate_id: str) -> float:
    valid = [(cid, score) for cid, score in scores.items() if math.isfinite(score)]
    if len(valid) <= 1:
        return math.nan
    ordered = sorted(valid, key=lambda item: item[1], reverse=True)
    for rank, (cid, _) in enumerate(ordered):
        if cid == candidate_id:
            return rank / max(len(ordered) - 1, 1)
    return math.nan


def _make_splits(periods: list[str], args: argparse.Namespace) -> tuple[list[tuple[str, ...]], str, int]:
    test_size = max(1, min(len(periods) - 1, int(round(len(periods) * min(max(float(args.test_fraction), 0.1), 0.9)))))
    train_size = len(periods) - test_size
    total_possible = math.comb(len(periods), train_size)
    if total_possible <= int(args.max_splits):
        return [tuple(item) for item in itertools.combinations(periods, train_size)], "exhaustive", total_possible
    rng = random.Random(int(args.sample_seed))
    split_set: set[tuple[str, ...]] = set()
    attempts = 0
    while len(split_set) < int(args.max_splits) and attempts < int(args.max_splits) * 25:
        attempts += 1
        split_set.add(tuple(sorted(rng.sample(periods, train_size))))
    return sorted(split_set), "sampled", total_possible


def main() -> int:
    args = _parse_args()
    candidates = wf._load_candidates(
        [str(path) for path in args.reports],
        max_full_sample_dd_pct=float(args.max_full_sample_dd_pct),
    )
    returns_by_id = _returns_by_candidate(candidates, str(args.period))
    candidate_ids = sorted(returns_by_id)
    periods = sorted({period for returns in returns_by_id.values() for period in returns})
    if len(candidate_ids) < 2 or len(periods) < 4:
        raise SystemExit("too few candidates or periods for selector PBO")

    splits, split_sampling, total_possible = _make_splits(periods, args)
    overfit_count = 0
    valid_count = 0
    rank_values: list[float] = []
    selection_counts: Counter[str] = Counter()
    examples: list[dict[str, Any]] = []
    for train_tuple in splits:
        train_periods = list(train_tuple)
        test_periods = [period for period in periods if period not in set(train_periods)]
        train_scores = {
            cid: _selector_score(returns_by_id[cid], train_periods, args)
            for cid in candidate_ids
        }
        test_scores = {
            cid: _selector_score(returns_by_id[cid], test_periods, args)
            for cid in candidate_ids
        }
        valid_train = {cid: score for cid, score in train_scores.items() if math.isfinite(score)}
        valid_test = {cid: score for cid, score in test_scores.items() if math.isfinite(score)}
        if len(valid_train) < 2 or len(valid_test) < 2:
            continue
        selected_id = max(valid_train.items(), key=lambda item: item[1])[0]
        rank_pct = _rank_pct(valid_test, selected_id)
        if not math.isfinite(rank_pct):
            continue
        valid_count += 1
        rank_values.append(rank_pct)
        overfit_count += 1 if rank_pct > 0.50 else 0
        selection_counts[selected_id] += 1
        if len(examples) < 50:
            examples.append(
                {
                    "train_periods": train_periods,
                    "test_periods": test_periods,
                    "selected_candidate_id": selected_id,
                    "selected_test_rank_pct": round(rank_pct, 6),
                    "selected_train_score": round(train_scores[selected_id], 8),
                    "selected_test_score": round(test_scores[selected_id], 8),
                }
            )

    pbo_proxy = overfit_count / valid_count if valid_count else math.nan
    verdict = "PASS" if math.isfinite(pbo_proxy) and pbo_proxy <= float(args.max_pbo_proxy) else "FAIL"
    output = {
        "schema_version": "walkforward_selector_pbo_v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "authority": "research_only_no_live_authority_change",
        "input_reports": [str(path) for path in args.reports],
        "method": {
            "selector_mode": str(args.selector_mode),
            "period": str(args.period),
            "split_sampling": split_sampling,
            "total_possible_splits": total_possible,
            "evaluated_split_count": len(splits),
            "valid_split_count": valid_count,
            "sample_seed": int(args.sample_seed),
        },
        "verdict": {
            "level": verdict,
            "pbo_proxy": round(pbo_proxy, 6) if math.isfinite(pbo_proxy) else None,
            "max_pbo_proxy": float(args.max_pbo_proxy),
            "median_selected_test_rank_pct": round(statistics.median(rank_values), 6) if rank_values else None,
            "worst_selected_test_rank_pct": round(max(rank_values), 6) if rank_values else None,
            "live_trading_allowed": False,
        },
        "candidate_count": len(candidate_ids),
        "periods": periods,
        "selection_counts": dict(selection_counts.most_common()),
        "examples": examples,
    }
    if bool(args.write_report):
        report_dir = ROOT_DIR / str(args.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        out_path = report_dir / f"walkforward_selector_pbo_{stamp}.json"
        latest_path = report_dir / "latest.json"
        output["report_path"] = str(out_path.relative_to(ROOT_DIR))
        output["latest_report_path"] = str(latest_path.relative_to(ROOT_DIR))
        text = json.dumps(output, ensure_ascii=False, indent=2, default=str)
        atomic_write_text(out_path, text)
        atomic_write_text(latest_path, text)
    print(json.dumps({"verdict": output["verdict"], "candidate_count": len(candidate_ids)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
