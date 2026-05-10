from datetime import UTC, datetime, timedelta

from app.db.models import Candle
from app.services.micro_main_strategy_research import (
    SessionImpulseRetestResearch,
    build_session_impulse_retest_shadow_summary,
    decision_for_micro_summary,
    session_impulse_retest_profile_for_symbol,
    summarize_micro_trades,
)


def _candles(symbol: str, timeframe: str, step_minutes: int, count: int, start: datetime) -> list[Candle]:
    rows: list[Candle] = []
    price = 100.0
    for idx in range(count):
        drift = 0.04 if idx < count // 2 else -0.01
        price += drift
        rows.append(
            Candle(
                symbol=symbol,
                timeframe=timeframe,
                ts=start + timedelta(minutes=step_minutes * idx),
                o=price,
                h=price + 0.3,
                l=price - 0.3,
                c=price + (0.05 if idx % 2 == 0 else -0.02),
                v=1000 + idx,
                source="test",
                is_final=True,
            )
        )
    return rows


def test_micro_main_strategy_summary_handles_empty_trades() -> None:
    summary = summarize_micro_trades([])
    assert summary["closed"] == 0
    assert summary["ev_r"] == 0.0
    assert summary["total_r"] == 0.0


def test_micro_main_strategy_backtest_runs() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    candles_1m = _candles("TESTUSDC", "1m", 1, 1200, start)
    candles_5m = _candles("TESTUSDC", "5m", 5, 400, start)
    engine = SessionImpulseRetestResearch(symbol="TESTUSDC", candles_1m=candles_1m, candles_5m=candles_5m)
    trades = engine.backtest()
    assert isinstance(trades, list)


def test_micro_main_signal_filter_profile_merges_symbol_override() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    candles_1m = _candles("BTCUSDC", "1m", 1, 1200, start)
    candles_5m = _candles("BTCUSDC", "5m", 5, 400, start)
    engine = SessionImpulseRetestResearch(symbol="BTCUSDC", candles_1m=candles_1m, candles_5m=candles_5m)
    profile = engine._signal_filter_profile()
    assert profile["min_reclaim_body_atr"] == 0.30
    assert profile["min_trend_strength"] == 0.25
    assert profile["max_retest_wait_minutes"] == 3.0
    assert profile["late_retest_high_risk_atr"] == 1.0
    assert profile["late_retest_high_risk_max_wait_minutes"] == 2.0


def test_micro_main_relaxed_profile_merges_default_and_symbol_override() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    candles_1m = _candles("XRPUSDC", "1m", 1, 1200, start)
    candles_5m = _candles("XRPUSDC", "5m", 5, 400, start)
    engine = SessionImpulseRetestResearch(
        symbol="XRPUSDC",
        candles_1m=candles_1m,
        candles_5m=candles_5m,
        profile_name="relaxed_v1",
    )
    profile = engine._signal_filter_profile()
    assert profile["min_reclaim_body_atr"] == 0.28
    assert profile["min_trend_strength"] == 0.20
    assert profile["min_volume_factor"] == 0.80

    eth_engine = SessionImpulseRetestResearch(
        symbol="ETHUSDC",
        candles_1m=candles_1m,
        candles_5m=candles_5m,
        profile_name="relaxed_v1",
    )
    assert eth_engine._signal_filter_profile()["min_volume_factor"] == 0.90


def test_micro_main_late_retest_risk_filter_blocks_stale_high_risk_retest() -> None:
    profile = {
        "late_retest_high_risk_atr": 1.0,
        "late_retest_high_risk_max_wait_minutes": 2.0,
    }
    assert SessionImpulseRetestResearch._passes_late_retest_risk_filter(
        profile,
        risk_atr=0.99,
        retest_wait_minutes=3,
    )
    assert SessionImpulseRetestResearch._passes_late_retest_risk_filter(
        profile,
        risk_atr=1.0,
        retest_wait_minutes=2,
    )
    assert not SessionImpulseRetestResearch._passes_late_retest_risk_filter(
        profile,
        risk_atr=1.0,
        retest_wait_minutes=3,
    )


def test_micro_main_runtime_profile_mapping_is_hybrid() -> None:
    assert session_impulse_retest_profile_for_symbol("BTCUSDC") == "baseline"
    assert session_impulse_retest_profile_for_symbol("BNBUSDC") == "baseline"
    assert session_impulse_retest_profile_for_symbol("SUIUSDC") == "baseline"
    assert session_impulse_retest_profile_for_symbol("BCHUSDC") == "baseline"
    assert session_impulse_retest_profile_for_symbol("LTCUSDC") == "baseline"
    assert session_impulse_retest_profile_for_symbol("NEARUSDC") == "baseline"
    assert session_impulse_retest_profile_for_symbol("AAVEUSDC") == "baseline"
    assert session_impulse_retest_profile_for_symbol("ETHUSDC") == "relaxed_v1"
    assert session_impulse_retest_profile_for_symbol("LINKUSDC") == "relaxed_v1"
    assert session_impulse_retest_profile_for_symbol("ADAUSDC") == "relaxed_v1"
    assert session_impulse_retest_profile_for_symbol("UNKNOWNUSDC") == "baseline"


def test_micro_main_blocked_signal_hours_are_symbol_specific() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    btc_1m = _candles("BTCUSDC", "1m", 1, 1200, start)
    btc_5m = _candles("BTCUSDC", "5m", 5, 400, start)
    btc_engine = SessionImpulseRetestResearch(symbol="BTCUSDC", candles_1m=btc_1m, candles_5m=btc_5m)
    assert btc_engine._blocked_signal_hours() == (0,)

    link_1m = _candles("LINKUSDC", "1m", 1, 1200, start)
    link_5m = _candles("LINKUSDC", "5m", 5, 400, start)
    link_engine = SessionImpulseRetestResearch(
        symbol="LINKUSDC",
        candles_1m=link_1m,
        candles_5m=link_5m,
        profile_name="relaxed_v1",
    )
    assert link_engine._blocked_signal_hours() == (8,)

    eth_1m = _candles("ETHUSDC", "1m", 1, 1200, start)
    eth_5m = _candles("ETHUSDC", "5m", 5, 400, start)
    eth_engine = SessionImpulseRetestResearch(
        symbol="ETHUSDC",
        candles_1m=eth_1m,
        candles_5m=eth_5m,
        profile_name="relaxed_v1",
    )
    assert eth_engine._blocked_signal_hours() == (1,)

    ada_1m = _candles("ADAUSDC", "1m", 1, 1200, start)
    ada_5m = _candles("ADAUSDC", "5m", 5, 400, start)
    ada_engine = SessionImpulseRetestResearch(
        symbol="ADAUSDC",
        candles_1m=ada_1m,
        candles_5m=ada_5m,
        profile_name="relaxed_v1",
    )
    assert ada_engine._blocked_signal_hours() == (7,)


def test_micro_main_time_guard_reason_prefers_tighter_guard_first() -> None:
    assert SessionImpulseRetestResearch._time_guard_exit_reason(held_minutes=10, best_progress_r=0.10) == "time_guard_10m"
    assert SessionImpulseRetestResearch._time_guard_exit_reason(held_minutes=20, best_progress_r=0.20) == "time_guard_20m"
    assert SessionImpulseRetestResearch._time_guard_exit_reason(held_minutes=20, best_progress_r=0.50) is None


def test_micro_main_shadow_summary_respects_symbol_contract() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    candles_1m = _candles("TESTUSDC", "1m", 1, 1200, start)
    candles_5m = _candles("TESTUSDC", "5m", 5, 400, start)
    payload = build_session_impulse_retest_shadow_summary(
        symbol="TESTUSDC",
        candles_1m=candles_1m,
        candles_5m=candles_5m,
        enabled=True,
        shadow_only=True,
        allowed_symbols=["BTCUSDC"],
    )
    assert payload["available"] is False
    assert payload["status"] == "symbol_not_allowed"
    assert payload["reason"] == "symbol_not_in_session_impulse_retest_contract"


def test_micro_main_decision_returns_watch_for_positive_but_thin_sample() -> None:
    assert decision_for_micro_summary({"closed": 35, "ev_r": 0.31, "total_r": 10.85}) == "WATCH"
