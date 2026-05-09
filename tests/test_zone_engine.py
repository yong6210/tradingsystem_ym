from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.db.models import Candle
from app.services.zone_engine import ZoneEngine


def make_15m_candles(n: int = 220, base: float = 50000.0) -> list[Candle]:
    ts = datetime.now(timezone.utc) - timedelta(minutes=15 * n)
    out: list[Candle] = []
    price = base
    for i in range(n):
        wave = ((i % 20) - 10) * 0.0015
        close = price * (1 + wave)
        high = max(price, close) * 1.001
        low = min(price, close) * 0.999
        out.append(
            Candle(
                symbol="BTCUSDC",
                timeframe="15m",
                ts=ts,
                o=price,
                h=high,
                l=low,
                c=close,
                v=1000 + (i % 7) * 50,
                source="test",
                is_final=True,
            )
        )
        ts += timedelta(minutes=15)
        price = close
    return out


def test_zone_engine_generates_and_merges() -> None:
    candles = make_15m_candles()
    engine = ZoneEngine()

    zones = engine.refresh(symbol="BTCUSDC", candles_15m=candles, existing=[])

    assert len(zones) > 0
    assert all(z.width_atr > 0 for z in zones)
    assert all(z.state in {"active", "weak", "expired"} for z in zones)
    assert {z.type for z in zones}.intersection({"LP", "OB", "FVG", "FLIP"})


def test_zone_engine_expires_old_zone_for_scalp() -> None:
    candles = make_15m_candles()
    engine = ZoneEngine()
    old_zone = engine.refresh(symbol="BTCUSDC", candles_15m=candles, existing=[])[0]
    old_zone.created_ts = datetime.now(timezone.utc) - timedelta(hours=30)

    refreshed = engine.refresh(symbol="BTCUSDC", candles_15m=candles, existing=[old_zone])

    carried = next((row for row in refreshed if row.zone_id == old_zone.zone_id), None)
    assert carried is None or carried.state == "expired"


def test_zone_engine_tolerates_malformed_scalp_age_setting() -> None:
    candles = make_15m_candles()
    engine = ZoneEngine()
    engine.settings.scalp_zone_hard_max_age_hours = "inf"
    old_zone = engine.refresh(symbol="BTCUSDC", candles_15m=candles, existing=[])[0]
    old_zone.created_ts = datetime.now(timezone.utc) - timedelta(hours=30)

    refreshed = engine.refresh(symbol="BTCUSDC", candles_15m=candles, existing=[old_zone])

    carried = next((row for row in refreshed if row.zone_id == old_zone.zone_id), None)
    assert carried is None or carried.state == "expired"
