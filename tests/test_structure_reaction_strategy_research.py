from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import MethodType

from app.db.models import Candle
from app.services.structure_reaction_strategy_research import (
    StructureReactionPolicy,
    StructureReactionResearch,
)


def _candles(symbol: str, interval: str, minutes: int, count: int, start: datetime) -> list[Candle]:
    rows: list[Candle] = []
    price = 100.0
    for idx in range(count):
        ts = start + timedelta(minutes=idx * minutes)
        rows.append(
            Candle(
                symbol=symbol,
                timeframe=interval,
                ts=ts,
                o=price,
                h=price + 0.2,
                l=price - 0.2,
                c=price + 0.05,
                v=1000.0,
                source="test",
                is_final=True,
            )
        )
    return rows


def test_structure_reaction_long_buffers_stop_beyond_anchor_and_tp_before_targets() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    candles_1m = _candles("TESTUSDT", "1m", 1, 1800, start)
    candles_5m = _candles("TESTUSDT", "5m", 5, 420, start)
    setup_idx = 320
    entry_idx = setup_idx * 5 + 5
    candles_5m[setup_idx].o = 99.6
    candles_5m[setup_idx].h = 100.1
    candles_5m[setup_idx].l = 99.2
    candles_5m[setup_idx].c = 100.0
    candles_5m[setup_idx].v = 3000.0
    candles_1m[entry_idx].o = 100.0
    engine = StructureReactionResearch(
        symbol="TESTUSDT",
        candles_1m=candles_1m,
        candles_5m=candles_5m,
        policy=StructureReactionPolicy(
            name="test_structure_reaction",
            min_stop_pct=0.0,
            min_risk_atr=0.0,
            max_stop_pct=0.0,
            max_risk_atr=3.0,
            min_volume_factor=0.1,
            min_body_atr=0.01,
            min_wick_fraction=0.10,
            stop_buffer_atr=0.12,
            target_buffer_atr=0.08,
            min_signal_spacing_minutes=0,
        ),
    )
    engine.atr_5m[setup_idx - 1] = 1.0
    engine.atr_5m[setup_idx] = 1.0

    def fake_context(self: StructureReactionResearch, **_kwargs: object) -> dict[str, object]:
        return {
            "htf_structure_enabled": True,
            "htf_structure_zone_count": 3,
            "htf_structure_anchor_score": 1.0,
            "htf_structure_anchor_distance_atr": 0.5,
            "htf_structure_anchor": {
                "kind": "order_block",
                "side": "support",
                "low": 99.0,
                "high": 99.5,
                "mid": 99.25,
                "score": 1.0,
                "timeframe": "4h",
                "source_ts": candles_5m[setup_idx - 20].ts.isoformat(),
                "source": "4h_bullish_order_block",
            },
            "htf_structure_anchor_low": 99.0,
            "htf_structure_anchor_high": 99.5,
            "htf_structure_target_prices": [101.2, 102.5],
            "htf_structure_target_sources": ["4h_resistance", "1d_resistance"],
        }

    engine._higher_timeframe_structure_context = MethodType(fake_context, engine)

    signal = engine._build_signal(setup_idx)

    assert signal is not None
    assert signal.family == "htf_structure_reaction"
    assert signal.direction == "long"
    assert round(signal.stop_price, 8) == 98.88
    assert round(signal.diagnostics["policy_structure_tp1_price"], 8) == 101.12
    assert round(signal.diagnostics["policy_structure_tp2_price"], 8) == 102.42


def test_structure_reaction_short_buffers_stop_beyond_anchor() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    candles_1m = _candles("TESTUSDT", "1m", 1, 1800, start)
    candles_5m = _candles("TESTUSDT", "5m", 5, 420, start)
    setup_idx = 320
    entry_idx = setup_idx * 5 + 5
    candles_5m[setup_idx].o = 100.4
    candles_5m[setup_idx].h = 100.8
    candles_5m[setup_idx].l = 99.9
    candles_5m[setup_idx].c = 100.0
    candles_5m[setup_idx].v = 3000.0
    candles_1m[entry_idx].o = 100.0
    engine = StructureReactionResearch(
        symbol="TESTUSDT",
        candles_1m=candles_1m,
        candles_5m=candles_5m,
        policy=StructureReactionPolicy(
            name="test_structure_reaction_short",
            min_stop_pct=0.0,
            min_risk_atr=0.0,
            max_stop_pct=0.0,
            max_risk_atr=3.0,
            min_volume_factor=0.1,
            min_body_atr=0.01,
            min_wick_fraction=0.10,
            stop_buffer_atr=0.12,
            target_buffer_atr=0.08,
            min_signal_spacing_minutes=0,
        ),
    )
    engine.atr_5m[setup_idx - 1] = 1.0
    engine.atr_5m[setup_idx] = 1.0

    def fake_context(self: StructureReactionResearch, **_kwargs: object) -> dict[str, object]:
        return {
            "htf_structure_enabled": True,
            "htf_structure_zone_count": 3,
            "htf_structure_anchor_score": 1.0,
            "htf_structure_anchor_distance_atr": 0.5,
            "htf_structure_anchor": {
                "kind": "order_block",
                "side": "resistance",
                "low": 100.5,
                "high": 101.0,
                "mid": 100.75,
                "score": 1.0,
                "timeframe": "4h",
                "source_ts": candles_5m[setup_idx - 20].ts.isoformat(),
                "source": "4h_bearish_order_block",
            },
            "htf_structure_anchor_low": 100.5,
            "htf_structure_anchor_high": 101.0,
            "htf_structure_target_prices": [98.8, 97.5],
            "htf_structure_target_sources": ["4h_support", "1d_support"],
        }

    engine._higher_timeframe_structure_context = MethodType(fake_context, engine)

    signal = engine._build_signal(setup_idx)

    assert signal is not None
    assert signal.direction == "short"
    assert round(signal.stop_price, 8) == 101.12
    assert round(signal.diagnostics["policy_structure_tp1_price"], 8) == 98.88
    assert round(signal.diagnostics["policy_structure_tp2_price"], 8) == 97.58
