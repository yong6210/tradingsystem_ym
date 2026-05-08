from datetime import UTC, datetime, timedelta

from app.db.models import Candle
from app.services.specialist_strategy_research import SpecialistResearchEngine, summarize_research_trades


def _candles() -> list[Candle]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    rows: list[Candle] = []
    price = 100.0
    for idx in range(160):
        drift = 0.12 if idx < 80 else -0.08
        price += drift
        high = price + 0.6
        low = price - 0.6
        close = price + (0.15 if idx % 3 == 0 else -0.05)
        rows.append(
            Candle(
                symbol="TESTUSDC",
                timeframe="15m",
                ts=start + timedelta(minutes=15 * idx),
                o=price,
                h=high,
                l=low,
                c=close,
                v=1000 + idx * 10,
                source="test",
                is_final=True,
            )
        )
    return rows


def test_specialist_research_engine_exposes_expected_families() -> None:
    engine = SpecialistResearchEngine(symbol="TESTUSDC", candles_15m=_candles())
    keys = {spec.key for spec in engine.family_specs()}
    assert "choch_displacement_reclaim" in keys
    assert "mss_choch_soft_reclaim" in keys
    assert "judas_swing_reversal" in keys
    assert "turtle_soup_failed_breakout" in keys
    assert "orb_breakout" in keys
    assert "orb_breakout_v2" in keys
    assert "session_auction_reclaim" in keys
    assert "session_auction_reclaim_v2" in keys
    assert "ict_mss_displacement_fvg_reclaim" in keys
    assert "event_shock_imbalance" in keys
    assert "vwap_deviation_reversion" in keys
    assert "volume_displacement_continuation" in keys


def test_specialist_research_summary_handles_empty_trades() -> None:
    summary = summarize_research_trades([])
    assert summary["closed"] == 0
    assert summary["ev_r"] == 0.0
    assert summary["total_r"] == 0.0
