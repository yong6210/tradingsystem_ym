from datetime import UTC, datetime, timedelta

from app.db.models import BasisSnapshot, Candle, CrossAssetBreadthSnapshot, FundingRateSnapshot, LiquidationEvent, MacroEvent, OpenInterestSnapshot
from app.services.alt_data_strategy_research import AltDataResearchEngine, summarize_alt_data_research_trades


def _candles() -> list[Candle]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    rows: list[Candle] = []
    price = 100.0
    for idx in range(180):
        price += 0.05
        rows.append(
            Candle(
                symbol="TESTUSDC",
                timeframe="15m",
                ts=start + timedelta(minutes=15 * idx),
                o=price,
                h=price + 0.6,
                l=price - 0.6,
                c=price + (0.1 if idx % 2 == 0 else -0.05),
                v=1000 + idx,
                source="test",
                is_final=True,
            )
        )
    return rows


def _funding_rows() -> list[FundingRateSnapshot]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return [
        FundingRateSnapshot(symbol="TESTUSDC", ts=start + timedelta(hours=8 * idx), funding_rate=0.0001, mark_price=100.0, source="test", raw={})
        for idx in range(6)
    ]


def _oi_rows() -> list[OpenInterestSnapshot]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return [
        OpenInterestSnapshot(symbol="TESTUSDC", period="15m", ts=start + timedelta(minutes=15 * idx), open_interest=10000 + idx, open_interest_value=1000000.0, source="test", raw={})
        for idx in range(180)
    ]


def _basis_rows() -> list[BasisSnapshot]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return [
        BasisSnapshot(
            symbol="TESTUSDC",
            timeframe="15m",
            ts=start + timedelta(minutes=15 * idx),
            basis_open=0.0,
            basis_high=0.0,
            basis_low=0.0,
            basis_close=0.0,
            basis_bps=0.0,
            source="test",
            raw={},
        )
        for idx in range(180)
    ]


def _breadth_rows() -> list[CrossAssetBreadthSnapshot]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return [
        CrossAssetBreadthSnapshot(
            leader_symbol="TESTUSDC",
            confirm_symbol="OTHERUSDC",
            timeframe="15m",
            ts=start + timedelta(minutes=15 * idx),
            leader_close=100.0 + idx,
            confirm_close=99.0 + idx,
            leader_ret_1h=0.001,
            confirm_ret_1h=0.0005,
            leader_ret_4h=0.004,
            confirm_ret_4h=0.002,
            divergence_bps=20.0,
            breadth_score=2.1 if idx % 10 == 0 else 0.0,
            source="test",
            raw={},
        )
        for idx in range(180)
    ]


def _macro_events() -> list[MacroEvent]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return [
        MacroEvent(
            event_ts=start + timedelta(minutes=15 * 40),
            event_code="FOMC_RATE_DECISION",
            importance="high",
            country="US",
            title="FOMC rate decision / statement",
            source="test",
            raw={},
        )
    ]


def _liquidation_rows() -> list[LiquidationEvent]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return [
        LiquidationEvent(
            symbol="TESTUSDC",
            ts=start + timedelta(minutes=15 * 50),
            side="SELL",
            price=101.0,
            qty=100.0,
            notional=10100.0,
            source="test",
            raw={},
        )
    ]


def test_alt_data_research_engine_exposes_expected_families() -> None:
    engine = AltDataResearchEngine(
        symbol="TESTUSDC",
        candles_15m=_candles(),
        funding_rates=_funding_rows(),
        open_interest_rows=_oi_rows(),
        basis_rows=_basis_rows(),
        liquidation_rows=_liquidation_rows(),
        breadth_rows=_breadth_rows(),
        macro_events=_macro_events(),
    )
    keys = {spec.key for spec in engine.family_specs()}
    assert "funding_oi_squeeze_reversal" in keys
    assert "funding_oi_squeeze_reversal_v2" in keys
    assert "basis_dislocation_mean_reversion" in keys
    assert "basis_dislocation_mean_reversion_v2" in keys
    assert "oi_breakout_confirmation" in keys
    assert "oi_breakout_confirmation_v2" in keys
    assert "liquidation_cascade_absorption" in keys
    assert "breadth_divergence_rotation" in keys
    assert "event_basis_dislocation" in keys


def test_alt_data_research_summary_handles_empty_trades() -> None:
    summary = summarize_alt_data_research_trades([])
    assert summary["closed"] == 0
    assert summary["ev_r"] == 0.0
    assert summary["total_r"] == 0.0
