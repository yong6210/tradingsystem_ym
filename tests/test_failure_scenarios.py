from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete

from app.db.models import EventOutbox
from app.db.session import SessionLocal, init_db
from app.integrations.binance_futures import BinanceKline
from app.services.event_bus import EventBus
from app.services.strategy_engine import StrategyEngine


def test_event_bus_reprocess_recovers_from_backend_failure() -> None:
    init_db()
    with SessionLocal() as db:
        db.execute(delete(EventOutbox))
        db.commit()

        bus = EventBus(db)
        bus.settings.event_retry_backoff_seconds = 0

        class FailingBackend:
            def publish(self, event) -> None:
                raise RuntimeError("forced_publish_failure")

        class OkBackend:
            def publish(self, event) -> None:
                return None

        bus.backend = FailingBackend()
        row = bus.publish("zone.created", {"symbol": "BTCUSDC", "dedupe_key": "recover:1"})
        db.commit()
        assert row.status == "failed"

        bus.backend = OkBackend()
        result = bus.reprocess_pending(limit=10)
        db.commit()

        refreshed = db.get(EventOutbox, row.event_id)
        assert refreshed is not None
        assert refreshed.status == "published"
        assert result["published"] == 1


def test_ws_stream_reconnects_after_runtime_error() -> None:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        symbol = f"WSR{int(datetime.now(timezone.utc).timestamp())}USDC"
        base = datetime.now(timezone.utc) - timedelta(minutes=5)
        calls = {"count": 0}

        async def flaky_stream(symbols: list[str], interval: str):
            calls["count"] += 1
            if calls["count"] == 1:
                raise RuntimeError("transient_ws_error")
            yield BinanceKline(
                symbol=symbol,
                interval=interval,
                open_time=base,
                close_time=base + timedelta(minutes=5),
                o=101.0,
                h=102.0,
                l=100.0,
                c=101.5,
                v=123.0,
                is_final=True,
            )

        engine.market_data.binance.stream_klines = flaky_stream  # type: ignore[assignment]
        engine.settings.ws_reconnect_base_seconds = 0.0
        engine.settings.ws_reconnect_max_seconds = 0.0
        engine.refresh_symbol = lambda s: {"symbol": s, "updated": True}  # type: ignore[assignment]

        payload = asyncio.run(
            engine.stream_binance_klines(
                symbols=[symbol],
                intervals=["5m"],
                refresh_on_final=False,
                max_messages=1,
            )
        )

        assert payload["processed_messages"] == 1
        assert payload["reconnects"] >= 1
