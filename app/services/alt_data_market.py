from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo
import re

from statistics import mean, pstdev

import httpx

from app.db.models import BasisSnapshot, CrossAssetBreadthSnapshot, FundingRateSnapshot, MacroEvent, OpenInterestSnapshot
from app.db.repositories import BasisSnapshotRepository, CandleRepository, CrossAssetBreadthRepository, FundingRateRepository, MacroEventRepository, OpenInterestRepository
from app.integrations.binance_futures import BinanceFuturesClient


@dataclass(slots=True)
class AltDataBackfillSummary:
    symbol: str
    funding_rows: int = 0
    open_interest_rows: int = 0
    basis_rows: int = 0
    breadth_rows: int = 0
    macro_event_rows: int = 0


class AltDataMarketService:
    def __init__(
        self,
        *,
        funding_repo: FundingRateRepository,
        open_interest_repo: OpenInterestRepository,
        basis_repo: BasisSnapshotRepository,
        macro_event_repo: MacroEventRepository | None = None,
        candle_repo: CandleRepository | None = None,
        breadth_repo: CrossAssetBreadthRepository | None = None,
        client: BinanceFuturesClient | None = None,
    ):
        self.funding_repo = funding_repo
        self.open_interest_repo = open_interest_repo
        self.basis_repo = basis_repo
        self.macro_event_repo = macro_event_repo
        self.candle_repo = candle_repo
        self.breadth_repo = breadth_repo
        self.binance = client or BinanceFuturesClient()
        self._ny_tz = ZoneInfo("America/New_York")

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @staticmethod
    def _ms(value: datetime) -> int:
        return int(AltDataMarketService._utc(value).timestamp() * 1000)

    @staticmethod
    def _pct_change(values: list[float], idx: int, lookback: int) -> float:
        prev_idx = max(idx - lookback, 0)
        prev = float(values[prev_idx])
        current = float(values[idx])
        if abs(prev) <= 1e-9:
            return 0.0
        return float((current - prev) / abs(prev))

    @staticmethod
    def _zscore(values: list[float], idx: int, lookback: int) -> float:
        start = max(0, idx - lookback)
        window = values[start:idx]
        if len(window) < max(20, lookback // 3):
            return 0.0
        avg = mean(window)
        std = pstdev(window)
        if std <= 1e-9:
            return 0.0
        return float((values[idx] - avg) / std)

    def backfill_macro_events(self, *, lookback_days: int = 730) -> int:
        if self.macro_event_repo is None:
            raise RuntimeError("macro_event_backfill_requires_macro_event_repo")

        url = "https://www.federalreserve.gov/newsevents/pressreleases/monetary20240809a.htm"
        headers = {"User-Agent": "Mozilla/5.0 trading-research-bot"}
        with httpx.Client(timeout=30.0, headers=headers, follow_redirects=True) as client:
            response = client.get(url)
            response.raise_for_status()
            html = response.text

        section_pattern = re.compile(r"<p>For\s+(\d{4}):</p>\s*<ul>(.*?)</ul>", re.IGNORECASE | re.DOTALL)
        item_pattern = re.compile(
            r"<li>Tuesday,\s+([A-Za-z]+)\s+(\d{1,2}),\s+and\s+Wednesday,\s+([A-Za-z]+)\s+(\d{1,2})(?:,\s*(\d{4}))?</li>",
            re.IGNORECASE,
        )
        sections = section_pattern.findall(html)
        if not sections:
            return 0

        now = datetime.now(UTC)
        cutoff = now - timedelta(days=max(int(lookback_days), 1))
        ingest_count = 0
        for section_year_text, section_html in sections:
            section_year = int(section_year_text)
            for month1, day1, month2, day2, explicit_year in item_pattern.findall(section_html):
                year = int(explicit_year) if explicit_year else section_year
                try:
                    event_local = datetime.strptime(f"{month2} {day2} {year} 14:00", "%B %d %Y %H:%M").replace(tzinfo=self._ny_tz)
                except ValueError:
                    continue
                event_ts = event_local.astimezone(UTC)
                if event_ts < cutoff:
                    continue
                self.macro_event_repo.upsert(
                    MacroEvent(
                        event_ts=event_ts,
                        event_code="FOMC_RATE_DECISION",
                        importance="high",
                        country="US",
                        title="FOMC rate decision / statement",
                        source="federalreserve",
                        raw={
                            "source_url": url,
                            "meeting_start": f"{month1} {day1}, {year}",
                            "meeting_end": f"{month2} {day2}, {year}",
                        },
                    )
                )
                ingest_count += 1
        return ingest_count

    def backfill_funding_rates(self, *, symbol: str, lookback_days: int = 365, limit: int = 1000) -> int:
        symbol = symbol.upper()
        now = datetime.now(UTC)
        last = self.funding_repo.get_last(symbol)
        cursor = self._utc(last.ts) + timedelta(milliseconds=1) if last is not None else now - timedelta(days=lookback_days)
        end = now
        ingested = 0
        while cursor <= end:
            rows = self.binance.fetch_funding_rates(
                symbol=symbol,
                limit=limit,
                start_time_ms=self._ms(cursor),
                end_time_ms=self._ms(end),
            )
            if not rows:
                break
            for row in rows:
                self.funding_repo.upsert(
                    FundingRateSnapshot(
                        symbol=symbol,
                        ts=row.ts,
                        funding_rate=row.funding_rate,
                        mark_price=row.mark_price,
                        source="binance",
                        raw=row.raw,
                    )
                )
                ingested += 1
            next_cursor = max(self._utc(row.ts) for row in rows) + timedelta(milliseconds=1)
            if next_cursor <= cursor:
                break
            cursor = next_cursor
            if len(rows) < limit:
                break
        return ingested

    def backfill_open_interest(
        self,
        *,
        symbol: str,
        period: str = "15m",
        lookback_days: int = 365,
        limit: int = 500,
    ) -> int:
        symbol = symbol.upper()
        now = datetime.now(UTC)
        last = self.open_interest_repo.get_last(symbol, period)
        cutoff = self._utc(last.ts) + timedelta(milliseconds=1) if last is not None else now - timedelta(days=lookback_days)
        cursor_end = now
        ingested = 0
        while cursor_end >= cutoff:
            rows = self.binance.fetch_open_interest_hist(
                symbol=symbol,
                period=period,
                limit=limit,
                end_time_ms=self._ms(cursor_end),
            )
            if not rows:
                break
            eligible_rows = sorted((row for row in rows if self._utc(row.ts) >= cutoff), key=lambda item: self._utc(item.ts))
            for row in eligible_rows:
                self.open_interest_repo.upsert(
                    OpenInterestSnapshot(
                        symbol=symbol,
                        period=period,
                        ts=row.ts,
                        open_interest=row.open_interest,
                        open_interest_value=row.open_interest_value,
                        source="binance",
                        raw=row.raw,
                    )
                )
                ingested += 1
            oldest_ts = min(self._utc(row.ts) for row in rows)
            if oldest_ts <= cutoff:
                break
            if len(rows) < limit:
                break
            next_cursor_end = oldest_ts - timedelta(milliseconds=1)
            if next_cursor_end >= cursor_end:
                break
            cursor_end = next_cursor_end
        return ingested

    def backfill_basis(
        self,
        *,
        symbol: str,
        timeframe: str = "15m",
        lookback_days: int = 365,
        limit: int = 1500,
    ) -> int:
        symbol = symbol.upper()
        now = datetime.now(UTC)
        last = self.basis_repo.get_last(symbol, timeframe)
        cursor = self._utc(last.ts) + timedelta(milliseconds=1) if last is not None else now - timedelta(days=lookback_days)
        end = now
        ingested = 0
        while cursor <= end:
            rows = self.binance.fetch_premium_index_klines(
                symbol=symbol,
                interval=timeframe,
                limit=limit,
                start_time_ms=self._ms(cursor),
                end_time_ms=self._ms(end),
            )
            if not rows:
                break
            for row in rows:
                self.basis_repo.upsert(
                    BasisSnapshot(
                        symbol=symbol,
                        timeframe=timeframe,
                        ts=row.open_time,
                        basis_open=row.basis_open,
                        basis_high=row.basis_high,
                        basis_low=row.basis_low,
                        basis_close=row.basis_close,
                        basis_bps=float(row.basis_close) * 10000.0,
                        source="binance",
                        raw={"kline": row.raw},
                    )
                )
                ingested += 1
            next_cursor = max(self._utc(row.open_time) for row in rows) + timedelta(minutes=1)
            if next_cursor <= cursor:
                break
            cursor = next_cursor
            if len(rows) < limit:
                break
        return ingested

    def backfill_cross_asset_breadth(
        self,
        *,
        leader_symbol: str,
        confirm_symbol: str,
        timeframe: str = "15m",
        lookback_days: int = 365,
    ) -> int:
        if self.candle_repo is None or self.breadth_repo is None:
            raise RuntimeError("cross_asset_breadth_requires_candle_repo_and_breadth_repo")

        leader_symbol = leader_symbol.upper()
        confirm_symbol = confirm_symbol.upper()
        leader_last_candle = self.candle_repo.get_last_candle(leader_symbol, timeframe)
        confirm_last_candle = self.candle_repo.get_last_candle(confirm_symbol, timeframe)
        if leader_last_candle is None or confirm_last_candle is None:
            return 0
        end_ts = min(self._utc(leader_last_candle.ts), self._utc(confirm_last_candle.ts))
        last = self.breadth_repo.get_last(
            leader_symbol=leader_symbol,
            confirm_symbol=confirm_symbol,
            timeframe=timeframe,
        )
        start = self._utc(last.ts) - timedelta(days=2) if last is not None else end_ts - timedelta(days=lookback_days)
        leader_candles = self.candle_repo.list_range(symbol=leader_symbol, timeframe=timeframe, start_ts=start, end_ts=end_ts)
        confirm_candles = self.candle_repo.list_range(symbol=confirm_symbol, timeframe=timeframe, start_ts=start, end_ts=end_ts)
        if not leader_candles or not confirm_candles:
            return 0

        confirm_by_ts = {self._utc(item.ts): item for item in confirm_candles}
        aligned_ts: list[datetime] = []
        leader_closes: list[float] = []
        confirm_closes: list[float] = []
        for candle in leader_candles:
            ts = self._utc(candle.ts)
            paired = confirm_by_ts.get(ts)
            if paired is None:
                continue
            aligned_ts.append(ts)
            leader_closes.append(float(candle.c))
            confirm_closes.append(float(paired.c))

        if len(aligned_ts) < 32:
            return 0

        divergence_series: list[float] = []
        ingested = 0
        for idx, ts in enumerate(aligned_ts):
            leader_ret_1h = self._pct_change(leader_closes, idx, 4)
            confirm_ret_1h = self._pct_change(confirm_closes, idx, 4)
            leader_ret_4h = self._pct_change(leader_closes, idx, 16)
            confirm_ret_4h = self._pct_change(confirm_closes, idx, 16)
            divergence_bps = float((leader_ret_4h - confirm_ret_4h) * 10000.0)
            divergence_series.append(divergence_bps)
            breadth_score = self._zscore(divergence_series, idx, 96)
            self.breadth_repo.upsert(
                CrossAssetBreadthSnapshot(
                    leader_symbol=leader_symbol,
                    confirm_symbol=confirm_symbol,
                    timeframe=timeframe,
                    ts=ts,
                    leader_close=leader_closes[idx],
                    confirm_close=confirm_closes[idx],
                    leader_ret_1h=leader_ret_1h,
                    confirm_ret_1h=confirm_ret_1h,
                    leader_ret_4h=leader_ret_4h,
                    confirm_ret_4h=confirm_ret_4h,
                    divergence_bps=divergence_bps,
                    breadth_score=breadth_score,
                    source="derived",
                    raw={
                        "leader_symbol": leader_symbol,
                        "confirm_symbol": confirm_symbol,
                        "leader_ret_1h": leader_ret_1h,
                        "confirm_ret_1h": confirm_ret_1h,
                        "leader_ret_4h": leader_ret_4h,
                        "confirm_ret_4h": confirm_ret_4h,
                    },
                )
            )
            ingested += 1
        return ingested

    def backfill_symbol_alt_data(
        self,
        *,
        symbol: str,
        lookback_days: int = 365,
        oi_period: str = "15m",
        basis_timeframe: str = "15m",
    ) -> AltDataBackfillSummary:
        return AltDataBackfillSummary(
            symbol=symbol.upper(),
            funding_rows=self.backfill_funding_rates(symbol=symbol, lookback_days=lookback_days),
            open_interest_rows=self.backfill_open_interest(
                symbol=symbol,
                period=oi_period,
                lookback_days=lookback_days,
            ),
            basis_rows=self.backfill_basis(
                symbol=symbol,
                timeframe=basis_timeframe,
                lookback_days=lookback_days,
            ),
            macro_event_rows=0,
        )
