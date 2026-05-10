from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Callable, Protocol

from sqlalchemy.orm import Session

from app.services.market_data import DataQualityError, MarketDataService


class AutoRouteSymbol(Protocol):
    def __call__(self, *, symbol: str) -> dict[str, Any]: ...


class AutoRouteSessionImpulseRetestPlans(Protocol):
    def __call__(self, *, symbol: str, plan_ids: list[str]) -> dict[str, Any]: ...


ProgressCallback = Callable[[dict[str, Any]], Any]
RefreshSymbol = Callable[[str], dict[str, Any]]


class RuntimeKlineStreamService:
    """Owns live kline ingestion, refresh, and auto-route telemetry.

    StrategyEngine keeps the public orchestration API, but the long-running
    websocket loop lives here so runtime behavior can be tested and evolved
    without expanding the engine god object.
    """

    def __init__(
        self,
        *,
        db: Session,
        market_data: MarketDataService,
        settings: Any,
        refresh_symbol: RefreshSymbol,
        auto_route_symbol: AutoRouteSymbol,
        auto_route_session_impulse_retest_plans: AutoRouteSessionImpulseRetestPlans,
    ):
        self.db = db
        self.market_data = market_data
        self.settings = settings
        self.refresh_symbol = refresh_symbol
        self.auto_route_symbol = auto_route_symbol
        self.auto_route_session_impulse_retest_plans = auto_route_session_impulse_retest_plans

    async def stream(
        self,
        *,
        symbols: list[str],
        intervals: list[str] | tuple[str, ...] = ("1m", "5m", "15m"),
        refresh_on_final: bool = True,
        max_messages: int | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        symbols = sorted({s.upper() for s in symbols if s})
        selected_intervals = [iv for iv in intervals if iv in {"1m", "5m", "15m"}]
        if not symbols or not selected_intervals:
            return {
                "running": False,
                "reason": "empty_symbols_or_intervals",
                "symbols": symbols,
                "intervals": selected_intervals,
            }

        stats: dict[str, Any] = {
            "running": True,
            "symbols": symbols,
            "intervals": selected_intervals,
            "processed_messages": 0,
            "committed_candles": 0,
            "ingest_errors": 0,
            "skipped_reverse_timestamp": 0,
            "refresh_calls": 0,
            "refresh_errors": 0,
            "auto_route_calls": 0,
            "auto_route_submit_calls": 0,
            "auto_route_intents_created": 0,
            "auto_route_errors": 0,
            "progress_callback_errors": 0,
            "reconnects": 0,
            "per_interval": {iv: 0 for iv in selected_intervals},
            "per_symbol": {symbol: 0 for symbol in symbols},
        }
        stop = False
        refresh_guard: dict[tuple[str, str], datetime] = {}

        def _emit_progress() -> None:
            if progress_callback is None:
                return
            try:
                progress_callback(dict(stats))
                stats["last_progress_callback_success_at"] = datetime.now(timezone.utc).isoformat()
            except Exception as exc:
                stats["progress_callback_errors"] = int(stats.get("progress_callback_errors", 0) or 0) + 1
                stats["last_progress_callback_error"] = f"{exc.__class__.__name__}:{exc}"
                stats["last_progress_callback_error_at"] = datetime.now(timezone.utc).isoformat()

        async def _stream_one_interval(interval: str) -> None:
            nonlocal stop
            backoff = self.settings.ws_reconnect_base_seconds
            while not stop:
                try:
                    async for kline in self.market_data.binance.stream_klines(symbols=symbols, interval=interval):
                        if stop:
                            break

                        payload = {
                            "symbol": kline.symbol,
                            "timeframe": interval,
                            "ts": kline.open_time,
                            "o": kline.o,
                            "h": kline.h,
                            "l": kline.l,
                            "c": kline.c,
                            "v": kline.v,
                            "source": "binance_ws",
                            "is_final": kline.is_final,
                        }

                        try:
                            self.market_data.ingest_candle(payload)
                            self.db.commit()
                            stats["committed_candles"] += 1
                            stats["last_ingest_success_at"] = datetime.now(timezone.utc).isoformat()
                        except DataQualityError as exc:
                            self.db.rollback()
                            if str(exc) == "reverse timestamp detected":
                                stats["skipped_reverse_timestamp"] += 1
                            else:
                                stats["ingest_errors"] += 1
                                stats["last_ingest_error"] = f"{exc.__class__.__name__}:{exc}"
                                stats["last_ingest_error_at"] = datetime.now(timezone.utc).isoformat()
                            _emit_progress()
                            continue
                        except Exception as exc:
                            self.db.rollback()
                            stats["ingest_errors"] += 1
                            stats["last_ingest_error"] = f"{exc.__class__.__name__}:{exc}"
                            stats["last_ingest_error_at"] = datetime.now(timezone.utc).isoformat()
                            _emit_progress()
                            continue

                        stats["processed_messages"] += 1
                        stats["per_interval"][interval] = int(stats["per_interval"][interval]) + 1
                        stats["per_symbol"][kline.symbol] = int(stats["per_symbol"].get(kline.symbol, 0)) + 1
                        stats["last_stream_error"] = ""

                        if refresh_on_final and kline.is_final:
                            now = datetime.now(timezone.utc)
                            refresh_key = (kline.symbol, interval)
                            last = refresh_guard.get(refresh_key)
                            if last is None or (
                                now - last
                            ).total_seconds() >= self.settings.ws_refresh_cooldown_seconds:
                                refresh_payload: dict[str, Any] | None = None
                                refresh_ok = False
                                try:
                                    refresh_payload = self.refresh_symbol(kline.symbol)
                                    stats["refresh_calls"] += 1
                                    stats["last_refresh_error"] = ""
                                    stats["last_refresh_success_at"] = datetime.now(timezone.utc).isoformat()
                                    refresh_ok = True
                                except Exception as exc:
                                    self.db.rollback()
                                    stats["refresh_errors"] += 1
                                    stats["last_refresh_error"] = f"{exc.__class__.__name__}:{exc}"
                                    stats["last_refresh_error_at"] = datetime.now(timezone.utc).isoformat()

                                if refresh_ok:
                                    try:
                                        plan_ids = list((refresh_payload or {}).get("session_impulse_retest_plan_ids") or [])
                                        route_payload = (
                                            self.auto_route_session_impulse_retest_plans(
                                                symbol=kline.symbol,
                                                plan_ids=plan_ids,
                                            )
                                            if plan_ids
                                            else self.auto_route_symbol(symbol=kline.symbol)
                                        )
                                        stats["auto_route_calls"] += 1
                                        stats["auto_route_submit_calls"] += int(route_payload.get("submit_calls", 0) or 0)
                                        stats["auto_route_intents_created"] += int(route_payload.get("intents_created", 0) or 0)
                                        stats["last_auto_route_error"] = ""
                                        stats["last_auto_route_success_at"] = datetime.now(timezone.utc).isoformat()
                                    except Exception as exc:
                                        self.db.rollback()
                                        stats["auto_route_errors"] += 1
                                        stats["last_auto_route_error"] = f"{exc.__class__.__name__}:{exc}"
                                        stats["last_auto_route_error_at"] = datetime.now(timezone.utc).isoformat()
                                refresh_guard[refresh_key] = now

                        _emit_progress()

                        if max_messages and stats["processed_messages"] >= max_messages:
                            stop = True
                            break

                    if stop:
                        break

                    stats["reconnects"] += 1
                    _emit_progress()
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2.0, self.settings.ws_reconnect_max_seconds)
                except asyncio.CancelledError:
                    break
                except Exception as exc:
                    self.db.rollback()
                    stats["reconnects"] += 1
                    stats["last_stream_error"] = f"{exc.__class__.__name__}:{exc}"
                    _emit_progress()
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2.0, self.settings.ws_reconnect_max_seconds)

        tasks = [asyncio.create_task(_stream_one_interval(interval)) for interval in selected_intervals]
        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            stats["running"] = False

        return stats
