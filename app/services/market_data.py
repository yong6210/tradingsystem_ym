from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.core.config import get_settings
from app.db.models import Candle
from app.db.repositories import CandleRepository
from app.integrations.binance_futures import BinanceFuturesClient


class DataQualityError(ValueError):
    pass


@dataclass
class DataQualityGate:
    allow_late_seconds: int = 45

    @staticmethod
    def _as_utc(ts: datetime) -> datetime:
        if ts.tzinfo is None:
            return ts.replace(tzinfo=timezone.utc)
        return ts.astimezone(timezone.utc)

    def validate(self, new: Candle, prev: Candle | None) -> None:
        if new.h < max(new.o, new.c) or new.l > min(new.o, new.c):
            raise DataQualityError("invalid ohlc bounds")
        if new.v < 0:
            raise DataQualityError("negative volume")
        new_ts = self._as_utc(new.ts)
        prev_ts = self._as_utc(prev.ts) if prev else None
        if prev_ts and new_ts < prev_ts:
            raise DataQualityError("reverse timestamp detected")
        if prev_ts and new_ts == prev_ts and new.is_final and prev.is_final:
            return

        now = datetime.now(timezone.utc)
        if (now - new_ts).total_seconds() > 3600 * 24 * 30:
            raise DataQualityError("stale candle older than 30 days")


class MarketDataService:
    def __init__(self, candle_repo: CandleRepository):
        self.candle_repo = candle_repo
        self.settings = get_settings()
        self.quality_gate = DataQualityGate()
        self.binance = BinanceFuturesClient()

    def ingest_candle(self, payload: dict) -> Candle:
        candle = Candle(**payload)
        prev = self.candle_repo.get_last_candle(candle.symbol, candle.timeframe)
        self.quality_gate.validate(candle, prev)
        return self.candle_repo.upsert(candle)

    def recent_candles(self, symbol: str, timeframe: str, limit: int = 300) -> list[Candle]:
        return self.candle_repo.list_recent(symbol=symbol, timeframe=timeframe, limit=limit)

    def backfill_from_binance(self, symbol: str, timeframe: str, limit: int = 500) -> int:
        klines = sorted(
            self.binance.fetch_klines(symbol=symbol, interval=timeframe, limit=limit),
            key=lambda row: row.open_time,
        )
        last_candle = self.candle_repo.get_last_candle(symbol, timeframe)
        last_ts = self.quality_gate._as_utc(last_candle.ts) if last_candle else None
        ingested = 0
        for row in klines:
            if last_ts is not None and self.quality_gate._as_utc(row.open_time) < last_ts:
                continue
            payload = {
                "symbol": row.symbol,
                "timeframe": timeframe,
                "ts": row.open_time,
                "o": row.o,
                "h": row.h,
                "l": row.l,
                "c": row.c,
                "v": row.v,
                "source": "binance",
                "is_final": row.is_final,
            }
            try:
                self.ingest_candle(payload)
            except DataQualityError as exc:
                if str(exc) == "reverse timestamp detected":
                    continue
                raise
            ingested += 1
            last_ts = self.quality_gate._as_utc(row.open_time)
        return ingested

    def backfill_symbol_timeframes(
        self,
        symbol: str,
        limit_1m: int = 0,
        limit_5m: int = 500,
        limit_15m: int = 500,
    ) -> dict[str, int]:
        count_1m = self.backfill_from_binance(symbol=symbol, timeframe="1m", limit=limit_1m) if int(limit_1m) > 0 else 0
        count_5m = self.backfill_from_binance(symbol=symbol, timeframe="5m", limit=limit_5m)
        count_15m = self.backfill_from_binance(symbol=symbol, timeframe="15m", limit=limit_15m)
        return {"1m": count_1m, "5m": count_5m, "15m": count_15m, "total": count_1m + count_5m + count_15m}

    def refresh_universe(self, limit: int = 30) -> list[str]:
        return self.binance.fetch_top_usdc_perp_symbols(limit=limit)

    @staticmethod
    def default_universe(name: str = "usdc_perp_top30") -> list[str]:
        if name != "usdc_perp_top30":
            return []
        return [
            "BTCUSDC",
            "ETHUSDC",
            "SOLUSDC",
            "XRPUSDC",
            "BNBUSDC",
            "DOGEUSDC",
            "ADAUSDC",
            "AVAXUSDC",
            "LINKUSDC",
            "DOTUSDC",
            "LTCUSDC",
            "TRXUSDC",
            "BCHUSDC",
            "MATICUSDC",
            "ATOMUSDC",
            "AAVEUSDC",
            "NEARUSDC",
            "SUIUSDC",
            "APTUSDC",
            "ETCUSDC",
            "FILUSDC",
            "INJUSDC",
            "ARBUSDC",
            "OPUSDC",
            "TONUSDC",
            "RUNEUSDC",
            "SEIUSDC",
            "TIAUSDC",
            "PEPEUSDC",
            "WIFUSDC",
        ]
