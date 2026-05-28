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


def _train_score_for_candidate(candidate: dict[str, Any], train_periods: list[str], args: argparse.Namespace) -> float:
    returns = wfbar._candidate_period_returns([candidate], str(args.period)).get(str(candidate.get("candidate_id")), {})
    return wf._train_score(
        returns,
        train_periods,
        max_train_worst_year_pct=float(args.max_train_worst_year_pct),
        max_train_period_dd_pct=float(args.max_train_period_dd_pct),
        min_train_positive_fraction=float(args.min_train_positive_fraction),
        selector_mode=str(args.selector_mode),
    )


def _rank(rows: list[dict[str, Any]], key: str, limit: int = 12) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            float(dict(row.get("summary") or {}).get(key, -1e18) or -1e18),
            float(dict(row.get("summary") or {}).get("calmar", -1e18) or -1e18),
        ),
        reverse=True,
    )[:limit]


def main() -> int:
    args = wfbar._parse_args()
    candidates = wf._load_candidates(
        [str(path) for path in args.reports],
        max_full_sample_dd_pct=float(args.max_full_sample_dd_pct),
    )
    returns_by_candidate = wfbar._candidate_period_returns(candidates, str(args.period))
    periods = sorted({period for returns in returns_by_candidate.values() for period in returns})
    min_train = int(args.min_train_periods)
    if len(periods) <= min_train:
        raise SystemExit(f"too few periods for holdout scan: {len(periods)}")
    train_periods = periods[:min_train]
    test_periods = periods[min_train:]

    scored_candidates: list[tuple[float, dict[str, Any]]] = []
    for candidate in candidates:
        candidate_id = str(candidate.get("candidate_id") or "")
        if not candidate_id or test_periods[0] not in returns_by_candidate.get(candidate_id, {}):
            continue
        train_score = _train_score_for_candidate(candidate, train_periods, args)
        if not math.isfinite(train_score):
            continue
        scored_candidates.append((train_score, candidate))
    scored_candidates.sort(key=lambda item: item[0], reverse=True)
    if int(getattr(args, "preselect_top", 0) or 0) > 0:
        scored_candidates = scored_candidates[: int(args.preselect_top)]

    specs_by_candidate_id: dict[str, list[hybrid.SleeveSpec]] = {
        str(candidate.get("candidate_id") or ""): wfbar._specs_from_candidate(candidate, str(args.interval))
        for _, candidate in scored_candidates
    }
    all_specs = [spec for specs in specs_by_candidate_id.values() for spec in specs]
    frame, data_status, features, indicators, funding_period_rates = wfbar._load_market(args, all_specs)
    period_args = argparse.Namespace(**vars(args))
    period_args.evaluation_start = wfbar._period_start(str(args.period), test_periods[0]).isoformat()
    period_args.evaluation_end = wfbar._period_end(str(args.period), test_periods[-1]).isoformat()

    rows: list[dict[str, Any]] = []
    for train_score, candidate in scored_candidates:
        candidate_id = str(candidate.get("candidate_id") or "")
        specs = specs_by_candidate_id[candidate_id]
        summary = hybrid._backtest_mix(
            frame,
            features,
            indicators,
            specs,
            args=period_args,
            funding_period_rates=funding_period_rates,
        )
        rows.append(
            {
                "candidate_id": candidate_id,
                "model_id": dict(candidate.get("summary") or {}).get("model_id"),
                "train_score": round(float(train_score), 8),
                "config": dict(candidate.get("config") or {}),
                "summary": summary,
            }
        )

    output: dict[str, Any] = {
        "schema_version": "hybrid_holdout_candidate_scan_v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "authority": "research_only_no_live_authority_change",
        "input_reports": [str(path) for path in args.reports],
        "candidate_count": len(candidates),
        "evaluated_candidate_count": len(rows),
        "preselected_candidate_count": len(scored_candidates),
        "data_status": data_status,
        "method": {
            "period": str(args.period),
            "selector_mode_for_train_rank": str(args.selector_mode),
            "train_periods": train_periods,
            "test_periods": test_periods,
            "test_start": period_args.evaluation_start,
            "test_end": period_args.evaluation_end,
            "warning": "top_by_oos_* is a diagnostic ranking that uses the holdout result and is not a live promotion rule",
            "preselect_top": int(getattr(args, "preselect_top", 0) or 0),
        },
        "cost_model": {
            key: getattr(args, key)
            for key in (
                "fee_bps_per_side",
                "slippage_bps_per_side",
                "drawdown_guard_pct",
                "drawdown_risk_scale",
                "drawdown_ladder",
                "vol_target_annual_pct",
                "vol_target_mode",
                "market_gate_mode",
                "market_gate_risk_scale",
            )
        },
        "selected_by_train": sorted(rows, key=lambda row: float(row["train_score"]), reverse=True)[:5],
        "top_by_oos_return": _rank(rows, "total_return_pct"),
        "top_by_oos_calmar": _rank(rows, "calmar"),
        "all_results": rows,
    }
    if bool(args.write_report):
        report_dir = ROOT_DIR / str(args.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        out_path = report_dir / f"hybrid_holdout_candidate_scan_{stamp}.json"
        latest_path = report_dir / "latest.json"
        output["report_path"] = str(out_path.relative_to(ROOT_DIR))
        output["latest_report_path"] = str(latest_path.relative_to(ROOT_DIR))
        text = json.dumps(output, ensure_ascii=False, indent=2, default=str)
        atomic_write_text(out_path, text)
        atomic_write_text(latest_path, text)

    print(
        json.dumps(
            {
                "evaluated_candidate_count": len(rows),
                "top_by_oos_return": [
                    {
                        "model_id": row["model_id"],
                        "train_score": row["train_score"],
                        "total_return_pct": row["summary"].get("total_return_pct"),
                        "cagr_pct": row["summary"].get("cagr_pct"),
                        "max_drawdown_pct": row["summary"].get("max_drawdown_pct"),
                        "calmar": row["summary"].get("calmar"),
                    }
                    for row in output["top_by_oos_return"][:5]
                ],
                "report_dir": str(args.report_dir),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
