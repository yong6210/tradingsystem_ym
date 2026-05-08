#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
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


def _csv_items(raw: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in str(raw or "").split(",") if item.strip())


def _preset_config(name: str) -> dict[str, Any]:
    settings = get_settings()
    live_symbols = tuple(
        item.strip().upper()
        for item in str(getattr(settings, "auto_trading_micro_live_allowed_symbols", "") or "").split(",")
        if item.strip()
    ) or ("BTCUSDC",)
    live_families = tuple(
        item.strip().lower()
        for item in str(getattr(settings, "auto_trading_micro_live_allowed_families", "") or "").split(",")
        if item.strip()
    ) or ("sweep_reversal",)
    live_entry_models = tuple(
        item.strip().upper()
        for item in str(getattr(settings, "auto_trading_micro_live_allowed_entry_models", "") or "").split(",")
        if item.strip()
    ) or ("LIMIT",)
    live_sessions = tuple(
        item.strip().lower()
        for item in str(getattr(settings, "auto_trading_micro_live_allowed_sessions", "") or "").split(",")
        if item.strip()
    )
    blocked_session_direction_hours_utc = str(
        getattr(settings, "auto_trading_micro_live_session_direction_blocked_hours_utc", "") or ""
    )
    blocked_symbol_family_entry_direction_hours_utc = str(
        getattr(settings, "auto_trading_micro_live_symbol_family_entry_direction_blocked_hours_utc", "") or ""
    )
    blocked_strategy_time_contract_path = str(
        getattr(settings, "auto_trading_micro_live_strategy_time_contract_path", "") or ""
    )
    blocked_plan_ids_path = str(
        getattr(settings, "auto_trading_micro_live_plan_blocklist_path", "") or ""
    )

    presets: dict[str, dict[str, Any]] = {
        "live_subset": {
            "review_name": "live_subset",
            "eligible_symbols": live_symbols,
            "eligible_families": live_families,
            "eligible_entry_models": live_entry_models,
            "contract_scope": "historical_walk_forward_strategy_level",
            "cache_key": "strategy_proof_contract_live_subset",
            "generate_on_new_15m_only": True,
            "independent_signal_mode": True,
            "max_candidates_per_bar": 1,
            "source_mode": "raw_candle_heuristic",
            "allowed_sessions": (),
            "blocked_session_direction_hours_utc": "",
            "blocked_symbol_family_entry_direction_hours_utc": "",
            "blocked_strategy_time_contract_path": "",
            "blocked_plan_ids_path": "",
        },
        "micro_live_baseline": {
            "review_name": "micro_live_baseline",
            "eligible_symbols": live_symbols,
            "eligible_families": live_families,
            "eligible_entry_models": live_entry_models,
            "contract_scope": "historical_walk_forward_strategy_level",
            "cache_key": "strategy_proof_contract_live_subset",
            "generate_on_new_15m_only": True,
            "independent_signal_mode": True,
            "max_candidates_per_bar": 1,
            "source_mode": "raw_candle_heuristic",
            "allowed_sessions": live_sessions,
            "blocked_session_direction_hours_utc": "",
            "blocked_symbol_family_entry_direction_hours_utc": "",
            "blocked_strategy_time_contract_path": "",
            "blocked_plan_ids_path": "",
        },
        "micro_live_contract": {
            "review_name": "micro_live_contract",
            "eligible_symbols": live_symbols,
            "eligible_families": live_families,
            "eligible_entry_models": live_entry_models,
            "contract_scope": "historical_walk_forward_strategy_level",
            "cache_key": "strategy_proof_contract_live_subset",
            "generate_on_new_15m_only": True,
            "independent_signal_mode": True,
            "max_candidates_per_bar": 1,
            "source_mode": "raw_candle_heuristic",
            "allowed_sessions": live_sessions,
            "blocked_session_direction_hours_utc": blocked_session_direction_hours_utc,
            "blocked_symbol_family_entry_direction_hours_utc": blocked_symbol_family_entry_direction_hours_utc,
            "blocked_strategy_time_contract_path": blocked_strategy_time_contract_path,
            "blocked_plan_ids_path": blocked_plan_ids_path,
        },
        "broad_strategy": {
            "review_name": "broad_strategy",
            "eligible_symbols": ("BTCUSDC", "ETHUSDC"),
            "eligible_families": ("sweep_reversal", "trend_continuation"),
            "eligible_entry_models": ("LIMIT", "SWEEP_CONFIRM", "CONFIRM"),
            "contract_scope": "historical_walk_forward_strategy_level",
            "cache_key": "strategy_proof_contract",
            "generate_on_new_15m_only": True,
            "independent_signal_mode": True,
            "max_candidates_per_bar": 1,
            "source_mode": "raw_candle_heuristic",
            "allowed_sessions": (),
            "blocked_session_direction_hours_utc": "",
            "blocked_symbol_family_entry_direction_hours_utc": "",
            "blocked_strategy_time_contract_path": "",
            "blocked_plan_ids_path": "",
        },
        "btc_broad_detail": {
            "review_name": "btc_broad_detail",
            "eligible_symbols": ("BTCUSDC",),
            "eligible_families": ("sweep_reversal", "trend_continuation"),
            "eligible_entry_models": ("LIMIT", "SWEEP_CONFIRM", "CONFIRM"),
            "contract_scope": "historical_walk_forward_strategy_level",
            "cache_key": "strategy_proof_contract_btc_broad_detail",
            "generate_on_new_15m_only": True,
            "independent_signal_mode": True,
            "max_candidates_per_bar": 1,
            "source_mode": "raw_candle_heuristic",
            "allowed_sessions": (),
            "blocked_session_direction_hours_utc": "",
            "blocked_symbol_family_entry_direction_hours_utc": "",
            "blocked_strategy_time_contract_path": "",
            "blocked_plan_ids_path": "",
        },
    }
    if name not in presets:
        raise ValueError(f"unknown preset: {name}")
    return dict(presets[name])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run split review for historical walk-forward replay evidence.")
    parser.add_argument(
        "--preset",
        choices=("live_subset", "micro_live_baseline", "micro_live_contract", "broad_strategy", "btc_broad_detail"),
        default="live_subset",
    )
    parser.add_argument("--symbols", default="")
    parser.add_argument("--families", default="")
    parser.add_argument("--entry-models", default="")
    parser.add_argument("--contract-scope", default="")
    parser.add_argument("--cache-key", default="")
    parser.add_argument("--source-mode", default="")
    parser.add_argument("--review-name", default="")
    parser.add_argument("--allowed-sessions", default="")
    parser.add_argument("--blocked-session-direction-hours-utc", default="")
    parser.add_argument("--blocked-symbol-family-entry-direction-hours-utc", default="")
    parser.add_argument("--blocked-strategy-time-contract-path", default="")
    parser.add_argument("--blocked-plan-ids-path", default="")
    parser.add_argument("--no-write-report", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    init_db()
    config = _preset_config(str(args.preset))
    if str(args.symbols).strip():
        config["eligible_symbols"] = tuple(item.upper() for item in _csv_items(args.symbols))
    if str(args.families).strip():
        config["eligible_families"] = tuple(item.lower() for item in _csv_items(args.families))
    if str(args.entry_models).strip():
        config["eligible_entry_models"] = tuple(item.upper() for item in _csv_items(args.entry_models))
    if str(args.contract_scope).strip():
        config["contract_scope"] = str(args.contract_scope).strip()
    if str(args.cache_key).strip():
        config["cache_key"] = str(args.cache_key).strip()
    if str(args.source_mode).strip():
        config["source_mode"] = str(args.source_mode).strip()
    if str(args.review_name).strip():
        config["review_name"] = str(args.review_name).strip()
    if str(args.allowed_sessions).strip():
        config["allowed_sessions"] = tuple(item.lower() for item in _csv_items(args.allowed_sessions))
    if str(args.blocked_session_direction_hours_utc).strip():
        config["blocked_session_direction_hours_utc"] = str(args.blocked_session_direction_hours_utc).strip()
    if str(args.blocked_symbol_family_entry_direction_hours_utc).strip():
        config["blocked_symbol_family_entry_direction_hours_utc"] = (
            str(args.blocked_symbol_family_entry_direction_hours_utc).strip()
        )
    if str(args.blocked_strategy_time_contract_path).strip():
        config["blocked_strategy_time_contract_path"] = str(args.blocked_strategy_time_contract_path).strip()
    if str(args.blocked_plan_ids_path).strip():
        config["blocked_plan_ids_path"] = str(args.blocked_plan_ids_path).strip()

    with SessionLocal() as db:
        proof = HistoricalWalkForwardProofService(candle_repo=CandleRepository(db), settings=get_settings())
        payload = proof.generate(
            eligible_symbols=tuple(config["eligible_symbols"]),
            eligible_families=tuple(config["eligible_families"]),
            eligible_entry_models=tuple(config["eligible_entry_models"]),
            contract_scope=str(config["contract_scope"]),
            cache_key=str(config["cache_key"]),
            generate_on_new_15m_only=bool(config["generate_on_new_15m_only"]),
            independent_signal_mode=bool(config["independent_signal_mode"]),
            max_candidates_per_bar=int(config["max_candidates_per_bar"]),
            source_mode=str(config["source_mode"]),
            blocked_strategy_time_contract_path=str(config["blocked_strategy_time_contract_path"]),
            blocked_plan_ids_path=str(config["blocked_plan_ids_path"]),
        )
        service = HistoricalWalkForwardSplitReviewService(settings=get_settings())
        payload = service.filter_payload(
            payload=payload,
            allowed_sessions=tuple(config.get("allowed_sessions") or ()),
            blocked_session_direction_hours_utc=str(config.get("blocked_session_direction_hours_utc") or ""),
            blocked_symbol_family_entry_direction_hours_utc=str(
                config.get("blocked_symbol_family_entry_direction_hours_utc") or ""
            ),
            blocked_strategy_time_contract_path=str(config.get("blocked_strategy_time_contract_path") or ""),
            blocked_plan_ids_path=str(config.get("blocked_plan_ids_path") or ""),
        )
        review = service.summarize_payload(
            payload=payload,
            review_name=str(config["review_name"]),
            write_report=not args.no_write_report,
        )

    print(json.dumps(review, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
