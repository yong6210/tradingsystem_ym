from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.core.config import CURRENT_MICRO_LIVE_USDT_SYMBOLS, get_settings
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

    def validate(self, new: Candle, prev: Candle | None, *, allow_stale: bool = False) -> None:
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
        if not allow_stale and (now - new_ts).total_seconds() > 3600 * 24 * 30:
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

    def backfill_history_before_latest(
        self,
        *,
        symbol: str,
        timeframe: str,
        limit: int = 1500,
        batches: int = 1,
    ) -> int:
        earliest_candle = self.candle_repo.get_first_candle(symbol, timeframe)
        if earliest_candle is None:
            return 0

        earliest_ts = self.quality_gate._as_utc(earliest_candle.ts)
        ingested = 0
        remaining_batches = max(1, int(batches))
        while earliest_ts is not None and remaining_batches > 0:
            end_time_ms = int((earliest_ts - timedelta(milliseconds=1)).timestamp() * 1000)
            klines = sorted(
                self.binance.fetch_klines(
                    symbol=symbol,
                    interval=timeframe,
                    limit=limit,
                    end_time_ms=end_time_ms,
                ),
                key=lambda row: row.open_time,
            )
            older_rows = [
                row
                for row in klines
                if self.quality_gate._as_utc(row.open_time) < earliest_ts
            ]
            if not older_rows:
                break
            prev_candle: Candle | None = None
            for row in older_rows:
                candle = Candle(
                    symbol=row.symbol,
                    timeframe=timeframe,
                    ts=row.open_time,
                    o=row.o,
                    h=row.h,
                    l=row.l,
                    c=row.c,
                    v=row.v,
                    source="binance",
                    is_final=row.is_final,
                )
                try:
                    self.quality_gate.validate(candle, prev_candle, allow_stale=True)
                except DataQualityError as exc:
                    if str(exc) == "reverse timestamp detected":
                        continue
                    raise
                self.candle_repo.upsert(candle)
                ingested += 1
                prev_candle = candle
            earliest_ts = min(self.quality_gate._as_utc(row.open_time) for row in older_rows)
            remaining_batches -= 1
        return ingested

    def backfill_symbol_timeframes(
        self,
        symbol: str,
        limit_1m: int = 0,
        limit_5m: int = 500,
        limit_15m: int = 500,
        history_batches_1m: int = 0,
        history_batches_5m: int = 0,
        history_batches_15m: int = 0,
        min_1m_history_candles: int = 0,
    ) -> dict[str, int]:
        count_1m = self.backfill_from_binance(symbol=symbol, timeframe="1m", limit=limit_1m) if int(limit_1m) > 0 else 0
        count_5m = self.backfill_from_binance(symbol=symbol, timeframe="5m", limit=limit_5m)
        count_15m = self.backfill_from_binance(symbol=symbol, timeframe="15m", limit=limit_15m)
        min_1m_history = max(0, int(min_1m_history_candles))
        current_1m_count = (
            len(self.candle_repo.list_recent(symbol=symbol, timeframe="1m", limit=min_1m_history))
            if min_1m_history > 0
            else 0
        )
        history_1m = (
            self.backfill_history_before_latest(
                symbol=symbol,
                timeframe="1m",
                limit=limit_1m,
                batches=history_batches_1m,
            )
            if int(limit_1m) > 0
            and int(history_batches_1m) > 0
            and (min_1m_history <= 0 or current_1m_count < min_1m_history)
            else 0
        )
        history_5m = (
            self.backfill_history_before_latest(
                symbol=symbol,
                timeframe="5m",
                limit=limit_5m,
                batches=history_batches_5m,
            )
            if int(history_batches_5m) > 0
            else 0
        )
        history_15m = (
            self.backfill_history_before_latest(
                symbol=symbol,
                timeframe="15m",
                limit=limit_15m,
                batches=history_batches_15m,
            )
            if int(history_batches_15m) > 0
            else 0
        )
        return {
            "1m": count_1m,
            "5m": count_5m,
            "15m": count_15m,
            "history_1m": history_1m,
            "history_5m": history_5m,
            "history_15m": history_15m,
            "total": count_1m + count_5m + count_15m + history_1m + history_5m + history_15m,
        }

    def refresh_universe(self, limit: int = 30, *, quote_asset: str | None = None) -> list[str]:
        quote = str(quote_asset or "").strip().upper()
        if not quote:
            universe_name = str(getattr(self.settings, "universe_name", "") or "").strip().lower()
            quote = "USDT" if "usdt" in universe_name else "USDC"
        return self.binance.fetch_top_perp_symbols(quote_asset=quote, limit=limit)

    @staticmethod
    def default_universe(name: str = "usdt_reliable_balanced_31") -> list[str]:
        normalized = str(name or "").strip().lower()
        if normalized == "usdt_reliable_balanced_31":
            return [item for item in CURRENT_MICRO_LIVE_USDT_SYMBOLS.split(",") if item]
        if normalized != "usdc_perp_top30":
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
