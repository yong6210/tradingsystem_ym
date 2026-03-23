from __future__ import annotations

import os

import pytest

from app.integrations.binance_futures import BinanceFuturesClient


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BINANCE_LIVE") != "1",
    reason="Set RUN_BINANCE_LIVE=1 to run real Binance integration checks",
)


def test_binance_live_fetch_klines() -> None:
    client = BinanceFuturesClient(timeout_seconds=5.0)
    rows = client.fetch_klines(symbol="BTCUSDC", interval="5m", limit=5)

    assert rows
    assert len(rows) <= 5
    assert all(row.symbol == "BTCUSDC" for row in rows)
    assert all(row.open_time < row.close_time for row in rows)
