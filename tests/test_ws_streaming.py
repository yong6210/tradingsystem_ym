from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from app.db.session import SessionLocal, init_db
from app.integrations.binance_futures import BinanceKline
from app.services.strategy_engine import StrategyEngine


def test_stream_binance_klines_ingests_and_refreshes() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        symbol = f"WST{int(datetime.now(timezone.utc).timestamp())}USDC"
        base = datetime.now(timezone.utc) - timedelta(minutes=15)

        async def fake_stream_klines(symbols: list[str], interval: str):
            assert symbol in symbols
            assert interval == "5m"
            for i in range(3):
                ts = base + timedelta(minutes=5 * i)
                yield BinanceKline(
                    symbol=symbol,
                    interval=interval,
                    open_time=ts,
                    close_time=ts + timedelta(minutes=5),
                    o=100.0 + i,
                    h=101.0 + i,
                    l=99.0 + i,
                    c=100.5 + i,
                    v=1000.0 + i,
                    is_final=True,
                )

        refresh_calls: list[str] = []

        engine.market_data.binance.stream_klines = fake_stream_klines  # type: ignore[assignment]
        engine.refresh_symbol = lambda s: refresh_calls.append(s) or {"symbol": s, "updated": True}  # type: ignore[assignment]

        payload = asyncio.run(
            engine.stream_binance_klines(
                symbols=[symbol],
                intervals=["5m"],
                refresh_on_final=True,
                max_messages=3,
            )
        )

        candles = engine.market_data.recent_candles(symbol=symbol, timeframe="5m", limit=10)
        assert payload["processed_messages"] == 3
        assert payload["committed_candles"] == 3
        assert payload["ingest_errors"] == 0
        assert payload["last_ingest_success_at"]
        assert len(candles) >= 3
        assert refresh_calls


def test_stream_binance_klines_handles_empty_input() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        payload = asyncio.run(engine.stream_binance_klines(symbols=[], intervals=["5m"], max_messages=1))
        assert payload["running"] is False
        assert payload["reason"] == "empty_symbols_or_intervals"


def test_stream_binance_klines_records_progress_callback_errors() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        symbol = f"WSCB{int(datetime.now(timezone.utc).timestamp())}USDC"
        base = datetime.now(timezone.utc) - timedelta(minutes=5)

        async def fake_stream_klines(symbols: list[str], interval: str):
            yield BinanceKline(
                symbol=symbol,
                interval=interval,
                open_time=base,
                close_time=base + timedelta(minutes=5),
                o=100.0,
                h=101.0,
                l=99.0,
                c=100.5,
                v=1000.0,
                is_final=True,
            )

        def failing_progress_callback(_stats: dict) -> None:
            raise RuntimeError("heartbeat_write_failed")

        engine.market_data.binance.stream_klines = fake_stream_klines  # type: ignore[assignment]
        engine.refresh_symbol = lambda s: {"symbol": s, "updated": True}  # type: ignore[assignment]

        payload = asyncio.run(
            engine.stream_binance_klines(
                symbols=[symbol],
                intervals=["5m"],
                refresh_on_final=False,
                max_messages=1,
                progress_callback=failing_progress_callback,
            )
        )

        assert payload["processed_messages"] == 1
        assert payload["progress_callback_errors"] >= 1
        assert payload["last_progress_callback_error"] == "RuntimeError:heartbeat_write_failed"
