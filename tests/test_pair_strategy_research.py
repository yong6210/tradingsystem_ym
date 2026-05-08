from datetime import UTC, datetime, timedelta

from app.db.models import Candle
from app.services.pair_strategy_research import PairStrategyResearchEngine, summarize_pair_trades


def _pair_candles() -> tuple[list[Candle], list[Candle]]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    leader: list[Candle] = []
    confirmer: list[Candle] = []
    price_a = 100.0
    price_b = 100.0
    for idx in range(120):
        price_a += 0.05
        price_b += 0.04
        leader.append(
            Candle(
                symbol="BTCUSDC",
                timeframe="15m",
                ts=start + timedelta(minutes=15 * idx),
                o=price_a,
                h=price_a + 0.7,
                l=price_a - 0.7,
                c=price_a + 0.1,
                v=1000 + idx,
                source="test",
                is_final=True,
            )
        )
        confirmer.append(
            Candle(
                symbol="ETHUSDC",
                timeframe="15m",
                ts=start + timedelta(minutes=15 * idx),
                o=price_b,
                h=price_b + 0.6,
                l=price_b - 0.6,
                c=price_b + 0.08,
                v=900 + idx,
                source="test",
                is_final=True,
            )
        )
    return leader, confirmer


def test_pair_strategy_engine_builds_and_runs() -> None:
    leader, confirmer = _pair_candles()
    engine = PairStrategyResearchEngine(
        leader_symbol="BTCUSDC",
        confirmer_symbol="ETHUSDC",
        leader_candles=leader,
        confirmer_candles=confirmer,
    )
    trades = engine.backtest_smt_divergence()
    summary = summarize_pair_trades(trades)
    assert "closed" in summary
    assert "ev_r" in summary
