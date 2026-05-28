#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.report_io import atomic_write_text
from scripts import analyze_multi_asset_rotation_walkforward as wf
from scripts import run_hybrid_strategy_mix_search as hybrid
from scripts import run_hybrid_walkforward_bar_resim as wfbar


def _select_holdout_candidate(
    *,
    returns_by_candidate: dict[str, dict[str, float]],
    train_periods: list[str],
    first_test_period: str,
    args: argparse.Namespace,
) -> tuple[str, float]:
    ranked: list[tuple[float, str]] = []
    for candidate_id, returns in returns_by_candidate.items():
        if first_test_period not in returns:
            continue
        score = wf._train_score(
            returns,
            train_periods,
            max_train_worst_year_pct=float(args.max_train_worst_year_pct),
            max_train_period_dd_pct=float(args.max_train_period_dd_pct),
            min_train_positive_fraction=float(args.min_train_positive_fraction),
            selector_mode=str(args.selector_mode),
        )
        if math.isfinite(score):
            ranked.append((score, candidate_id))
    if not ranked:
        raise SystemExit("no eligible candidate for holdout selection")
    return max(ranked, key=lambda item: item[0])


def main() -> int:
    args = wfbar._parse_args()
    candidates = wf._load_candidates(
        [str(path) for path in args.reports],
        max_full_sample_dd_pct=float(args.max_full_sample_dd_pct),
    )
    candidate_by_id = {str(row["candidate_id"]): row for row in candidates}
    returns_by_candidate = wfbar._candidate_period_returns(candidates, str(args.period))
    periods = sorted({period for returns in returns_by_candidate.values() for period in returns})
    min_train = int(args.min_train_periods)
    if len(periods) <= min_train:
        raise SystemExit(f"too few periods for holdout: {len(periods)}")

    train_periods = periods[:min_train]
    test_periods = periods[min_train:]
    if str(args.model_id or "").strip():
        selected = wfbar._find_candidate(candidates, str(args.model_id))
        if selected is None:
            raise SystemExit(f"fixed model not found: {args.model_id}")
        selected_id = str(selected.get("candidate_id") or "")
        selected_returns = returns_by_candidate.get(selected_id, {})
        score = wf._train_score(
            selected_returns,
            train_periods,
            max_train_worst_year_pct=float(args.max_train_worst_year_pct),
            max_train_period_dd_pct=float(args.max_train_period_dd_pct),
            min_train_positive_fraction=float(args.min_train_positive_fraction),
            selector_mode=str(args.selector_mode),
        )
    else:
        score, selected_id = _select_holdout_candidate(
            returns_by_candidate=returns_by_candidate,
            train_periods=train_periods,
            first_test_period=test_periods[0],
            args=args,
        )
    selected = candidate_by_id[selected_id]
    specs = wfbar._specs_from_candidate(selected, str(args.interval))

    frame, data_status, features, indicators, funding_period_rates = wfbar._load_market(args, specs)
    period_args = argparse.Namespace(**vars(args))
    period_args.evaluation_start = wfbar._period_start(str(args.period), test_periods[0]).isoformat()
    period_args.evaluation_end = wfbar._period_end(str(args.period), test_periods[-1]).isoformat()
    summary = hybrid._backtest_mix(
        frame,
        features,
        indicators,
        specs,
        args=period_args,
        funding_period_rates=funding_period_rates,
    )

    output: dict[str, Any] = {
        "schema_version": "hybrid_holdout_bar_resim_v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "authority": "research_only_no_live_authority_change",
        "input_reports": [str(path) for path in args.reports],
        "candidate_count": len(candidates),
        "data_status": data_status,
        "method": {
            "selector": "one-time causal holdout selection using only the initial train periods",
            "fixed_model_id": str(args.model_id or ""),
            "period": str(args.period),
            "selector_mode": str(args.selector_mode),
            "limitations": [
                "selection is still based on the candidate family supplied in the report",
                "does not place orders and has no live authority",
            ],
        },
        "selection": {
            "selected_candidate_id": selected_id,
            "selected_model_id": dict(selected.get("summary") or {}).get("model_id"),
            "train_score": round(float(score), 8),
            "train_periods": train_periods,
            "test_periods": test_periods,
            "test_start": period_args.evaluation_start,
            "test_end": period_args.evaluation_end,
        },
        "cost_model": {
            key: getattr(args, key)
            for key in (
                "fee_bps_per_side",
                "slippage_bps_per_side",
                "holding_cost_bps_per_day",
                "short_cost_bps_per_day",
                "drawdown_guard_pct",
                "drawdown_risk_scale",
                "drawdown_ladder",
                "vol_target_annual_pct",
                "vol_target_mode",
                "vol_lookback_hours",
                "vol_min_scale",
                "vol_max_scale",
                "max_symbol_weight",
                "min_rebalance_turnover",
                "rebalance_fill_fraction",
                "market_gate_mode",
                "market_gate_risk_scale",
            )
        },
        "summary": summary,
    }
    if bool(args.write_report):
        report_dir = ROOT_DIR / str(args.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        out_path = report_dir / f"hybrid_holdout_bar_resim_{stamp}.json"
        latest_path = report_dir / "latest.json"
        output["report_path"] = str(out_path.relative_to(ROOT_DIR))
        output["latest_report_path"] = str(latest_path.relative_to(ROOT_DIR))
        text = json.dumps(output, ensure_ascii=False, indent=2, default=str)
        atomic_write_text(out_path, text)
        atomic_write_text(latest_path, text)

    print(
        json.dumps(
            {
                "selection": output["selection"],
                "summary": {
                    key: summary.get(key)
                    for key in (
                        "total_return_pct",
                        "cagr_pct",
                        "max_drawdown_pct",
                        "calmar",
                        "worst_year_pct",
                        "positive_year_fraction",
                        "rebalance_count",
                    )
                },
                "report_dir": str(args.report_dir),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
