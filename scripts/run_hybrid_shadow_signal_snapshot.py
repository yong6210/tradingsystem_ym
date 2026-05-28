#!/usr/bin/env python3
from __future__ import annotations

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


def _current_period_key(period: str, ts: datetime) -> str:
    if period == "year":
        return str(ts.year)
    if period == "quarter":
        return f"{ts.year}Q{((ts.month - 1) // 3) + 1}"
    return f"{ts.year}-{ts.month:02d}"


def _find_candidate(candidates: list[dict[str, Any]], model_id: str) -> dict[str, Any] | None:
    needle = model_id.strip()
    if not needle:
        return None
    for candidate in candidates:
        summary = dict(candidate.get("summary") or {})
        candidate_id = str(candidate.get("candidate_id") or "")
        if needle == str(summary.get("model_id") or "") or needle == candidate_id or needle in candidate_id:
            return candidate
    return None


def _select_causal_current_candidate(candidates: list[dict[str, Any]], args: Any) -> tuple[dict[str, Any], list[str], float]:
    returns_by_candidate = wfbar._candidate_period_returns(candidates, str(args.period))
    periods = sorted({period for returns in returns_by_candidate.values() for period in returns})
    if len(periods) <= int(args.min_train_periods):
        raise SystemExit(f"too few periods for current selection: {len(periods)}")
    current_key = _current_period_key(str(args.period), datetime.now(UTC))
    train_periods = [period for period in periods if period < current_key]
    if len(train_periods) < int(args.min_train_periods):
        train_periods = periods[:-1]
    candidate_id, score = wfbar._select_candidate(
        candidate_returns=returns_by_candidate,
        train_periods=train_periods,
        test_period=current_key if current_key in periods else periods[-1],
        args=args,
    )
    if candidate_id is None or score is None:
        raise SystemExit("no eligible current candidate")
    for candidate in candidates:
        if str(candidate.get("candidate_id") or "") == candidate_id:
            return candidate, train_periods, float(score)
    raise SystemExit(f"selected candidate not found: {candidate_id}")


def main() -> int:
    args = wfbar._parse_args()
    candidates = wf._load_candidates(
        [str(path) for path in args.reports],
        max_full_sample_dd_pct=float(args.max_full_sample_dd_pct),
    )
    selected = _find_candidate(candidates, str(getattr(args, "model_id", "") or ""))
    train_periods: list[str] = []
    train_score = math.nan
    if selected is None:
        selected, train_periods, train_score = _select_causal_current_candidate(candidates, args)

    specs = wfbar._specs_from_candidate(selected, str(args.interval))
    frame, data_status, features, indicators, funding_period_rates = wfbar._load_market(args, specs)
    summary = hybrid._backtest_mix(
        frame,
        features,
        indicators,
        specs,
        args=args,
        funding_period_rates=funding_period_rates,
    )
    selected_summary = dict(selected.get("summary") or {})
    output: dict[str, Any] = {
        "schema_version": "hybrid_shadow_signal_snapshot_v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "authority": "research_only_no_order_authority",
        "orders_enabled": False,
        "live_trading_allowed": False,
        "input_reports": [str(path) for path in args.reports],
        "latest_bar_ts": frame.ts[-1].isoformat() if frame.ts else None,
        "data_status": data_status,
        "selection": {
            "selected_candidate_id": str(selected.get("candidate_id") or ""),
            "selected_model_id": selected_summary.get("model_id"),
            "selection_mode": "explicit_model_id" if str(getattr(args, "model_id", "") or "") else "causal_current_selector",
            "train_periods": train_periods,
            "train_score": round(train_score, 8) if math.isfinite(train_score) else None,
        },
        "cost_model": {
            "fee_bps_per_side": float(args.fee_bps_per_side),
            "slippage_bps_per_side": float(args.slippage_bps_per_side),
            "min_rebalance_turnover": float(args.min_rebalance_turnover),
            "rebalance_fill_fraction": float(args.rebalance_fill_fraction),
            "vol_target_annual_pct": float(args.vol_target_annual_pct),
            "vol_target_mode": str(args.vol_target_mode),
            "max_symbol_weight": float(args.max_symbol_weight),
            "market_gate_mode": str(args.market_gate_mode),
            "market_gate_risk_scale": float(args.market_gate_risk_scale),
        },
        "shadow_target": {
            "final_gross_exposure": summary.get("final_gross_exposure"),
            "final_net_exposure": summary.get("final_net_exposure"),
            "final_short_exposure": summary.get("final_short_exposure"),
            "final_top_weights": summary.get("final_top_weights"),
        },
        "backtest_context": {
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
    }
    if bool(args.write_report):
        report_dir = ROOT_DIR / str(args.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        out_path = report_dir / f"hybrid_shadow_signal_snapshot_{stamp}.json"
        latest_path = report_dir / "latest.json"
        output["report_path"] = str(out_path.relative_to(ROOT_DIR))
        output["latest_report_path"] = str(latest_path.relative_to(ROOT_DIR))
        text = json.dumps(output, ensure_ascii=False, indent=2, default=str)
        atomic_write_text(out_path, text)
        atomic_write_text(latest_path, text)
    print(json.dumps(output, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
