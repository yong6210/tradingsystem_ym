#!/usr/bin/env python3
from __future__ import annotations

import argparse
import itertools
import json
import math
import random
import re
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


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit async rotation validation reports for backtest-overfit risk."
    )
    parser.add_argument("--reports", nargs="+", required=True)
    parser.add_argument("--selected-report", default="")
    parser.add_argument("--selected-model-id", default="")
    parser.add_argument("--include-model-regex", default="")
    parser.add_argument("--exclude-model-regex", default="")
    parser.add_argument("--min-scenarios", type=int, default=5)
    parser.add_argument("--min-candidates", type=int, default=4)
    parser.add_argument("--period", choices=("year", "quarter", "month"), default="year")
    parser.add_argument("--test-fraction", type=float, default=0.5)
    parser.add_argument("--max-splits", type=int, default=5000)
    parser.add_argument("--sample-seed", type=int, default=1729)
    parser.add_argument("--holdout-periods", type=int, default=0)
    parser.add_argument("--max-pbo-proxy", type=float, default=0.25)
    parser.add_argument("--max-selected-holdout-rank-pct", type=float, default=0.50)
    parser.add_argument("--max-dd-pct", type=float, default=50.0)
    parser.add_argument("--min-x", type=float, default=3.0)
    parser.add_argument("--report-dir", default="reports/validation/rotation_anti_overfit_audit")
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def _as_float(value: Any, default: float = math.nan) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def _relpath(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT_DIR))
    except ValueError:
        return str(path)


def _median(values: list[float]) -> float:
    finite = [value for value in values if math.isfinite(value)]
    return statistics.median(finite) if finite else math.nan


def _candidate_name(path: Path, result: dict[str, Any]) -> str:
    return f"{path.parent.name}:{result.get('model_id') or result.get('mix') or path.stem}"


def _period_returns_from_payloads(
    payloads: list[dict[str, Any]],
    *,
    period_field: str,
) -> dict[str, dict[str, float]]:
    period_values: dict[str, list[float]] = {}
    for payload in payloads:
        for period_key, value in dict(payload.get(period_field) or {}).items():
            period_values.setdefault(str(period_key), []).append(_as_float(value))
    period_returns_pct: dict[str, dict[str, float]] = {}
    for period_key, values in period_values.items():
        finite = [value for value in values if math.isfinite(value)]
        if not finite:
            continue
        period_returns_pct[period_key] = {
            "median_pct": _median(finite),
            "worst_pct": min(finite),
            "scenario_count": len(finite),
        }
    return period_returns_pct


def _period_score(period_returns_pct: dict[str, dict[str, float]], periods: list[str]) -> float:
    logs: list[float] = []
    worst_period = 0.0
    equity = peak = 1.0
    max_dd = 0.0
    for period in periods:
        payload = period_returns_pct.get(period)
        if not payload:
            return -math.inf
        median_return = _as_float(payload.get("median_pct"))
        worst_return = _as_float(payload.get("worst_pct"))
        if not math.isfinite(median_return) or median_return <= -99.9:
            return -math.inf
        period_return = median_return / 100.0
        logs.append(math.log1p(period_return))
        equity *= 1.0 + period_return
        peak = max(peak, equity)
        max_dd = max(max_dd, 1.0 - equity / max(peak, 1e-12))
        if math.isfinite(worst_return):
            worst_period = min(worst_period, worst_return / 100.0)
    if not logs:
        return -math.inf
    mean_log = sum(logs) / len(logs)
    variance = sum((value - mean_log) * (value - mean_log) for value in logs) / len(logs)
    volatility = math.sqrt(max(variance, 0.0))
    downside_penalty = max(0.0, -worst_period)
    return mean_log - 0.50 * volatility - 0.35 * max_dd - 0.25 * downside_penalty


def _rank_pct(scores: dict[str, float], candidate_id: str) -> float:
    valid = [(cid, score) for cid, score in scores.items() if math.isfinite(score)]
    if len(valid) <= 1 or candidate_id not in {cid for cid, _ in valid}:
        return math.nan
    ordered = sorted(valid, key=lambda item: item[1], reverse=True)
    rank = next(index for index, (cid, _) in enumerate(ordered) if cid == candidate_id)
    return rank / max(len(ordered) - 1, 1)


def _load_candidate(raw_path: str, *, min_scenarios: int, period: str) -> dict[str, Any] | None:
    path = Path(raw_path)
    if not path.is_absolute():
        path = ROOT_DIR / path
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    results = list(data.get("results") or [])
    if not results:
        return None
    result = dict(results[0])
    rows = [dict(row) for row in list(result.get("rows") or [])]
    if len(rows) < min_scenarios:
        return None

    period_field = {
        "year": "by_year_return_pct",
        "quarter": "by_quarter_return_pct",
        "month": "by_month_return_pct",
    }[period]
    period_returns_pct = _period_returns_from_payloads(rows, period_field=period_field)

    candidate_id = _relpath(path)
    return {
        "candidate_id": candidate_id,
        "model_id": str(result.get("model_id") or result.get("mix") or path.stem),
        "name": _candidate_name(path, result),
        "report_path": _relpath(path),
        "scenario_count": len(rows),
        "scenario_labels": [str(row.get("label")) for row in rows],
        "data_end_utc": data.get("data_end_utc"),
        "period_returns_pct": period_returns_pct,
        "metrics": {
            "geo": _as_float(result.get("geo")),
            "min_x": _as_float(result.get("min_x")),
            "max_dd_pct": _as_float(result.get("max_dd_pct")),
            "min_worst_year_pct": _as_float(result.get("min_worst_year_pct")),
        },
    }


def _load_all_results_candidates(
    raw_path: str,
    *,
    min_scenarios: int,
    period: str,
) -> list[dict[str, Any]]:
    path = Path(raw_path)
    if not path.is_absolute():
        path = ROOT_DIR / path
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    rows = [dict(row) for row in list(data.get("all_results") or [])]
    if not rows:
        return []
    if max(int(min_scenarios), 1) > 1:
        return []

    period_field = {
        "year": "by_year_return_pct",
        "quarter": "by_quarter_return_pct",
        "month": "by_month_return_pct",
    }[period]
    candidates: list[dict[str, Any]] = []
    for idx, row in enumerate(rows):
        summary = dict(row.get("summary") or {})
        if not summary:
            continue
        period_returns_pct = _period_returns_from_payloads([summary], period_field=period_field)
        if not period_returns_pct:
            continue
        config = dict(row.get("config") or {})
        model_id = str(summary.get("model_id") or config.get("model_id") or config.get("mix_id") or f"row_{idx}")
        total_return_pct = _as_float(summary.get("total_return_pct"))
        equity_multiple = 1.0 + total_return_pct / 100.0 if math.isfinite(total_return_pct) else math.nan
        max_dd_pct = _as_float(summary.get("max_drawdown_pct"))
        worst_year_pct = _as_float(summary.get("worst_year_pct"))
        candidates.append(
            {
                "candidate_id": f"{_relpath(path)}#{model_id}",
                "model_id": model_id,
                "name": f"{path.parent.name}:{model_id}",
                "report_path": _relpath(path),
                "scenario_count": 1,
                "scenario_labels": [str(data.get("cost_model", {}).get("slippage_bps_per_side", "default"))],
                "data_end_utc": data.get("data_end_utc") or data.get("generated_at"),
                "period_returns_pct": period_returns_pct,
                "metrics": {
                    "geo": equity_multiple,
                    "min_x": equity_multiple,
                    "max_dd_pct": max_dd_pct,
                    "min_worst_year_pct": worst_year_pct,
                    "cagr_pct": _as_float(summary.get("cagr_pct")),
                    "calmar": _as_float(summary.get("calmar")),
                    "score": _as_float(summary.get("score")),
                    "decision": str(summary.get("decision") or ""),
                },
            }
        )
    return candidates


def _load_candidates(raw_path: str, *, min_scenarios: int, period: str) -> list[dict[str, Any]]:
    all_results_candidates = _load_all_results_candidates(
        raw_path,
        min_scenarios=min_scenarios,
        period=period,
    )
    if all_results_candidates:
        return all_results_candidates
    candidate = _load_candidate(raw_path, min_scenarios=min_scenarios, period=period)
    return [candidate] if candidate is not None else []


def _filter_candidates(
    candidates: list[dict[str, Any]],
    *,
    include_model_regex: str,
    exclude_model_regex: str,
) -> list[dict[str, Any]]:
    include = re.compile(include_model_regex) if include_model_regex.strip() else None
    exclude = re.compile(exclude_model_regex) if exclude_model_regex.strip() else None
    filtered: list[dict[str, Any]] = []
    for candidate in candidates:
        haystack = f"{candidate.get('candidate_id', '')} {candidate.get('model_id', '')} {candidate.get('name', '')}"
        if include is not None and include.search(haystack) is None:
            continue
        if exclude is not None and exclude.search(haystack) is not None:
            continue
        filtered.append(candidate)
    return filtered


def _split_audit(
    candidates: list[dict[str, Any]],
    *,
    test_fraction: float,
    max_splits: int,
    sample_seed: int,
) -> dict[str, Any]:
    periods = sorted(
        {
            period
            for candidate in candidates
            for period in dict(candidate.get("period_returns_pct") or {})
        }
    )
    candidate_ids = [str(candidate["candidate_id"]) for candidate in candidates]
    period_returns = {
        str(candidate["candidate_id"]): dict(candidate.get("period_returns_pct") or {})
        for candidate in candidates
    }
    if len(periods) < 4 or len(candidate_ids) < 2:
        return {"available": False, "reason": "too_few_periods_or_candidates", "periods": periods}

    test_size = max(1, min(len(periods) - 1, int(round(len(periods) * min(max(test_fraction, 0.1), 0.9)))))
    train_size = len(periods) - test_size
    if train_size <= 0:
        return {"available": False, "reason": "empty_train_split", "periods": periods}

    total_possible_splits = math.comb(len(periods), train_size)
    max_splits = max(int(max_splits), 1)
    if total_possible_splits <= max_splits:
        train_splits = [tuple(item) for item in itertools.combinations(periods, train_size)]
        split_sampling = "exhaustive"
    else:
        rng = random.Random(int(sample_seed))
        split_set: set[tuple[str, ...]] = set()
        attempts = 0
        max_attempts = max_splits * 25
        while len(split_set) < max_splits and attempts < max_attempts:
            attempts += 1
            split_set.add(tuple(sorted(rng.sample(periods, train_size))))
        train_splits = sorted(split_set)
        split_sampling = "sampled"

    splits: list[dict[str, Any]] = []
    selection_counts: Counter[str] = Counter()
    overfit_count = 0
    valid_count = 0
    for train_tuple in train_splits:
        train_periods = list(train_tuple)
        test_periods = [period for period in periods if period not in set(train_periods)]
        train_scores = {
            cid: _period_score(period_returns[cid], train_periods)
            for cid in candidate_ids
        }
        test_scores = {
            cid: _period_score(period_returns[cid], test_periods)
            for cid in candidate_ids
        }
        valid_train = {cid: score for cid, score in train_scores.items() if math.isfinite(score)}
        valid_test = {cid: score for cid, score in test_scores.items() if math.isfinite(score)}
        if len(valid_train) < 2 or len(valid_test) < 2:
            continue
        selected = max(valid_train.items(), key=lambda item: item[1])[0]
        rank_pct = _rank_pct(valid_test, selected)
        if not math.isfinite(rank_pct):
            continue
        valid_count += 1
        overfit_count += 1 if rank_pct > 0.50 else 0
        selection_counts[selected] += 1
        splits.append(
            {
                "train_periods": train_periods,
                "test_periods": test_periods,
                "selected_candidate_id": selected,
                "selected_test_rank_pct": rank_pct,
                "selected_train_score": train_scores[selected],
                "selected_test_score": test_scores[selected],
            }
        )

    if valid_count <= 0:
        return {"available": False, "reason": "no_valid_splits", "periods": periods}
    rank_values = [float(split["selected_test_rank_pct"]) for split in splits]
    return {
        "available": True,
        "periods": periods,
        "split_count": valid_count,
        "total_possible_splits": total_possible_splits,
        "evaluated_split_count": len(train_splits),
        "split_sampling": split_sampling,
        "sample_seed": int(sample_seed),
        "pbo_proxy": overfit_count / valid_count,
        "median_selected_test_rank_pct": statistics.median(rank_values),
        "worst_selected_test_rank_pct": max(rank_values),
        "selection_counts": dict(selection_counts.most_common()),
        "splits": splits,
    }


def _holdout_audit(
    candidates: list[dict[str, Any]],
    *,
    selected_id: str | None,
    holdout_periods: int,
) -> dict[str, Any]:
    periods = sorted(
        {
            period
            for candidate in candidates
            for period in dict(candidate.get("period_returns_pct") or {})
        }
    )
    if len(periods) < 4:
        return {"available": False, "reason": "too_few_periods", "periods": periods}
    holdout_periods = max(1, min(int(holdout_periods), len(periods) - 1))
    train_periods = periods[:-holdout_periods]
    test_periods = periods[-holdout_periods:]
    period_returns = {
        str(candidate["candidate_id"]): dict(candidate.get("period_returns_pct") or {})
        for candidate in candidates
    }
    train_scores = {
        cid: _period_score(returns, train_periods)
        for cid, returns in period_returns.items()
    }
    test_scores = {
        cid: _period_score(returns, test_periods)
        for cid, returns in period_returns.items()
    }
    valid_train = {cid: score for cid, score in train_scores.items() if math.isfinite(score)}
    valid_test = {cid: score for cid, score in test_scores.items() if math.isfinite(score)}
    if len(valid_train) < 2 or len(valid_test) < 2:
        return {"available": False, "reason": "no_valid_scores", "periods": periods}
    train_winner = max(valid_train.items(), key=lambda item: item[1])[0]
    payload = {
        "available": True,
        "train_periods": train_periods,
        "test_periods": test_periods,
        "train_winner_candidate_id": train_winner,
        "train_winner_test_rank_pct": _rank_pct(valid_test, train_winner),
        "test_winner_candidate_id": max(valid_test.items(), key=lambda item: item[1])[0],
    }
    if selected_id:
        payload["selected_candidate_id"] = selected_id
        payload["selected_train_rank_pct"] = _rank_pct(valid_train, selected_id)
        payload["selected_test_rank_pct"] = _rank_pct(valid_test, selected_id)
    return payload


def _robust_score(candidate: dict[str, Any]) -> float:
    metrics = dict(candidate.get("metrics") or {})
    geo = max(_as_float(metrics.get("geo"), 0.0), 1e-12)
    min_x = max(_as_float(metrics.get("min_x"), 0.0), 1e-12)
    dd = _as_float(metrics.get("max_dd_pct"), 100.0)
    worst_year = _as_float(metrics.get("min_worst_year_pct"), -100.0)
    scenario_count = max(int(candidate.get("scenario_count") or 0), 1)
    return (
        math.log(geo)
        + 0.35 * math.log(min_x)
        - 0.020 * dd
        + 0.010 * worst_year
        + 0.025 * math.log(scenario_count)
    )


def _verdict(
    *,
    candidates: list[dict[str, Any]],
    selected: dict[str, Any] | None,
    split_audit: dict[str, Any],
    holdout_audit: dict[str, Any],
    args: argparse.Namespace,
) -> dict[str, Any]:
    issues: list[str] = []
    if len(candidates) < int(args.min_candidates):
        issues.append("candidate_universe_too_small")
    if not split_audit.get("available"):
        issues.append("pbo_proxy_unavailable")
    elif _as_float(split_audit.get("pbo_proxy"), 1.0) > float(args.max_pbo_proxy):
        issues.append("pbo_proxy_above_threshold")
    if selected is None:
        issues.append("selected_report_not_in_candidate_universe")
    else:
        metrics = dict(selected.get("metrics") or {})
        if _as_float(metrics.get("max_dd_pct"), 100.0) > float(args.max_dd_pct):
            issues.append("selected_dd_above_threshold")
        if _as_float(metrics.get("min_x"), 0.0) < float(args.min_x):
            issues.append("selected_min_x_below_threshold")
        if holdout_audit.get("available"):
            selected_rank = _as_float(holdout_audit.get("selected_test_rank_pct"), 1.0)
            if selected_rank > float(args.max_selected_holdout_rank_pct):
                issues.append("selected_holdout_rank_weak")
    if not issues:
        level = "PASS"
    elif any(issue in issues for issue in ("pbo_proxy_above_threshold", "selected_holdout_rank_weak")):
        level = "FAIL"
    else:
        level = "WARN"
    return {
        "level": level,
        "issues": issues,
        "policy": {
            "promotion_allowed": level == "PASS",
            "parameter_freeze_required": level != "PASS",
            "live_trading_allowed": False,
        },
    }


def main() -> int:
    args = _parse_args()
    candidates: list[dict[str, Any]] = []
    for raw_path in args.reports:
        candidates.extend(_load_candidates(
            raw_path,
            min_scenarios=max(int(args.min_scenarios), 1),
            period=str(args.period),
        ))
    candidates = _filter_candidates(
        candidates,
        include_model_regex=str(args.include_model_regex or ""),
        exclude_model_regex=str(args.exclude_model_regex or ""),
    )
    for candidate in candidates:
        candidate["robust_score"] = _robust_score(candidate)
    candidates.sort(key=lambda row: float(row["robust_score"]), reverse=True)

    selected_id: str | None = None
    selected: dict[str, Any] | None = None
    if str(args.selected_report).strip():
        selected_report = str(args.selected_report)
        selected_model_id = str(args.selected_model_id or "").strip()
        if "#" in selected_report and not selected_model_id:
            selected_report, selected_model_id = selected_report.split("#", 1)
        selected_path = Path(selected_report)
        if not selected_path.is_absolute():
            selected_path = ROOT_DIR / selected_path
        selected_id = (
            f"{_relpath(selected_path)}#{selected_model_id}"
            if selected_model_id
            else _relpath(selected_path)
        )
        selected = next((candidate for candidate in candidates if candidate["candidate_id"] == selected_id), None)
        if selected is None and selected_model_id:
            selected = next((candidate for candidate in candidates if candidate.get("model_id") == selected_model_id), None)
            if selected is not None:
                selected_id = str(selected["candidate_id"])

    split = _split_audit(
        candidates,
        test_fraction=float(args.test_fraction),
        max_splits=int(args.max_splits),
        sample_seed=int(args.sample_seed),
    )
    if int(args.holdout_periods) > 0:
        holdout_periods = int(args.holdout_periods)
    elif str(args.period) == "month":
        holdout_periods = 6
    elif str(args.period) == "quarter":
        holdout_periods = 4
    else:
        holdout_periods = 2
    holdout = _holdout_audit(candidates, selected_id=selected_id, holdout_periods=holdout_periods)
    verdict = _verdict(candidates=candidates, selected=selected, split_audit=split, holdout_audit=holdout, args=args)

    generated_at = datetime.now(UTC)
    report = {
        "schema_version": "rotation_anti_overfit_audit_v1",
        "generated_at": generated_at.isoformat(),
        "authority": "research_only_no_live_authority_change",
        "input": {
            "report_count": len(args.reports),
            "loaded_candidate_count": len(candidates),
            "min_scenarios": int(args.min_scenarios),
            "period": str(args.period),
            "max_splits": int(args.max_splits),
            "sample_seed": int(args.sample_seed),
            "holdout_periods": int(holdout_periods),
            "selected_report": selected_id,
            "selected_model_id": str(args.selected_model_id or ""),
            "include_model_regex": str(args.include_model_regex or ""),
            "exclude_model_regex": str(args.exclude_model_regex or ""),
        },
        "verdict": verdict,
        "selected_candidate": selected,
        "top_candidates": candidates[:20],
        "split_audit": split,
        "holdout_audit": holdout,
    }

    print(
        json.dumps(
            {
                "verdict": verdict["level"],
                "issues": verdict["issues"],
                "loaded_candidate_count": len(candidates),
                "pbo_proxy": split.get("pbo_proxy"),
                "selected_holdout_rank_pct": holdout.get("selected_test_rank_pct"),
                "top_candidate": candidates[0]["name"] if candidates else None,
            },
            ensure_ascii=False,
        )
    )
    if args.write_report:
        report_dir = ROOT_DIR / str(args.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        path = report_dir / f"rotation_anti_overfit_audit_{generated_at.strftime('%Y%m%dT%H%M%SZ')}.json"
        atomic_write_text(path, json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True))
        atomic_write_text(report_dir / "latest.json", json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True))
        print(json.dumps({"report_path": _relpath(path), "latest_report_path": _relpath(report_dir / "latest.json")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
