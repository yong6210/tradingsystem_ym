from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.db.repositories import CandleRepository
from app.db.session import SessionLocal, init_db
from app.integrations.binance_futures import BinanceKline
from app.db.models import Candle
from app.services.market_data import DataQualityError, DataQualityGate, MarketDataService


def _candle(*, ts: datetime, close: float = 100.0) -> Candle:
    return Candle(
        symbol="QTESTUSDC",
        timeframe="5m",
        ts=ts,
        o=close - 0.3,
        h=close + 0.4,
        l=close - 0.6,
        c=close,
        v=1000.0,
        source="test",
        is_final=True,
    )


def test_quality_gate_handles_naive_prev_timestamp() -> None:
    gate = DataQualityGate()
    prev = _candle(ts=datetime.now(timezone.utc).replace(tzinfo=None))
    new = _candle(ts=datetime.now(timezone.utc) + timedelta(minutes=5))
    gate.validate(new, prev)


def test_quality_gate_detects_reverse_timestamp_after_normalization() -> None:
    gate = DataQualityGate()
    prev = _candle(ts=datetime.now(timezone.utc).replace(tzinfo=None))
    new = _candle(ts=datetime.now(timezone.utc) - timedelta(minutes=5))
    with pytest.raises(DataQualityError):
        gate.validate(new, prev)


def test_candle_repository_upsert_handles_duplicate_key_in_same_transaction() -> None:
    init_db()
    symbol = f"DUPX{uuid4().hex[:6].upper()}USDC"
    base = datetime(2026, 3, 9, 0, 0, tzinfo=timezone.utc)

    with SessionLocal() as db:
        repo = CandleRepository(db)
        repo.upsert(
            Candle(
                symbol=symbol,
                timeframe="1m",
                ts=base,
                o=100.0,
                h=101.0,
                l=99.5,
                c=100.5,
                v=1000.0,
                source="first",
                is_final=False,
            )
        )
        repo.upsert(
            Candle(
                symbol=symbol,
                timeframe="1m",
                ts=base,
                o=100.1,
                h=101.2,
                l=99.4,
                c=100.9,
                v=1200.0,
                source="second",
                is_final=True,
            )
        )

        db.commit()

        candles = repo.list_recent(symbol=symbol, timeframe="1m", limit=10)

        assert len(candles) == 1
        assert candles[0].c == 100.9
        assert candles[0].v == 1200.0
        assert candles[0].source == "second"
        assert candles[0].is_final is True


def test_backfill_from_binance_skips_older_overlap_rows() -> None:
    init_db()
    symbol = f"OVLP{uuid4().hex[:6].upper()}USDC"
    base = datetime(2026, 3, 9, 0, 0, tzinfo=timezone.utc)

    with SessionLocal() as db:
        repo = CandleRepository(db)
        repo.upsert(
            Candle(
                symbol=symbol,
                timeframe="5m",
                ts=base + timedelta(minutes=10),
                o=100.0,
                h=101.0,
                l=99.0,
                c=100.5,
                v=1000.0,
                source="seed",
                is_final=True,
            )
        )
        db.commit()

        service = MarketDataService(repo)
        service.binance.fetch_klines = lambda **kwargs: [  # type: ignore[assignment]
            BinanceKline(symbol=symbol, interval="5m", open_time=base, close_time=base + timedelta(minutes=5), o=99.0, h=100.0, l=98.5, c=99.5, v=1000.0, is_final=True),
            BinanceKline(symbol=symbol, interval="5m", open_time=base + timedelta(minutes=5), close_time=base + timedelta(minutes=10), o=99.5, h=100.5, l=99.0, c=100.0, v=1100.0, is_final=True),
            BinanceKline(symbol=symbol, interval="5m", open_time=base + timedelta(minutes=10), close_time=base + timedelta(minutes=15), o=100.0, h=101.0, l=99.5, c=100.5, v=1200.0, is_final=True),
            BinanceKline(symbol=symbol, interval="5m", open_time=base + timedelta(minutes=15), close_time=base + timedelta(minutes=20), o=100.5, h=101.5, l=100.0, c=101.0, v=1300.0, is_final=True),
        ]

        ingested = service.backfill_from_binance(symbol=symbol, timeframe="5m", limit=4)
        db.commit()

        candles = repo.list_recent(symbol=symbol, timeframe="5m", limit=10)

        assert ingested == 2
        assert [DataQualityGate._as_utc(row.ts) for row in candles] == [
            base + timedelta(minutes=10),
            base + timedelta(minutes=15),
        ]


def test_backfill_from_binance_returns_zero_when_all_rows_are_older_than_latest() -> None:
    init_db()
    symbol = f"OVLA{uuid4().hex[:6].upper()}USDC"
    base = datetime(2026, 3, 9, 0, 0, tzinfo=timezone.utc)

    with SessionLocal() as db:
        repo = CandleRepository(db)
        repo.upsert(
            Candle(
                symbol=symbol,
                timeframe="15m",
                ts=base + timedelta(minutes=45),
                o=100.0,
                h=102.0,
                l=99.0,
                c=101.0,
                v=2000.0,
                source="seed",
                is_final=True,
            )
        )
        db.commit()

        service = MarketDataService(repo)
        service.binance.fetch_klines = lambda **kwargs: [  # type: ignore[assignment]
            BinanceKline(symbol=symbol, interval="15m", open_time=base, close_time=base + timedelta(minutes=15), o=95.0, h=96.0, l=94.5, c=95.5, v=1500.0, is_final=True),
            BinanceKline(symbol=symbol, interval="15m", open_time=base + timedelta(minutes=15), close_time=base + timedelta(minutes=30), o=95.5, h=97.0, l=95.0, c=96.5, v=1600.0, is_final=True),
        ]

        ingested = service.backfill_from_binance(symbol=symbol, timeframe="15m", limit=2)
        db.commit()

        candles = repo.list_recent(symbol=symbol, timeframe="15m", limit=10)

        assert ingested == 0
        assert len(candles) == 1
        assert DataQualityGate._as_utc(candles[0].ts) == base + timedelta(minutes=45)
