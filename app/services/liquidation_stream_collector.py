from __future__ import annotations

import asyncio
from dataclasses import dataclass
from time import monotonic

from app.db.models import LiquidationEvent
from app.db.repositories import LiquidationEventRepository
from app.integrations.binance_futures import BinanceFuturesClient, BinanceLiquidationOrder


@dataclass(slots=True)
class LiquidationCaptureSummary:
    symbols: list[str]
    captured_events: int = 0
    inserted_rows: int = 0
    reconnect_count: int = 0
    last_error: str | None = None


class LiquidationStreamCollector:
    def __init__(
        self,
        *,
        repo: LiquidationEventRepository,
        client: BinanceFuturesClient | None = None,
    ):
        self.repo = repo
        self.client = client or BinanceFuturesClient()

    @staticmethod
    def _notional(event: BinanceLiquidationOrder) -> float:
        price = float(event.avg_price or event.price or 0.0)
        qty = float(event.filled_qty or event.qty or 0.0)
        return float(price * qty)

    async def capture(
        self,
        *,
        symbols: list[str],
        max_events: int | None = None,
        timeout_seconds: float | None = None,
        idle_reconnect_seconds: float = 300.0,
        reconnect_backoff_seconds: float = 2.0,
    ) -> LiquidationCaptureSummary:
        normalized_symbols = [str(item).upper() for item in symbols if str(item).strip()]
        summary = LiquidationCaptureSummary(symbols=normalized_symbols)

        if not normalized_symbols:
            return summary

        deadline = monotonic() + float(timeout_seconds) if timeout_seconds is not None else None
        idle_timeout = max(float(idle_reconnect_seconds), 1.0)
        reconnect_backoff = max(float(reconnect_backoff_seconds), 0.0)

        while max_events is None or summary.captured_events < max_events:
            if deadline is not None:
                remaining_total = deadline - monotonic()
                if remaining_total <= 0.0:
                    break
                per_attempt_timeout = min(idle_timeout, remaining_total)
            else:
                per_attempt_timeout = idle_timeout

            remaining_events = None if max_events is None else max(max_events - summary.captured_events, 0)
            if remaining_events == 0:
                break

            try:
                async for event in self.client.stream_force_orders(
                    normalized_symbols,
                    max_events=remaining_events,
                    timeout_seconds=per_attempt_timeout,
                ):
                    summary.captured_events += 1
                    self.repo.upsert(
                        LiquidationEvent(
                            symbol=event.symbol,
                            ts=event.ts,
                            side=event.side,
                            price=float(event.avg_price or event.price or 0.0),
                            qty=float(event.filled_qty or event.qty or 0.0),
                            notional=self._notional(event),
                            source="binance_force_order_ws",
                            raw=event.raw,
                        )
                    )
                    summary.inserted_rows += 1
                    summary.last_error = None
                if deadline is not None and deadline - monotonic() <= 0.0:
                    break
            except Exception as exc:
                summary.reconnect_count += 1
                summary.last_error = f"{type(exc).__name__}: {exc}"
                if deadline is not None and deadline - monotonic() <= 0.0:
                    break
                if reconnect_backoff > 0.0:
                    await asyncio.sleep(reconnect_backoff)
                continue

            if deadline is None and max_events is not None and summary.captured_events >= max_events:
                break
            if deadline is None and max_events is None:
                # Infinite capture mode should still periodically reconnect on idle windows.
                summary.reconnect_count += 1
            elif deadline is not None and deadline - monotonic() > 0.0:
                summary.reconnect_count += 1

        return summary
