import asyncio
from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.repositories import LiquidationEventRepository
from app.services.liquidation_stream_collector import LiquidationStreamCollector


class _FakeEvent:
    def __init__(self, symbol: str, side: str, ts: datetime, price: float, avg_price: float, qty: float, filled_qty: float):
        self.symbol = symbol
        self.side = side
        self.ts = ts
        self.price = price
        self.avg_price = avg_price
        self.qty = qty
        self.filled_qty = filled_qty
        self.status = "FILLED"
        self.raw = {"e": "forceOrder"}


class _FakeClient:
    async def stream_force_orders(self, symbols: list[str], *, max_events=None, timeout_seconds=None):
        yield _FakeEvent("BTCUSDC", "SELL", datetime(2026, 4, 22, 12, 0, tzinfo=UTC), 80000.0, 80010.0, 0.5, 0.5)
        yield _FakeEvent("ETHUSDC", "BUY", datetime(2026, 4, 22, 12, 1, tzinfo=UTC), 1500.0, 1498.0, 10.0, 10.0)


class _RetryingFakeClient:
    def __init__(self) -> None:
        self.calls = 0

    async def stream_force_orders(self, symbols: list[str], *, max_events=None, timeout_seconds=None):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("transient_disconnect")
        yield _FakeEvent("BTCUSDC", "SELL", datetime(2026, 4, 22, 12, 2, tzinfo=UTC), 80100.0, 80100.0, 0.25, 0.25)


def test_liquidation_stream_collector_persists_rows() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    with session_factory() as db:
        collector = LiquidationStreamCollector(
            repo=LiquidationEventRepository(db),
            client=_FakeClient(),
        )
        summary = asyncio.run(collector.capture(symbols=["BTCUSDC", "ETHUSDC"], max_events=2, timeout_seconds=1.0))
        db.commit()

        assert summary.captured_events == 2
        assert summary.inserted_rows == 2
        btc_rows = LiquidationEventRepository(db).list_range(
            symbol="BTCUSDC",
            start_ts=datetime(2026, 4, 22, 0, 0, tzinfo=UTC),
            end_ts=datetime(2026, 4, 23, 0, 0, tzinfo=UTC),
        )
        assert len(btc_rows) == 1
        assert round(float(btc_rows[0].notional), 2) == 40005.0


def test_liquidation_stream_collector_reconnects_after_transient_error() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    with session_factory() as db:
        collector = LiquidationStreamCollector(
            repo=LiquidationEventRepository(db),
            client=_RetryingFakeClient(),
        )
        summary = asyncio.run(
            collector.capture(
                symbols=["BTCUSDC"],
                max_events=1,
                timeout_seconds=1.0,
                idle_reconnect_seconds=0.1,
                reconnect_backoff_seconds=0.0,
            )
        )
        db.commit()

        assert summary.captured_events == 1
        assert summary.inserted_rows == 1
        assert summary.reconnect_count >= 1
        assert summary.last_error is None
