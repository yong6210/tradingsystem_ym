from datetime import UTC, datetime, timedelta

from app.db.models import Candle
from app.services.micro_main_strategy_research import (
    MicroSignal,
    SessionImpulseRetestExitPolicy,
    SessionImpulseRetestResearch,
    build_session_impulse_retest_shadow_summary,
    decision_for_micro_summary,
    evaluate_session_impulse_retest_shadow_filters,
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


def test_micro_main_latest_signal_diagnostics_explain_no_fresh_signal() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    candles_1m = _candles("TESTUSDC", "1m", 1, 1200, start)
    candles_5m = _candles("TESTUSDC", "5m", 5, 400, start)
    engine = SessionImpulseRetestResearch(symbol="TESTUSDC", candles_1m=candles_1m, candles_5m=candles_5m)

    payload = engine.latest_signal_diagnostics(freshness_minutes=20)

    assert payload["schema_version"] == "session_impulse_retest_latest_signal_diagnostics_v1"
    assert payload["symbol"] == "TESTUSDC"
    assert payload["status"] in {"no_fresh_signal", "fresh_signal"}
    assert payload["scan_bars"] > 0
    if payload["status"] == "no_fresh_signal":
        assert payload["reason"]
        assert isinstance(payload["reason_counts"], dict)
        assert payload["latest_checked"]["reason"]


def test_micro_main_latest_signal_diagnostics_prefers_latest_checked_reason() -> None:
    start = datetime(2026, 5, 17, 12, 30, tzinfo=UTC)
    candles_1m = _candles("TESTUSDC", "1m", 1, 900, start)
    candles_5m = _candles("TESTUSDC", "5m", 5, 180, start)
    engine = SessionImpulseRetestResearch(symbol="TESTUSDC", candles_1m=candles_1m, candles_5m=candles_5m)
    diagnostics = [
        {"setup_ts": "latest", "reason": "trend_strength_too_weak"},
        {"setup_ts": "older-1", "reason": "before_session_signal_window"},
        {"setup_ts": "older-2", "reason": "before_session_signal_window"},
    ]

    engine._build_signal = lambda idx: None  # type: ignore[method-assign]
    engine._signal_rejection_diagnostics = (  # type: ignore[method-assign]
        lambda idx: diagnostics.pop(0) if diagnostics else {"setup_ts": "older", "reason": "before_session_signal_window"}
    )

    payload = engine.latest_signal_diagnostics(freshness_minutes=20)

    assert payload["reason_counts"]["before_session_signal_window"] > payload["reason_counts"]["trend_strength_too_weak"]
    assert payload["reason"] == "trend_strength_too_weak"


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
    assert session_impulse_retest_profile_for_symbol("ETHUSDT") == "relaxed_v1"
    assert session_impulse_retest_profile_for_symbol("LINKUSDT") == "relaxed_v1"
    assert session_impulse_retest_profile_for_symbol("UNKNOWNUSDC") == "baseline"


def test_micro_main_blocked_signal_hours_are_symbol_specific() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    btc_1m = _candles("BTCUSDC", "1m", 1, 1200, start)
    btc_5m = _candles("BTCUSDC", "5m", 5, 400, start)
    btc_engine = SessionImpulseRetestResearch(symbol="BTCUSDC", candles_1m=btc_1m, candles_5m=btc_5m)
    assert btc_engine._blocked_signal_hours() == (0,)
    btc_usdt_engine = SessionImpulseRetestResearch(symbol="BTCUSDT", candles_1m=btc_1m, candles_5m=btc_5m)
    assert btc_usdt_engine._blocked_signal_hours() == (0,)

    link_1m = _candles("LINKUSDC", "1m", 1, 1200, start)
    link_5m = _candles("LINKUSDC", "5m", 5, 400, start)
    link_engine = SessionImpulseRetestResearch(
        symbol="LINKUSDC",
        candles_1m=link_1m,
        candles_5m=link_5m,
        profile_name="relaxed_v1",
    )
    assert link_engine._blocked_signal_hours() == (8,)
    link_usdt_engine = SessionImpulseRetestResearch(
        symbol="LINKUSDT",
        candles_1m=link_1m,
        candles_5m=link_5m,
        profile_name="relaxed_v1",
    )
    assert link_usdt_engine._blocked_signal_hours() == (8,)

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


def test_micro_main_session_anchor_lookup_covers_long_anchor_gap_for_diagnostics() -> None:
    start = datetime(2026, 5, 17, 5, 0, tzinfo=UTC)
    candles_1m = _candles("TESTUSDC", "1m", 1, 1200, start)
    candles_5m = _candles("TESTUSDC", "5m", 5, 120, start)
    engine = SessionImpulseRetestResearch(symbol="TESTUSDC", candles_1m=candles_1m, candles_5m=candles_5m)
    idx = engine.ts_5m.index(datetime(2026, 5, 17, 12, 55, tzinfo=UTC))

    anchor_idx = engine._session_anchor_index(idx)
    diagnostic = engine._signal_rejection_diagnostics(idx)

    assert anchor_idx is not None
    assert engine.ts_5m[anchor_idx] == datetime(2026, 5, 17, 6, 0, tzinfo=UTC)
    assert diagnostic["reason"] == "after_session_signal_window"


def test_micro_main_time_guard_reason_prefers_tighter_guard_first() -> None:
    assert SessionImpulseRetestResearch._time_guard_exit_reason(held_minutes=10, best_progress_r=0.10) == "time_guard_10m"
    assert SessionImpulseRetestResearch._time_guard_exit_reason(held_minutes=20, best_progress_r=0.20) == "time_guard_20m"
    assert SessionImpulseRetestResearch._time_guard_exit_reason(held_minutes=20, best_progress_r=0.50) is None


def test_session_impulse_retest_adaptive_exit_defends_expanded_stops() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    candles_1m = _candles("TESTUSDT", "1m", 1, 1200, start)
    candles_5m = _candles("TESTUSDT", "5m", 5, 400, start)
    engine = SessionImpulseRetestResearch(
        symbol="TESTUSDT",
        candles_1m=candles_1m,
        candles_5m=candles_5m,
        exit_policy=SessionImpulseRetestExitPolicy(
            name="adaptive_floor_min_0_003_live_split",
            stop_mode="floor",
            min_stop_pct=0.003,
            target_rr=2.5,
            tp1_rr=1.0,
            tp1_fraction=0.35,
            tp2_rr=2.5,
            tp2_fraction=0.65,
            adaptive_targets_enabled=True,
        ),
    )
    setup_ts = engine.ts_5m[120]
    signal = MicroSignal(
        family="session_impulse_retest",
        direction="long",
        signal_ts=setup_ts,
        setup_ts=setup_ts,
        entry_ts=setup_ts,
        entry_price=100.0,
        stop_price=99.9,
        target_price=100.2,
        max_hold_minutes=40,
        regime_hint="session_open",
        diagnostics={
            "reclaim_body_atr": 0.60,
            "volume_factor": 1.80,
            "trend_strength_atr": 0.80,
            "drive_extension_atr": 1.10,
            "retest_wait_minutes": 0,
        },
    )

    adjusted = engine._apply_exit_policy(signal)

    assert adjusted is not None
    assert adjusted.diagnostics["policy_target_profile"] == "defensive"
    assert adjusted.diagnostics["policy_target_rr"] == 2.0
    assert round(adjusted.diagnostics["policy_tp1_fraction"], 8) == 0.45
    assert round(adjusted.diagnostics["policy_tp2_fraction"], 8) == 0.55


def test_session_impulse_retest_structure_exit_uses_key_levels() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    candles_1m = _candles("TESTUSDT", "1m", 1, 1200, start)
    candles_5m = _candles("TESTUSDT", "5m", 5, 400, start)
    engine = SessionImpulseRetestResearch(
        symbol="TESTUSDT",
        candles_1m=candles_1m,
        candles_5m=candles_5m,
        exit_policy=SessionImpulseRetestExitPolicy(
            name="structure_adaptive_floor_min_0_003_live_split",
            stop_mode="floor",
            min_stop_pct=0.003,
            target_rr=2.5,
            tp1_rr=1.0,
            tp1_fraction=0.35,
            tp2_rr=2.5,
            tp2_fraction=0.65,
            adaptive_targets_enabled=True,
            structure_targets_enabled=True,
            structure_target_buffer_atr=0.0,
        ),
    )
    setup_ts = engine.ts_5m[120]
    signal = MicroSignal(
        family="session_impulse_retest",
        direction="long",
        signal_ts=setup_ts,
        setup_ts=setup_ts,
        entry_ts=setup_ts,
        entry_price=100.0,
        stop_price=99.0,
        target_price=102.0,
        max_hold_minutes=40,
        regime_hint="session_open",
        diagnostics={
            "entry_distance_atr": 0.10,
            "reclaim_body_atr": 0.60,
            "volume_factor": 1.80,
            "trend_strength_atr": 0.80,
            "drive_extension_atr": 1.10,
            "retest_wait_minutes": 0,
            "structure_target_prices": [101.2, 102.4, 103.6],
            "structure_target_sources": ["drive_high", "opening_range_measured_move_1x", "opening_range_measured_move_2x"],
        },
    )

    adjusted = engine._apply_exit_policy(signal)

    assert adjusted is not None
    assert adjusted.diagnostics["policy_target_profile"] == "structure_strong"
    assert round(adjusted.diagnostics["policy_target_rr"], 8) == 2.4
    assert adjusted.diagnostics["policy_structure_tp1_source"] == "drive_high"
    assert adjusted.diagnostics["policy_structure_tp2_source"] == "opening_range_measured_move_1x"
    assert round(adjusted.diagnostics["policy_tp1_rr"], 8) == 1.2
    assert round(adjusted.diagnostics["policy_tp2_rr"], 8) == 2.4


def test_session_impulse_retest_structure_targets_buffer_before_key_level() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    candles_1m = _candles("TESTUSDT", "1m", 1, 1200, start)
    candles_5m = _candles("TESTUSDT", "5m", 5, 400, start)
    engine = SessionImpulseRetestResearch(
        symbol="TESTUSDT",
        candles_1m=candles_1m,
        candles_5m=candles_5m,
        exit_policy=SessionImpulseRetestExitPolicy(
            name="structure_buffered_targets",
            stop_mode="floor",
            min_stop_pct=0.0,
            min_risk_atr=0.0,
            tp1_fraction=0.35,
            tp2_fraction=0.65,
            adaptive_targets_enabled=False,
            structure_targets_enabled=True,
            structure_target_buffer_atr=0.10,
            structure_tp1_min_rr=0.8,
            structure_tp2_min_rr=1.6,
        ),
    )
    engine.atr_5m[120] = 1.0
    setup_ts = engine.ts_5m[120]
    signal = MicroSignal(
        family="session_impulse_retest",
        direction="long",
        signal_ts=setup_ts,
        setup_ts=setup_ts,
        entry_ts=setup_ts,
        entry_price=100.0,
        stop_price=99.0,
        target_price=102.0,
        max_hold_minutes=40,
        regime_hint="session_open",
        diagnostics={
            "entry_distance_atr": 0.10,
            "structure_target_prices": [101.2, 102.4],
            "structure_target_sources": ["near_resistance", "far_resistance"],
        },
    )

    adjusted = engine._apply_exit_policy(signal)

    assert adjusted is not None
    assert round(adjusted.diagnostics["policy_structure_tp1_price"], 8) == 101.1
    assert round(adjusted.diagnostics["policy_structure_tp2_price"], 8) == 102.3
    assert round(adjusted.diagnostics["policy_tp1_rr"], 8) == 1.1
    assert round(adjusted.diagnostics["policy_tp2_rr"], 8) == 2.3


def test_session_impulse_retest_structure_stop_buffers_beyond_swing_level() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    candles_1m = _candles("TESTUSDT", "1m", 1, 1200, start)
    candles_5m = _candles("TESTUSDT", "5m", 5, 400, start)
    engine = SessionImpulseRetestResearch(
        symbol="TESTUSDT",
        candles_1m=candles_1m,
        candles_5m=candles_5m,
        exit_policy=SessionImpulseRetestExitPolicy(
            name="structure_buffered_stop",
            stop_mode="structure_floor",
            swing_lookback_bars=6,
            stop_buffer_atr=0.12,
            min_stop_pct=0.0,
            min_risk_atr=0.0,
            target_rr=2.0,
        ),
    )
    engine.atr_5m[120] = 1.0
    for idx in range(115, 121):
        engine.lows_5m[idx] = 99.4
    engine.lows_5m[118] = 99.0
    setup_ts = engine.ts_5m[120]
    signal = MicroSignal(
        family="session_impulse_retest",
        direction="long",
        signal_ts=setup_ts,
        setup_ts=setup_ts,
        entry_ts=setup_ts,
        entry_price=100.0,
        stop_price=99.7,
        target_price=101.0,
        max_hold_minutes=40,
        regime_hint="session_open",
    )

    adjusted = engine._apply_exit_policy(signal)

    assert adjusted is not None
    assert round(adjusted.stop_price, 8) == 98.88
    assert round(adjusted.diagnostics["policy_risk_atr"], 8) == 1.12


def test_session_impulse_retest_structure_exit_skips_chased_entry() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    candles_1m = _candles("TESTUSDT", "1m", 1, 1200, start)
    candles_5m = _candles("TESTUSDT", "5m", 5, 400, start)
    engine = SessionImpulseRetestResearch(
        symbol="TESTUSDT",
        candles_1m=candles_1m,
        candles_5m=candles_5m,
        exit_policy=SessionImpulseRetestExitPolicy(
            name="structure_adaptive_floor_min_0_003_live_split",
            stop_mode="floor",
            min_stop_pct=0.003,
            adaptive_targets_enabled=True,
            structure_targets_enabled=True,
            structure_entry_max_distance_atr=0.45,
        ),
    )
    setup_ts = engine.ts_5m[120]
    signal = MicroSignal(
        family="session_impulse_retest",
        direction="long",
        signal_ts=setup_ts,
        setup_ts=setup_ts,
        entry_ts=setup_ts,
        entry_price=100.0,
        stop_price=99.0,
        target_price=102.0,
        max_hold_minutes=40,
        regime_hint="session_open",
        diagnostics={"entry_distance_atr": 0.70},
    )

    assert engine._apply_exit_policy(signal) is None


def test_session_impulse_retest_entry_waits_until_setup_candle_is_actionable() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    candles_1m = _candles("TESTUSDT", "1m", 1, 40, start)
    candles_5m = _candles("TESTUSDT", "5m", 5, 12, start)
    setup_idx = 2
    inside_idx = 10
    actionable_idx = 15
    candles_1m[inside_idx].o = 99.8
    candles_1m[inside_idx].h = 100.4
    candles_1m[inside_idx].l = 99.9
    candles_1m[inside_idx].c = 100.2
    candles_1m[actionable_idx].o = 99.9
    candles_1m[actionable_idx].h = 100.3
    candles_1m[actionable_idx].l = 99.95
    candles_1m[actionable_idx].c = 100.1
    engine = SessionImpulseRetestResearch(symbol="TESTUSDT", candles_1m=candles_1m, candles_5m=candles_5m)

    entry = engine._find_1m_entry(
        setup_idx_5m=setup_idx,
        direction="long",
        reclaim_level=100.0,
        atr_5m=1.0,
        retest_buffer_atr=0.1,
        max_retest_wait_minutes=3,
    )

    assert entry is not None
    assert entry[0] == start + timedelta(minutes=15)
    assert entry[1] == 100.1


def test_session_impulse_retest_entry_ignores_same_5m_bar_retest() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    candles_1m = _candles("TESTUSDT", "1m", 1, 40, start)
    candles_5m = _candles("TESTUSDT", "5m", 5, 12, start)
    setup_idx = 2
    candles_1m[10].o = 99.8
    candles_1m[10].h = 100.4
    candles_1m[10].l = 99.9
    candles_1m[10].c = 100.2
    for idx in range(15, 19):
        candles_1m[idx].o = 100.2
        candles_1m[idx].h = 100.4
        candles_1m[idx].l = 100.15
        candles_1m[idx].c = 100.1
    engine = SessionImpulseRetestResearch(symbol="TESTUSDT", candles_1m=candles_1m, candles_5m=candles_5m)

    entry = engine._find_1m_entry(
        setup_idx_5m=setup_idx,
        direction="long",
        reclaim_level=100.0,
        atr_5m=1.0,
        retest_buffer_atr=0.1,
        max_retest_wait_minutes=3,
    )

    assert entry is None


def test_session_impulse_retest_backtest_moves_stop_after_partial() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    candles_1m = _candles("TESTUSDT", "1m", 1, 120, start)
    candles_5m = _candles("TESTUSDT", "5m", 5, 80, start)
    candles_1m[10].o = 100.0
    candles_1m[10].h = 101.1
    candles_1m[10].l = 100.2
    candles_1m[10].c = 101.0
    candles_1m[11].o = 100.8
    candles_1m[11].h = 100.9
    candles_1m[11].l = 99.95
    candles_1m[11].c = 100.1
    engine = SessionImpulseRetestResearch(
        symbol="TESTUSDT",
        candles_1m=candles_1m,
        candles_5m=candles_5m,
        exit_policy=SessionImpulseRetestExitPolicy(
            name="managed_split",
            tp1_rr=1.0,
            tp1_fraction=0.35,
            tp2_rr=2.0,
            tp2_fraction=0.65,
            stop_after_partial_rr=0.0,
        ),
    )
    signal = MicroSignal(
        family="session_impulse_retest",
        direction="long",
        signal_ts=candles_1m[10].ts,
        setup_ts=candles_1m[10].ts,
        entry_ts=candles_1m[10].ts,
        entry_price=100.0,
        stop_price=99.0,
        target_price=102.0,
        max_hold_minutes=20,
        regime_hint="test",
    )

    trade = engine._simulate_trade(signal)

    assert trade is not None
    assert trade.exit_reason == "stop_after_partial"
    assert round(trade.gross_r, 8) == 0.35
    assert trade.diagnostics["position_management_events"] == ["stop_after_partial_adjusted"]
    assert trade.diagnostics["managed_stop_after_partial_price"] == 100.0


def test_session_impulse_retest_backtest_can_exit_on_adverse_volume() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    candles_1m = _candles("TESTUSDT", "1m", 1, 120, start)
    candles_5m = _candles("TESTUSDT", "5m", 5, 80, start)
    for idx in range(5, 12):
        candles_1m[idx].v = 1000.0
    candles_1m[10].o = 100.0
    candles_1m[10].h = 100.4
    candles_1m[10].l = 99.9
    candles_1m[10].c = 100.2
    candles_1m[11].o = 100.4
    candles_1m[11].h = 100.5
    candles_1m[11].l = 99.8
    candles_1m[11].c = 99.9
    candles_1m[11].v = 5000.0
    engine = SessionImpulseRetestResearch(
        symbol="TESTUSDT",
        candles_1m=candles_1m,
        candles_5m=candles_5m,
        exit_policy=SessionImpulseRetestExitPolicy(
            name="managed_adverse_volume",
            adverse_volume_exit_enabled=True,
            adverse_volume_exit_after_partial_only=False,
            adverse_volume_exit_min_factor=3.0,
            adverse_volume_exit_min_body_r=0.35,
            adverse_volume_exit_lookback_bars=5,
        ),
    )
    signal = MicroSignal(
        family="session_impulse_retest",
        direction="long",
        signal_ts=candles_1m[10].ts,
        setup_ts=candles_1m[10].ts,
        entry_ts=candles_1m[10].ts,
        entry_price=100.0,
        stop_price=99.0,
        target_price=102.0,
        max_hold_minutes=20,
        regime_hint="test",
    )

    trade = engine._simulate_trade(signal)

    assert trade is not None
    assert trade.exit_reason == "adverse_volume_exit"
    assert round(trade.gross_r, 8) == -0.1
    assert trade.diagnostics["position_management_events"] == ["adverse_volume_exit"]
    assert trade.diagnostics["adverse_volume_exit"]["volume_factor"] == 5.0


def test_session_impulse_retest_higher_timeframe_context_finds_anchor_and_target() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    candles_1m = _candles("TESTUSDT", "1m", 1, 1200, start)
    candles_5m = _candles("TESTUSDT", "5m", 5, 400, start)
    engine = SessionImpulseRetestResearch(
        symbol="TESTUSDT",
        candles_1m=candles_1m,
        candles_5m=candles_5m,
        exit_policy=SessionImpulseRetestExitPolicy(
            higher_timeframe_structure_enabled=True,
            higher_timeframe_entry_min_score=0.0,
            higher_timeframe_lookback_days=21,
        ),
    )
    setup_idx = 220
    setup_ts = engine.ts_5m[setup_idx]

    def _bar(hours_back: int, *, o: float, h: float, l: float, c: float) -> dict[str, object]:
        start_ts = setup_ts - timedelta(hours=hours_back)
        return {
            "start_ts": start_ts,
            "end_ts": start_ts + timedelta(hours=4),
            "o": o,
            "h": h,
            "l": l,
            "c": c,
            "v": 1000.0,
        }

    engine.htf_1d_bars = []
    engine.htf_1d_atr = []
    engine.htf_4h_bars = [
        _bar(36, o=100.0, h=101.0, l=98.0, c=99.0),
        _bar(32, o=99.2, h=103.0, l=99.0, c=102.5),
        _bar(28, o=102.5, h=104.0, l=102.0, c=103.5),
        _bar(24, o=103.5, h=104.5, l=102.8, c=104.0),
        _bar(20, o=106.5, h=107.0, l=106.0, c=106.2),
        _bar(16, o=105.5, h=106.0, l=105.0, c=105.4),
        _bar(12, o=104.0, h=104.5, l=103.8, c=104.1),
    ]
    engine.htf_4h_atr = [1.0] * len(engine.htf_4h_bars)

    context = engine._higher_timeframe_structure_context(
        setup_idx=setup_idx,
        direction="long",
        entry_price=99.5,
        atr=1.0,
    )

    assert context["htf_structure_anchor_score"] > 0.0
    assert context["htf_structure_anchor_kind"] == "order_block"
    assert context["htf_structure_anchor_source"] == "4h_bullish_order_block"
    assert "4h_bearish_fvg" in context["htf_structure_target_sources"]
    assert any(price > 99.5 for price in context["htf_structure_target_prices"])


def test_session_impulse_retest_higher_timeframe_score_can_block_weak_context() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    candles_1m = _candles("TESTUSDT", "1m", 1, 1200, start)
    candles_5m = _candles("TESTUSDT", "5m", 5, 400, start)
    engine = SessionImpulseRetestResearch(
        symbol="TESTUSDT",
        candles_1m=candles_1m,
        candles_5m=candles_5m,
        exit_policy=SessionImpulseRetestExitPolicy(
            name="htf_structure_min_score_test",
            stop_mode="floor",
            min_stop_pct=0.003,
            target_rr=2.5,
            higher_timeframe_structure_enabled=True,
            higher_timeframe_entry_min_score=0.7,
        ),
    )
    setup_ts = engine.ts_5m[120]
    signal = MicroSignal(
        family="session_impulse_retest",
        direction="long",
        signal_ts=setup_ts,
        setup_ts=setup_ts,
        entry_ts=setup_ts,
        entry_price=100.0,
        stop_price=99.0,
        target_price=102.0,
        max_hold_minutes=40,
        regime_hint="session_open",
        diagnostics={"htf_structure_anchor_score": 0.2},
    )

    assert engine._apply_exit_policy(signal) is None


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


def test_session_impulse_retest_shadow_filter_is_compare_only() -> None:
    blocked = evaluate_session_impulse_retest_shadow_filters(diagnostics={"reclaim_body_atr": 0.24})
    assert blocked["mode"] == "compare_only"
    assert blocked["blocking_live"] is False
    assert blocked["decision"] == "would_block"
    assert blocked["filters"][0]["passed"] is False

    passed = evaluate_session_impulse_retest_shadow_filters(diagnostics={"reclaim_body_atr": 0.31})
    assert passed["decision"] == "would_pass"
    assert passed["filters"][0]["passed"] is True
