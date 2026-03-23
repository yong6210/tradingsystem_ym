from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from app.db.models import Candle
from app.db.repositories import CandleRepository


class DemoDataService:
    def __init__(self, candle_repo: CandleRepository):
        self.candle_repo = candle_repo

    def seed_symbol(self, symbol: str, bars_5m: int = 500, start_price: float = 50000.0) -> None:
        rng = random.Random(f"{symbol}-{bars_5m}-{start_price}")
        now = datetime.now(timezone.utc)
        price = start_price
        candles_5m: list[Candle] = []
        ts = now - timedelta(minutes=5 * bars_5m)

        for i in range(bars_5m):
            drift = 0.00015 if i % 100 < 50 else -0.0001
            noise = rng.uniform(-0.004, 0.004)
            ret = drift + noise
            close = max(1.0, price * (1 + ret))

            high = max(price, close) * (1 + rng.uniform(0.0, 0.0015))
            low = min(price, close) * (1 - rng.uniform(0.0, 0.0015))
            volume = rng.uniform(100.0, 2000.0)

            candles_5m.append(
                Candle(
                    symbol=symbol,
                    timeframe="5m",
                    ts=ts,
                    o=price,
                    h=high,
                    l=low,
                    c=close,
                    v=volume,
                    source="demo",
                    is_final=True,
                )
            )
            price = close
            ts += timedelta(minutes=5)

        for row in candles_5m:
            self.candle_repo.upsert(row)

        # Build 15m candles from 5m stream.
        for i in range(0, len(candles_5m), 3):
            chunk = candles_5m[i : i + 3]
            if len(chunk) < 3:
                continue
            candle_15m = Candle(
                symbol=symbol,
                timeframe="15m",
                ts=chunk[0].ts,
                o=chunk[0].o,
                h=max(x.h for x in chunk),
                l=min(x.l for x in chunk),
                c=chunk[-1].c,
                v=sum(x.v for x in chunk),
                source="demo",
                is_final=True,
            )
            self.candle_repo.upsert(candle_15m)
