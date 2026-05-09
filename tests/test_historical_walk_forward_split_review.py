from __future__ import annotations

import json
from pathlib import Path

from app.services.historical_walk_forward_split_review import HistoricalWalkForwardSplitReviewService


def _row(
    *,
    symbol: str,
    family: str,
    direction: str,
    entry_model: str,
    exit_reason: str,
    realized_r: float,
    generated_ts: str,
    closed_ts: str,
    held_bars: int,
) -> dict[str, object]:
    return {
        "symbol": symbol,
        "strategy_family": family,
        "direction": direction,
        "entry_model": entry_model,
        "final_exit_reason": exit_reason,
        "replayed_realized_r": realized_r,
        "generated_ts": generated_ts,
        "closed_ts": closed_ts,
        "final_exit_held_bars": held_bars,
    }


def test_split_review_summarizes_breakdowns_and_headline() -> None:
    service = HistoricalWalkForwardSplitReviewService()
    payload = {
        "contract_scope": "historical_walk_forward_strategy_level",
        "source_mode": "raw_candle_heuristic",
        "eligible_symbols": ["BTCUSDC"],
        "eligible_families": ["sweep_reversal"],
        "eligible_entry_models": ["LIMIT"],
        "simulation_start_ts": "2026-01-01T00:00:00+00:00",
        "simulation_end_ts": "2026-02-01T00:00:00+00:00",
        "symbol_summaries": [{"symbol": "BTCUSDC", "closed_trade_count": 4}],
        "trade_rows": [
            _row(
                symbol="BTCUSDC",
                family="sweep_reversal",
                direction="long",
                entry_model="LIMIT",
                exit_reason="target_tp3",
                realized_r=2.0,
                generated_ts="2026-01-03T08:00:00+00:00",
                closed_ts="2026-01-03T08:20:00+00:00",
                held_bars=4,
            ),
            _row(
                symbol="BTCUSDC",
                family="sweep_reversal",
                direction="short",
                entry_model="LIMIT",
                exit_reason="stop_loss",
                realized_r=-1.0,
                generated_ts="2026-01-10T14:00:00+00:00",
                closed_ts="2026-01-10T14:15:00+00:00",
                held_bars=3,
            ),
            _row(
                symbol="BTCUSDC",
                family="sweep_reversal",
                direction="short",
                entry_model="SWEEP_CONFIRM",
                exit_reason="session_end_flatten",
                realized_r=1.1,
                generated_ts="2026-01-14T15:00:00+00:00",
                closed_ts="2026-01-14T16:00:00+00:00",
                held_bars=5,
            ),
            _row(
                symbol="BTCUSDC",
                family="sweep_reversal",
                direction="long",
                entry_model="LIMIT",
                exit_reason="stop_loss",
                realized_r=-1.0,
                generated_ts="2026-01-21T02:00:00+00:00",
                closed_ts="2026-01-21T02:10:00+00:00",
                held_bars=2,
            ),
        ],
    }

    review = service.summarize_payload(payload=payload, review_name="unit_case", write_report=False)

    assert review["overall"]["trades"] == 4
    assert review["overall"]["win_rate"] == 0.5
    assert review["overall"]["ev_r"] == 0.275
    assert review["overall"]["stop_loss_share"] == 0.5
    assert review["breakdowns"]["direction"][0]["key"] in {"LONG", "SHORT"}
    assert review["breakdowns"]["entry_model"][0]["key"] == "LIMIT"
    assert review["breakdowns"]["generated_month_recent"][-1]["key"] == "2026-01"


def test_split_review_writes_markdown_report(tmp_path: Path) -> None:
    service = HistoricalWalkForwardSplitReviewService()
    service.settings.validation_report_dir = str(tmp_path)
    payload = {
        "contract_scope": "historical_walk_forward_strategy_level",
        "source_mode": "raw_candle_heuristic",
        "eligible_symbols": ["BTCUSDC"],
        "eligible_families": ["sweep_reversal"],
        "eligible_entry_models": ["LIMIT"],
        "simulation_start_ts": "2026-01-01T00:00:00+00:00",
        "simulation_end_ts": "2026-02-01T00:00:00+00:00",
        "symbol_summaries": [],
        "trade_rows": [
            _row(
                symbol="BTCUSDC",
                family="sweep_reversal",
                direction="long",
                entry_model="LIMIT",
                exit_reason="target_tp3",
                realized_r=2.0,
                generated_ts="2026-01-03T08:00:00+00:00",
                closed_ts="2026-01-03T08:20:00+00:00",
                held_bars=4,
            )
        ],
    }

    review = service.summarize_payload(payload=payload, review_name="write_case", write_report=True)

    report_path = Path(str(review["report_path"]))
    assert report_path.exists()
    body = report_path.read_text(encoding="utf-8")
    assert "## Symbol Breakdown" in body
    assert "## Family Breakdown" in body
    assert "## Direction Breakdown" in body
    assert "## Entry Model Breakdown" in body


def test_split_review_filters_by_allowed_sessions_and_blocked_hours() -> None:
    service = HistoricalWalkForwardSplitReviewService()
    payload = {
        "contract_scope": "historical_walk_forward_strategy_level",
        "source_mode": "raw_candle_heuristic",
        "eligible_symbols": ["BTCUSDC"],
        "eligible_families": ["sweep_reversal"],
        "eligible_entry_models": ["LIMIT"],
        "simulation_start_ts": "2026-01-01T00:00:00+00:00",
        "simulation_end_ts": "2026-02-01T00:00:00+00:00",
        "symbol_summaries": [{"symbol": "BTCUSDC", "closed_trade_count": 3}],
        "trade_rows": [
            _row(
                symbol="BTCUSDC",
                family="sweep_reversal",
                direction="long",
                entry_model="LIMIT",
                exit_reason="target_tp3",
                realized_r=1.9,
                generated_ts="2026-01-03T08:00:00+00:00",
                closed_ts="2026-01-03T08:20:00+00:00",
                held_bars=4,
            ),
            _row(
                symbol="BTCUSDC",
                family="sweep_reversal",
                direction="long",
                entry_model="LIMIT",
                exit_reason="stop_loss",
                realized_r=-1.0,
                generated_ts="2026-01-03T14:00:00+00:00",
                closed_ts="2026-01-03T14:20:00+00:00",
                held_bars=4,
            ),
            _row(
                symbol="BTCUSDC",
                family="sweep_reversal",
                direction="long",
                entry_model="LIMIT",
                exit_reason="target_tp3",
                realized_r=1.9,
                generated_ts="2026-01-03T17:00:00+00:00",
                closed_ts="2026-01-03T17:20:00+00:00",
                held_bars=4,
            ),
        ],
    }

    filtered = service.filter_payload(
        payload=payload,
        allowed_sessions=("london", "new_york"),
        blocked_session_direction_hours_utc="BTCUSDC:new_york:LONG:14|15|16",
    )

    assert len(filtered["trade_rows"]) == 2
    assert [row["generated_hour_utc"] for row in filtered["trade_rows"]] == [8, 17]
    assert filtered["symbol_summaries"][0]["closed_trade_count"] == 2


def test_split_review_filters_by_strategy_hour_contract() -> None:
    service = HistoricalWalkForwardSplitReviewService()
    payload = {
        "contract_scope": "historical_walk_forward_strategy_level",
        "source_mode": "raw_candle_heuristic",
        "eligible_symbols": ["BTCUSDC"],
        "eligible_families": ["sweep_reversal"],
        "eligible_entry_models": ["SWEEP_CONFIRM"],
        "simulation_start_ts": "2026-01-01T00:00:00+00:00",
        "simulation_end_ts": "2026-02-01T00:00:00+00:00",
        "symbol_summaries": [{"symbol": "BTCUSDC", "closed_trade_count": 3}],
        "trade_rows": [
            _row(
                symbol="BTCUSDC",
                family="sweep_reversal",
                direction="long",
                entry_model="SWEEP_CONFIRM",
                exit_reason="target_tp3",
                realized_r=1.9,
                generated_ts="2026-01-03T08:00:00+00:00",
                closed_ts="2026-01-03T08:20:00+00:00",
                held_bars=4,
            ),
            _row(
                symbol="BTCUSDC",
                family="sweep_reversal",
                direction="long",
                entry_model="SWEEP_CONFIRM",
                exit_reason="stop_loss",
                realized_r=-1.0,
                generated_ts="2026-01-03T10:00:00+00:00",
                closed_ts="2026-01-03T10:20:00+00:00",
                held_bars=4,
            ),
            _row(
                symbol="BTCUSDC",
                family="sweep_reversal",
                direction="short",
                entry_model="SWEEP_CONFIRM",
                exit_reason="target_tp3",
                realized_r=1.9,
                generated_ts="2026-01-03T10:00:00+00:00",
                closed_ts="2026-01-03T10:20:00+00:00",
                held_bars=4,
            ),
        ],
    }

    filtered = service.filter_payload(
        payload=payload,
        blocked_symbol_family_entry_direction_hours_utc="BTCUSDC:sweep_reversal:SWEEP_CONFIRM:LONG:10",
    )

    assert len(filtered["trade_rows"]) == 2
    assert [row["generated_hour_utc"] for row in filtered["trade_rows"]] == [8, 10]
    assert filtered["symbol_summaries"][0]["closed_trade_count"] == 2
    assert filtered["applied_filters"]["blocked_symbol_family_entry_direction_hours_utc"] == (
        "BTCUSDC:sweep_reversal:SWEEP_CONFIRM:LONG:10"
    )


def test_split_review_filters_by_strategy_time_contract_file(tmp_path: Path) -> None:
    contract_path = tmp_path / "strategy_time_contract.json"
    contract_path.write_text(
        json.dumps(
            {
                "blocked_buckets": [
                    {
                        "symbol": "BTCUSDC",
                        "strategy_family": "sweep_reversal",
                        "entry_model": "SWEEP_CONFIRM",
                        "direction": "LONG",
                        "weekday_utc": 5,
                        "hour_utc": 10,
                        "minute_utc": 0,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    service = HistoricalWalkForwardSplitReviewService()
    payload = {
        "contract_scope": "historical_walk_forward_strategy_level",
        "source_mode": "raw_candle_heuristic",
        "eligible_symbols": ["BTCUSDC"],
        "eligible_families": ["sweep_reversal"],
        "eligible_entry_models": ["SWEEP_CONFIRM"],
        "simulation_start_ts": "2026-01-01T00:00:00+00:00",
        "simulation_end_ts": "2026-02-01T00:00:00+00:00",
        "symbol_summaries": [{"symbol": "BTCUSDC", "closed_trade_count": 3}],
        "trade_rows": [
            _row(
                symbol="BTCUSDC",
                family="sweep_reversal",
                direction="long",
                entry_model="SWEEP_CONFIRM",
                exit_reason="target_tp3",
                realized_r=1.9,
                generated_ts="2026-01-03T08:00:00+00:00",
                closed_ts="2026-01-03T08:20:00+00:00",
                held_bars=4,
            ),
            _row(
                symbol="BTCUSDC",
                family="sweep_reversal",
                direction="long",
                entry_model="SWEEP_CONFIRM",
                exit_reason="stop_loss",
                realized_r=-1.0,
                generated_ts="2026-01-03T10:00:00+00:00",
                closed_ts="2026-01-03T10:20:00+00:00",
                held_bars=4,
            ),
            _row(
                symbol="BTCUSDC",
                family="sweep_reversal",
                direction="short",
                entry_model="SWEEP_CONFIRM",
                exit_reason="target_tp3",
                realized_r=1.9,
                generated_ts="2026-01-03T10:00:00+00:00",
                closed_ts="2026-01-03T10:20:00+00:00",
                held_bars=4,
            ),
        ],
    }

    filtered = service.filter_payload(
        payload=payload,
        blocked_strategy_time_contract_path=str(contract_path),
    )

    assert len(filtered["trade_rows"]) == 2
    assert [row["generated_hour_utc"] for row in filtered["trade_rows"]] == [8, 10]
    assert filtered["symbol_summaries"][0]["closed_trade_count"] == 2
    assert filtered["applied_filters"]["blocked_strategy_time_contract_path"] == str(contract_path)


def test_split_review_filters_by_plan_blocklist_file(tmp_path: Path) -> None:
    blocklist_path = tmp_path / "plan_blocklist.json"
    blocklist_path.write_text(
        json.dumps({"blocked_plan_ids": ["drop_me"]}),
        encoding="utf-8",
    )
    service = HistoricalWalkForwardSplitReviewService()
    payload = {
        "contract_scope": "historical_walk_forward_strategy_level",
        "source_mode": "raw_candle_heuristic",
        "eligible_symbols": ["BTCUSDC"],
        "eligible_families": ["sweep_reversal"],
        "eligible_entry_models": ["SWEEP_CONFIRM"],
        "simulation_start_ts": "2026-01-01T00:00:00+00:00",
        "simulation_end_ts": "2026-02-01T00:00:00+00:00",
        "symbol_summaries": [{"symbol": "BTCUSDC", "closed_trade_count": 2}],
        "trade_rows": [
            {
                **_row(
                    symbol="BTCUSDC",
                    family="sweep_reversal",
                    direction="long",
                    entry_model="SWEEP_CONFIRM",
                    exit_reason="target_tp3",
                    realized_r=1.9,
                    generated_ts="2026-01-03T08:00:00+00:00",
                    closed_ts="2026-01-03T08:20:00+00:00",
                    held_bars=4,
                ),
                "plan_id": "keep_me",
            },
            {
                **_row(
                    symbol="BTCUSDC",
                    family="sweep_reversal",
                    direction="long",
                    entry_model="SWEEP_CONFIRM",
                    exit_reason="structure_failure",
                    realized_r=0.0,
                    generated_ts="2026-01-03T10:00:00+00:00",
                    closed_ts="2026-01-03T10:20:00+00:00",
                    held_bars=4,
                ),
                "plan_id": "drop_me",
            },
        ],
    }

    filtered = service.filter_payload(
        payload=payload,
        blocked_plan_ids_path=str(blocklist_path),
    )

    assert len(filtered["trade_rows"]) == 1
    assert filtered["trade_rows"][0]["plan_id"] == "keep_me"
    assert filtered["symbol_summaries"][0]["closed_trade_count"] == 1
    assert filtered["applied_filters"]["blocked_plan_ids_path"] == str(blocklist_path)
