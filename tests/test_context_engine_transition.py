from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.db.models import Candle
from app.services.context_engine import ContextEngine


def _candle(ts: datetime, o: float, c: float, wick: float = 7.0) -> Candle:
    high = max(o, c) + wick
    low = min(o, c) - wick
    return Candle(
        symbol="BTCUSDC",
        timeframe="5m",
        ts=ts,
        o=o,
        h=high,
        l=low,
        c=c,
        v=1_000.0,
        source="test",
        is_final=True,
    )


def test_context_engine_marks_transition_regime_when_conflict_churn_is_high() -> None:
    engine = ContextEngine()
    base = datetime(2026, 3, 1, tzinfo=timezone.utc)

    closes_5m = [100.0, 104.0, 99.0, 105.0, 98.0, 104.0, 99.0, 105.0, 98.0, 104.0, 99.0, 103.0]
    candles_5m: list[Candle] = []
    prev = 100.0
    for index, close in enumerate(closes_5m):
        candles_5m.append(_candle(base + timedelta(minutes=5 * index), prev, close))
        prev = close

    candles_15m: list[Candle] = []
    prev = 100.0
    for index, close in enumerate([100.5, 101.0, 101.8, 102.4, 103.0, 103.6]):
        candles_15m.append(
            Candle(
                symbol="BTCUSDC",
                timeframe="15m",
                ts=base + timedelta(minutes=15 * index),
                o=prev,
                h=max(prev, close) + 1.0,
                l=min(prev, close) - 0.8,
                c=close,
                v=2_000.0,
                source="test",
                is_final=True,
            )
        )
        prev = close

    snapshot = engine.build_snapshot(symbol="BTCUSDC", candles_5m=candles_5m, candles_15m=candles_15m)

    assert snapshot.transition_state == "transition_confirmed"
    assert snapshot.regime_label == "transition"
    assert snapshot.transition_score >= engine.settings.transition_confirmed_score
    assert snapshot.transition_features["bidirectional_sweep_churn"] == 1
    assert snapshot.transition_features["reaction_failure_cluster"] == 1
    assert snapshot.transition_features["wick_dominance"] == 1
    assert snapshot.transition_features["zone_invalidation_churn"] == 1
    assert snapshot.signal_telemetry["telemetry_source"] == "context_snapshot"
    assert "range_atr" in snapshot.signal_telemetry
    assert "close_vs_ema_fast_atr" in snapshot.signal_telemetry
    assert "long_sweep_distance_atr" in snapshot.signal_telemetry
