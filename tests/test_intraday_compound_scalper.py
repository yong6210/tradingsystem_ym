from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.services.intraday_compound_scalper import (
    IntradayCompoundScalper,
    IntradayScalpConfig,
    build_intraday_scalp_configs,
    intraday_scalp_decision,
    summarize_intraday_scalp_trades,
)
from scripts import run_intraday_compound_scalper_backtest as runner


@dataclass(frozen=True, slots=True)
class Bar:
    ts: datetime
    o: float
    h: float
    l: float
    c: float
    v: float


def _trend_bars(*, direction: str, count: int = 90) -> list[Bar]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    price = 100.0
    rows: list[Bar] = []
    step = 0.18 if direction == "long" else -0.18
    for idx in range(count):
        open_ = price
        close = price + step
        high = max(open_, close) + 0.08
        low = min(open_, close) - 0.08
        if idx % 12 == 0 and idx > 10:
            close = price + step * 3.0
            high = max(open_, close) + 0.20
            low = min(open_, close) - 0.05
        volume = 2_000.0 if idx % 12 == 0 and idx > 10 else 1_000.0
        rows.append(
            Bar(
                ts=start + timedelta(minutes=15 * idx),
                o=open_,
                h=high,
                l=low,
                c=close,
                v=volume,
            )
        )
        price = close
    return rows


def _test_config(**overrides: object) -> IntradayScalpConfig:
    values = {
        "model_id": "15m:test_intraday_compound_scalper",
        "interval": "15m",
        "fast_ema": 3,
        "slow_ema": 8,
        "trend_slope_lookback": 2,
        "breakout_lookback": 5,
        "swing_lookback": 3,
        "volume_lookback": 5,
        "atr_period": 3,
        "min_trend_atr": 0.05,
        "min_slow_slope_atr": 0.0,
        "min_volume_factor": 0.50,
        "min_body_atr": 0.10,
        "pullback_min_body_atr": 0.08,
        "stop_atr": 0.80,
        "target_rr": 0.80,
        "max_hold_bars": 8,
        "cooldown_bars": 1,
    }
    values.update(overrides)
    return IntradayScalpConfig(**values)


def test_intraday_compound_scalper_generates_long_trades() -> None:
    engine = IntradayCompoundScalper(
        symbol="BTCUSDT",
        bars=_trend_bars(direction="long"),
        config=_test_config(),
        fee_bps_per_side=0.0,
        slippage_bps_per_side=0.0,
    )

    trades = engine.backtest()

    assert trades
    assert {trade.direction for trade in trades} == {"long"}
    assert any(trade.exit_reason == "target" for trade in trades)
    summary = summarize_intraday_scalp_trades(trades)
    assert summary["closed"] == len(trades)
    assert summary["by_direction"]["long"]["closed"] == len(trades)


def test_intraday_compound_scalper_generates_short_trades() -> None:
    engine = IntradayCompoundScalper(
        symbol="BTCUSDT",
        bars=_trend_bars(direction="short"),
        config=_test_config(),
        fee_bps_per_side=0.0,
        slippage_bps_per_side=0.0,
    )

    trades = engine.backtest()

    assert trades
    assert {trade.direction for trade in trades} == {"short"}
    assert any(trade.exit_reason == "target" for trade in trades)


def test_intraday_scalp_decision_rejects_thin_sample() -> None:
    assert intraday_scalp_decision({"closed": 3, "ev_r": 1.0, "total_r": 3.0}, min_trades=20) == "INSUFFICIENT_SAMPLE"


def test_intraday_compound_scalper_runner_uses_research_only_contract(monkeypatch) -> None:
    bars = _trend_bars(direction="long", count=80)
    monkeypatch.setattr(runner, "_load_bars", lambda **_kwargs: bars)
    monkeypatch.setattr(runner, "build_intraday_scalp_configs", lambda _intervals: [_test_config()])

    payload = runner.run_backtest(
        SimpleNamespace(
            symbols="BTCUSDT",
            days=30,
            intervals="15m",
            fee_bps_per_side=0.0,
            slippage_bps_per_side=0.0,
            min_trades=1,
            max_models=1,
            include_trades=False,
            write_report=False,
            cache_dir="unused",
            report_dir="unused",
            base_url="",
            sleep_seconds=0.0,
        )
    )

    assert payload["authority"] == "research_only_no_live_authority_change"
    assert payload["strategy_family"]["name"] == "intraday_compound_scalper"
    assert payload["top"]
    assert payload["top"][0]["summary"]["closed"] > 0


def test_intraday_scalp_config_builder_is_limited_to_15m_30m() -> None:
    configs = build_intraday_scalp_configs(["5m", "15m", "30m", "1h"])
    assert configs
    assert {config.interval for config in configs} == {"15m", "30m"}
