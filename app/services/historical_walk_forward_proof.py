from __future__ import annotations

import copy
from bisect import bisect_left
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from math import isfinite
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.core.config import ROOT_DIR, Settings, get_settings
from app.db.models import Candle, Plan, Zone
from app.db.repositories import CandleRepository
from app.services.context_engine import ContextEngine
from app.services.fast_failure_guard import fast_failure_hit, fast_failure_trigger_detail, resolve_fast_failure_policy
from app.services.plan_generator import PlanGenerator, RankedPlan
from app.services.report_io import atomic_write_text
from app.services.session_guidance import SessionGuidanceService
from app.services.zone_engine import ZoneEngine


@dataclass(slots=True)
class _PendingPlan:
    plan: Plan
    generated_ts: datetime
    thesis_key: str


@dataclass(slots=True)
class _ActiveTrade:
    plan: Plan
    generated_ts: datetime
    entry_ts: datetime
    thesis_key: str
    remaining_qty: float = 1.0
    realized_r: float = 0.0
    exited_target_reasons: set[str] = field(default_factory=set)


class HistoricalWalkForwardProofService:
    _CACHE_SCHEMA_VERSION = "historical_walk_forward_contract_proof_v10"

    def __init__(
        self,
        *,
        candle_repo: CandleRepository,
        settings: Settings | None = None,
        context_engine: ContextEngine | None = None,
        zone_engine: ZoneEngine | None = None,
        plan_generator: PlanGenerator | None = None,
    ):
        self.candle_repo = candle_repo
        self.settings = settings or get_settings()
        self.context_engine = context_engine or ContextEngine()
        self.zone_engine = zone_engine or ZoneEngine()
        self.plan_generator = plan_generator or PlanGenerator()
        self.session_guidance = SessionGuidanceService(self.settings)

    @staticmethod
    def _normalize_ts(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @classmethod
    def _parse_ts(cls, value: Any) -> datetime | None:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            return cls._normalize_ts(datetime.fromisoformat(text.replace("Z", "+00:00")))
        except ValueError:
            return None

    @staticmethod
    def _json_default(value: Any) -> str:
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value)

    @staticmethod
    def _price_tolerance(value: float) -> float:
        return max(abs(float(value)) * 0.0005, 1e-6)

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        if value in (None, "", "None"):
            return default
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return default
        return parsed if isfinite(parsed) else default

    @classmethod
    def _safe_int(cls, value: Any, default: int = 0) -> int:
        return int(cls._safe_float(value, float(default)))

    @staticmethod
    def _safe_bool(value: Any, default: bool = False) -> bool:
        if value is None:
            return bool(default)
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value) if isfinite(float(value)) else bool(default)
        text = str(value).strip().lower()
        if text in {"1", "true", "yes", "y", "on"}:
            return True
        if text in {"0", "false", "no", "n", "off", "none", "null", ""}:
            return False
        return bool(default)

    @staticmethod
    def _ema(values: list[float], length: int) -> float:
        if not values:
            return 0.0
        span = max(int(length), 1)
        alpha = 2.0 / (span + 1.0)
        ema = float(values[0])
        for value in values[1:]:
            ema = alpha * float(value) + (1.0 - alpha) * ema
        return float(ema)

    @staticmethod
    def _atr(candles: list[Candle], length: int = 14) -> float:
        if len(candles) < 2:
            return 0.0
        recent = candles[-max(int(length), 2) :]
        prev_close = float(recent[0].c)
        trs: list[float] = []
        for candle in recent[1:]:
            high = float(candle.h)
            low = float(candle.l)
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            trs.append(float(tr))
            prev_close = float(candle.c)
        if not trs:
            return 0.0
        return float(sum(trs) / len(trs))

    @classmethod
    def _entry_touched(cls, *, plan: Plan, candle: Candle) -> bool:
        entry = float(plan.entry_price)
        tolerance = cls._price_tolerance(entry)
        return float(candle.l) <= entry + tolerance and float(candle.h) >= entry - tolerance

    @classmethod
    def _threshold_hits(cls, *, plan: Plan, candle: Candle) -> dict[str, bool]:
        high = float(candle.h)
        low = float(candle.l)
        direction = str(plan.direction or "").lower()
        tolerance = cls._price_tolerance
        if direction == "short":
            return {
                "stop": high >= float(plan.sl) - tolerance(plan.sl),
                "tp1": low <= float(plan.tp1) + tolerance(plan.tp1),
                "tp2": low <= float(plan.tp2) + tolerance(plan.tp2),
                "tp3": low <= float(plan.tp3) + tolerance(plan.tp3),
            }
        return {
            "stop": low <= float(plan.sl) + tolerance(plan.sl),
            "tp1": high >= float(plan.tp1) - tolerance(plan.tp1),
            "tp2": high >= float(plan.tp2) - tolerance(plan.tp2),
            "tp3": high >= float(plan.tp3) - tolerance(plan.tp3),
        }

    @staticmethod
    def _split_weights(plan: Plan) -> dict[str, float]:
        split = dict(plan.split or {})
        weights = {
            "tp1": max(float(split.get("tp1", 0.0) or 0.0), 0.0),
            "tp2": max(float(split.get("tp2", 0.0) or 0.0), 0.0),
            "runner": max(float(split.get("runner", 0.0) or 0.0), 0.0),
        }
        total = sum(weights.values())
        if total <= 1e-9:
            return {"tp1": 0.5, "tp2": 0.5, "runner": 0.0}
        if abs(total - 1.0) <= 1e-6:
            return weights
        return {key: float(value / total) for key, value in weights.items()}

    @staticmethod
    def _realized_r_at_price(*, plan: Plan, price: float) -> float:
        risk_abs = max(abs(float(plan.entry_price) - float(plan.sl)), 1e-9)
        if str(plan.direction or "").lower() == "short":
            return float(float(plan.entry_price) - float(price)) / risk_abs
        return float(float(price) - float(plan.entry_price)) / risk_abs

    @staticmethod
    def _thesis_key(plan: Plan) -> str:
        validity = dict(plan.validity or {})
        cluster = str(validity.get("thesis_cluster_id") or "").strip()
        if cluster:
            return cluster
        fingerprint = dict(validity.get("thesis_fingerprint") or {})
        if fingerprint:
            ordered = ",".join(f"{key}:{fingerprint[key]}" for key in sorted(fingerprint))
            if ordered:
                return ordered
        return f"{plan.symbol}:{validity.get('strategy_family')}:{plan.direction}:{plan.entry_model}"

    @staticmethod
    def _contract_matches(
        *,
        plan: Plan,
        eligible_symbols: set[str],
        eligible_families: set[str],
        eligible_entry_models: set[str],
    ) -> bool:
        if eligible_symbols and str(plan.symbol or "").upper() not in eligible_symbols:
            return False
        family = str((plan.validity or {}).get("strategy_family") or "").strip().lower()
        if eligible_families and family not in eligible_families:
            return False
        entry_model = str(plan.entry_model or "").strip().upper()
        if eligible_entry_models and entry_model not in eligible_entry_models:
            return False
        return True

    @staticmethod
    def _load_blocked_strategy_time_contract(raw_path: str) -> list[dict[str, Any]]:
        text = str(raw_path or "").strip()
        if not text:
            return []
        path = Path(text)
        if not path.is_absolute():
            path = ROOT_DIR / path
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        rows = HistoricalWalkForwardProofService._json_list_payload(payload, key="blocked_buckets")
        blocked: list[dict[str, Any]] = []
        for item in rows:
            row = dict(item or {})
            symbol = str(row.get("symbol") or "").strip().upper()
            family = str(row.get("strategy_family") or "").strip().lower()
            entry_model = str(row.get("entry_model") or "").strip().upper()
            direction = str(row.get("direction") or "").strip().upper()
            if not symbol or not family or not entry_model or not direction:
                continue
            normalized: dict[str, Any] = {
                "symbol": symbol,
                "strategy_family": family,
                "entry_model": entry_model,
                "direction": direction,
            }
            valid = True
            for key, lower, upper in (
                ("year_utc", 2000, 3000),
                ("month_utc", 1, 12),
                ("day_utc", 1, 31),
                ("weekday_utc", 0, 6),
                ("hour_utc", 0, 23),
                ("minute_utc", 0, 59),
            ):
                value = row.get(key)
                if value in (None, ""):
                    continue
                try:
                    number = int(value)
                except (TypeError, ValueError):
                    valid = False
                    break
                if not (lower <= number <= upper):
                    valid = False
                    break
                normalized[key] = number
            if valid:
                blocked.append(normalized)
        return blocked

    @staticmethod
    def _matches_strategy_time_bucket(
        generated_ts: datetime,
        *,
        symbol: str,
        family: str,
        entry_model: str,
        direction: str,
        contract_row: dict[str, Any],
    ) -> bool:
        if symbol != str(contract_row.get("symbol") or ""):
            return False
        if family != str(contract_row.get("strategy_family") or ""):
            return False
        if entry_model != str(contract_row.get("entry_model") or ""):
            return False
        if direction != str(contract_row.get("direction") or ""):
            return False
        checks = {
            "year_utc": int(generated_ts.year),
            "month_utc": int(generated_ts.month),
            "day_utc": int(generated_ts.day),
            "weekday_utc": int(generated_ts.weekday()),
            "hour_utc": int(generated_ts.hour),
            "minute_utc": int(generated_ts.minute),
        }
        for key, actual in checks.items():
            expected = contract_row.get(key)
            if expected is None:
                continue
            if int(expected) != actual:
                return False
        return True

    @staticmethod
    def _load_blocked_plan_ids(raw_path: str) -> set[str]:
        text = str(raw_path or "").strip()
        if not text:
            return set()
        path = Path(text)
        if not path.is_absolute():
            path = ROOT_DIR / path
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return set()
        rows = HistoricalWalkForwardProofService._json_list_payload(payload, key="blocked_plan_ids")
        return {
            str(item or "").strip()
            for item in rows
            if str(item or "").strip()
        }

    @staticmethod
    def _json_list_payload(payload: Any, *, key: str) -> list[Any]:
        if isinstance(payload, dict):
            raw = payload.get(key) or []
        else:
            raw = payload
        if not isinstance(raw, (list, tuple, set)):
            return []
        return list(raw)

    def _candidate_passes_selection_filters(
        self,
        *,
        plan: Plan,
        generated_ts: datetime,
        blocked_time_contract: list[dict[str, Any]],
        blocked_plan_ids: set[str],
    ) -> bool:
        plan_id = str(plan.plan_id or "").strip()
        if blocked_plan_ids and plan_id and plan_id in blocked_plan_ids:
            return False
        if not blocked_time_contract:
            return True
        symbol = str(plan.symbol or "").strip().upper()
        family = str((plan.validity or {}).get("strategy_family") or "").strip().lower()
        entry_model = str(plan.entry_model or "").strip().upper()
        direction = str(plan.direction or "").strip().upper()
        return not any(
            self._matches_strategy_time_bucket(
                generated_ts,
                symbol=symbol,
                family=family,
                entry_model=entry_model,
                direction=direction,
                contract_row=contract_row,
            )
            for contract_row in blocked_time_contract
        )

    @staticmethod
    def _cache_dir(settings: Settings) -> Path:
        return Path(settings.validation_report_dir) / "historical_walk_forward_cache"

    def _cache_path(self, cache_key: str) -> Path:
        safe = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in str(cache_key or "walk_forward"))
        return self._cache_dir(self.settings) / f"{safe}.json"

    def _source_ts_bounds(
        self,
        symbols: tuple[str, ...],
    ) -> tuple[datetime | None, dict[str, str], datetime | None, dict[str, str]]:
        latest: datetime | None = None
        latest_by_symbol: dict[str, str] = {}
        earliest: datetime | None = None
        earliest_by_symbol: dict[str, str] = {}
        for symbol in symbols:
            first_candle = self.candle_repo.get_first_candle(symbol, "5m")
            first_ts = self._normalize_ts(getattr(first_candle, "ts", None) if first_candle is not None else None)
            if first_ts is not None:
                earliest_by_symbol[symbol] = first_ts.isoformat()
                if earliest is None or first_ts < earliest:
                    earliest = first_ts

            last_candle = self.candle_repo.get_last_candle(symbol, "5m")
            last_ts = self._normalize_ts(getattr(last_candle, "ts", None) if last_candle is not None else None)
            if last_ts is not None:
                latest_by_symbol[symbol] = last_ts.isoformat()
                if latest is None or last_ts > latest:
                    latest = last_ts
        return latest, latest_by_symbol, earliest, earliest_by_symbol

    def _replay_settings_fingerprint(self) -> dict[str, Any]:
        return {
            "btc_sweep_reversal_limit_fast_failure_enabled": bool(
                getattr(self.settings, "btc_sweep_reversal_limit_fast_failure_enabled", False)
            ),
            "btc_sweep_reversal_limit_fast_failure_allowed_sessions": str(
                getattr(self.settings, "btc_sweep_reversal_limit_fast_failure_allowed_sessions", "") or ""
            ),
            "btc_sweep_reversal_limit_fast_failure_max_bars": int(
                self._safe_int(getattr(self.settings, "btc_sweep_reversal_limit_fast_failure_max_bars", 0), 18)
            ),
            "btc_sweep_reversal_limit_fast_failure_stop_r": round(
                self._safe_float(getattr(self.settings, "btc_sweep_reversal_limit_fast_failure_stop_r", 0.0), 0.00000001),
                8,
            ),
            "btc_sweep_reversal_limit_fast_failure_requires_sl_touch": bool(
                getattr(self.settings, "btc_sweep_reversal_limit_fast_failure_requires_sl_touch", False)
            ),
        }

    def _load_cached_payload(
        self,
        *,
        cache_key: str,
        latest_source_ts: datetime | None,
        latest_source_ts_by_symbol: dict[str, str],
        first_source_ts: datetime | None,
        first_source_ts_by_symbol: dict[str, str],
        generate_on_new_15m_only: bool,
        independent_signal_mode: bool,
        max_candidates_per_bar: int | None,
        source_mode: str,
        contract_scope: str,
        eligible_symbols: tuple[str, ...],
        eligible_families: tuple[str, ...],
        eligible_entry_models: tuple[str, ...],
        blocked_strategy_time_contract_path: str,
        blocked_plan_ids_path: str,
    ) -> dict[str, Any] | None:
        path = self._cache_path(cache_key)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(payload, dict):
            return None
        age_hours = self._safe_float(self.settings.auto_trading_historical_walk_forward_cache_hours, 6.0)
        generated_at = self._parse_ts(payload.get("generated_at"))
        if generated_at is None:
            return None
        if age_hours > 0 and generated_at < datetime.now(UTC) - timedelta(hours=age_hours):
            return None
        if str(payload.get("schema_version") or "") != self._CACHE_SCHEMA_VERSION:
            return None
        if str(payload.get("strategy_version") or "") != str(self.settings.strategy_version):
            return None
        if str(payload.get("contract_scope") or "") != str(contract_scope):
            return None
        if list(payload.get("eligible_symbols") or []) != list(eligible_symbols):
            return None
        if list(payload.get("eligible_families") or []) != list(eligible_families):
            return None
        if list(payload.get("eligible_entry_models") or []) != list(eligible_entry_models):
            return None
        if str(payload.get("blocked_strategy_time_contract_path") or "") != str(blocked_strategy_time_contract_path or ""):
            return None
        if str(payload.get("blocked_plan_ids_path") or "") != str(blocked_plan_ids_path or ""):
            return None
        if self._safe_bool(payload.get("generate_on_new_15m_only", False)) != self._safe_bool(generate_on_new_15m_only):
            return None
        if self._safe_bool(payload.get("independent_signal_mode", False)) != self._safe_bool(independent_signal_mode):
            return None
        if str(payload.get("source_mode") or "engine_regenerated") != str(source_mode or "engine_regenerated"):
            return None
        payload_max_candidates_per_bar = payload.get("max_candidates_per_bar")
        if payload_max_candidates_per_bar is not None:
            payload_max_candidates_per_bar = int(payload_max_candidates_per_bar)
        normalized_max_candidates_per_bar = None if max_candidates_per_bar is None else int(max_candidates_per_bar)
        if payload_max_candidates_per_bar != normalized_max_candidates_per_bar:
            return None
        if dict(payload.get("first_source_ts_by_symbol") or {}) != dict(first_source_ts_by_symbol):
            return None
        if dict(payload.get("latest_source_ts_by_symbol") or {}) != dict(latest_source_ts_by_symbol):
            return None
        payload_first = self._parse_ts(payload.get("first_source_ts"))
        if payload_first != first_source_ts:
            return None
        payload_latest = self._parse_ts(payload.get("latest_source_ts"))
        if payload_latest != latest_source_ts:
            return None
        if dict(payload.get("replay_settings_fingerprint") or {}) != self._replay_settings_fingerprint():
            return None
        return payload

    def _store_cached_payload(self, *, cache_key: str, payload: dict[str, Any]) -> None:
        path = self._cache_path(cache_key)
        atomic_write_text(path, json.dumps(payload, ensure_ascii=False, default=self._json_default))

    def _load_symbol_candles(
        self,
        *,
        symbol: str,
        timeframe: str,
        start_ts: datetime,
        end_ts: datetime,
    ) -> list[Candle]:
        return self.candle_repo.list_range(
            symbol=symbol,
            timeframe=timeframe,
            start_ts=start_ts,
            end_ts=end_ts,
        )

    def _load_historical_symbol_plans(
        self,
        *,
        symbol: str,
        start_ts: datetime,
        end_ts: datetime,
        eligible_symbols: set[str],
        eligible_families: set[str],
        eligible_entry_models: set[str],
    ) -> list[Plan]:
        stmt = (
            select(Plan)
            .where(
                Plan.symbol == symbol,
                Plan.valid_from.is_not(None),
                Plan.valid_until.is_not(None),
            )
            .order_by(Plan.valid_from.asc(), Plan.plan_id.asc())
        )
        plans = list(self.candle_repo.db.scalars(stmt))
        filtered: list[Plan] = []
        for plan in plans:
            generated_ts = self._normalize_ts(getattr(plan, "valid_from", None))
            if generated_ts is None or generated_ts < start_ts or generated_ts > end_ts:
                continue
            if str(getattr(plan, "timeframe", "") or "").lower() != "5m":
                continue
            if not self._contract_matches(
                plan=plan,
                eligible_symbols=eligible_symbols,
                eligible_families=eligible_families,
                eligible_entry_models=eligible_entry_models,
            ):
                continue
            filtered.append(plan)
        return filtered

    def _normalize_zone_timestamps(self, zones: list[Zone], *, current_ts: datetime) -> list[Zone]:
        for zone in zones:
            created_ts = self._normalize_ts(getattr(zone, "created_ts", None))
            if created_ts is None or created_ts > current_ts:
                zone.created_ts = current_ts
            else:
                zone.created_ts = created_ts
            touched_ts = self._normalize_ts(getattr(zone, "last_touched_ts", None))
            if touched_ts is not None and touched_ts > current_ts:
                zone.last_touched_ts = current_ts
        return zones

    def _generate_ranked_plans(
        self,
        *,
        symbol: str,
        current_ts: datetime,
        candles_5m: list[Candle],
        candles_15m: list[Candle],
        existing_zones: list[Zone],
        active_thesis_clusters: int,
    ) -> tuple[list[Zone], list[RankedPlan]]:
        context = self.context_engine.build_snapshot(symbol=symbol, candles_5m=candles_5m, candles_15m=candles_15m)
        zones = self.zone_engine.refresh(symbol=symbol, candles_15m=candles_15m, existing=existing_zones)
        zones = self._normalize_zone_timestamps(zones, current_ts=current_ts)
        active_zones = [zone for zone in zones if str(zone.state or "") != "expired"]
        ranked = self.plan_generator.generate(
            symbol=symbol,
            zones=active_zones,
            context=context,
            candles_5m=candles_5m,
            active_thesis_clusters=active_thesis_clusters,
            now=current_ts,
        )
        return zones, ranked

    def _clone_for_walk_forward(self, *, ranked: RankedPlan, generated_ts: datetime) -> Plan:
        plan = copy.deepcopy(ranked.plan)
        plan_id = (
            f"wf_{str(plan.symbol).lower()}_{generated_ts.strftime('%m%d%H%M')}_"
            f"{str(plan.entry_model).lower()}_{str(plan.zone_id)[-8:]}"
        )[:50]
        plan.plan_id = plan_id
        validity = dict(plan.validity or {})
        validity["walk_forward_generated_ts"] = generated_ts.isoformat()
        validity["walk_forward_rank_score"] = float(ranked.final_rank_score)
        plan.validity = validity
        return plan

    def _close_active_trade(
        self,
        *,
        active: _ActiveTrade,
        candle: Candle,
        exit_reason: str,
        exit_price: float,
        held_bars: int,
        trigger_detail: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        active.realized_r += self._realized_r_at_price(plan=active.plan, price=exit_price) * max(active.remaining_qty, 0.0)
        validity = dict(active.plan.validity or {})
        family = str(validity.get("strategy_family") or "")
        return {
            "plan_id": str(active.plan.plan_id or ""),
            "symbol": str(active.plan.symbol or ""),
            "direction": str(active.plan.direction or ""),
            "strategy_family": family,
            "entry_model": str(active.plan.entry_model or "").upper(),
            "strategy_grade": str(validity.get("strategy_grade") or "").strip().upper(),
            "strategy_family_score": float(validity.get("strategy_family_score") or 0.0),
            "regime": str(validity.get("regime") or "unknown").strip().lower() or "unknown",
            "generated_ts": active.generated_ts.isoformat(),
            "entry_ts": active.entry_ts.isoformat(),
            "closed_ts": self._normalize_ts(candle.ts).isoformat(),
            "walk_forward_rank_score": round(float(validity.get("walk_forward_rank_score") or 0.0), 4),
            "confluence_score": round(float(validity.get("confluence_score") or 0.0), 4),
            "meta_score": round(float(validity.get("meta_score") or 0.0), 4),
            "expected_ev_r": round(float(validity.get("expected_ev_r") or 0.0), 4),
            "expected_win_prob": round(float(validity.get("expected_win_prob") or 0.0), 4),
            "reaction_classification": str(validity.get("reaction_classification") or "").strip().lower(),
            "reaction_rejection_score": round(float(validity.get("reaction_rejection_score") or 0.0), 4),
            "reaction_acceptance_score": round(float(validity.get("reaction_acceptance_score") or 0.0), 4),
            "session_guidance_state": str(validity.get("session_guidance_state") or "").strip().lower(),
            "session_guidance_session_name": str(validity.get("session_guidance_session_name") or "").strip().lower(),
            "session_score_bias": round(float(validity.get("session_score_bias") or 0.0), 4),
            "session_probability_adjustment": round(float(validity.get("session_probability_adjustment") or 0.0), 4),
            "near_lp": self._safe_bool(validity.get("near_lp")),
            "zone_age_hours": round(float(validity.get("zone_age_hours") or 0.0), 4),
            "historical_raw_signal": self._safe_bool(validity.get("historical_raw_signal")),
            "raw_signal_features": copy.deepcopy(dict(validity.get("raw_signal_features") or {})),
            "final_exit_reason": str(exit_reason or "unknown"),
            "final_exit_price": float(exit_price),
            "final_exit_realized_r": round(float(active.realized_r), 4),
            "replayed_realized_r": round(float(active.realized_r), 4),
            "final_exit_held_bars": int(held_bars),
            "final_exit_trigger_detail": dict(trigger_detail or {}),
            "thesis_key": active.thesis_key,
            "strategy_version": str(active.plan.strategy_version or ""),
            "source": "historical_walk_forward",
        }

    def _advance_active_trade(self, *, active: _ActiveTrade, candle: Candle) -> dict[str, Any] | None:
        hits = self._threshold_hits(plan=active.plan, candle=candle)
        held_bars = max(
            0,
            int(
                (self._normalize_ts(candle.ts) - self._normalize_ts(active.entry_ts)).total_seconds()
                // (5 * 60)
            ),
        )
        fast_failure_policy = resolve_fast_failure_policy(plan=active.plan, held_bars=held_bars)
        if (
            active.remaining_qty > 1e-10
            and fast_failure_policy is not None
            and (not fast_failure_policy.requires_sl_touch or hits["stop"])
            and fast_failure_hit(
                plan=active.plan,
                policy=fast_failure_policy,
                high=float(candle.h),
                low=float(candle.l),
            )
        ):
            return self._close_active_trade(
                active=active,
                candle=candle,
                exit_reason="structure_failure",
                exit_price=float(fast_failure_policy.stop_price),
                held_bars=held_bars,
                trigger_detail=fast_failure_trigger_detail(
                    plan=active.plan,
                    policy=fast_failure_policy,
                    held_bars=held_bars,
                ),
            )
        if active.remaining_qty > 1e-10 and hits["stop"]:
            return self._close_active_trade(
                active=active,
                candle=candle,
                exit_reason="stop_loss",
                exit_price=float(active.plan.sl),
                held_bars=held_bars,
            )

        split = self._split_weights(active.plan)
        if (
            active.remaining_qty > 1e-10
            and "target_tp1" not in active.exited_target_reasons
            and hits["tp1"]
            and split["tp1"] > 1e-10
        ):
            qty = min(active.remaining_qty, split["tp1"])
            active.realized_r += qty * self._realized_r_at_price(plan=active.plan, price=float(active.plan.tp1))
            active.remaining_qty = max(0.0, active.remaining_qty - qty)
            active.exited_target_reasons.add("target_tp1")
            if active.remaining_qty <= 1e-10:
                return self._close_active_trade(
                    active=active,
                    candle=candle,
                    exit_reason="target_tp1",
                    exit_price=float(active.plan.tp1),
                    held_bars=held_bars,
                )

        if (
            active.remaining_qty > 1e-10
            and "target_tp2" not in active.exited_target_reasons
            and hits["tp2"]
            and split["tp2"] > 1e-10
        ):
            qty = min(active.remaining_qty, split["tp2"])
            active.realized_r += qty * self._realized_r_at_price(plan=active.plan, price=float(active.plan.tp2))
            active.remaining_qty = max(0.0, active.remaining_qty - qty)
            active.exited_target_reasons.add("target_tp2")
            if active.remaining_qty <= 1e-10:
                return self._close_active_trade(
                    active=active,
                    candle=candle,
                    exit_reason="target_tp2",
                    exit_price=float(active.plan.tp2),
                    held_bars=held_bars,
                )

        if active.remaining_qty > 1e-10 and hits["tp3"]:
            return self._close_active_trade(
                active=active,
                candle=candle,
                exit_reason="target_tp3",
                exit_price=float(active.plan.tp3),
                held_bars=held_bars,
            )

        max_allowed_bars = int((active.plan.validity or {}).get("strategy_family_time_stop_max_bars", 0) or 0)
        if active.remaining_qty > 1e-10 and max_allowed_bars > 0 and held_bars > max_allowed_bars:
            return self._close_active_trade(
                active=active,
                candle=candle,
                exit_reason="time_failure",
                exit_price=float(candle.c),
                held_bars=held_bars,
            )

        if active.remaining_qty > 1e-10 and self._normalize_ts(candle.ts) >= self._normalize_ts(active.plan.valid_until):
            return self._close_active_trade(
                active=active,
                candle=candle,
                exit_reason="session_end_flatten",
                exit_price=float(candle.c),
                held_bars=held_bars,
            )
        return None

    def _simulate_independent_plan(
        self,
        *,
        plan: Plan,
        generated_ts: datetime,
        generated_idx_5: int,
        thesis_key: str,
        candles_5m: list[Candle],
    ) -> tuple[dict[str, Any] | None, str]:
        active: _ActiveTrade | None = None
        valid_until = self._normalize_ts(plan.valid_until)
        for candle in candles_5m[generated_idx_5 + 1 :]:
            current_ts = self._normalize_ts(candle.ts)
            if current_ts is None:
                continue
            if active is None:
                if valid_until is not None and current_ts > valid_until:
                    return None, "expired_unfilled"
                if current_ts <= generated_ts:
                    continue
                if not self._entry_touched(plan=plan, candle=candle):
                    continue
                active = _ActiveTrade(
                    plan=plan,
                    generated_ts=generated_ts,
                    entry_ts=current_ts,
                    thesis_key=thesis_key,
                )
                continue

            closed_row = self._advance_active_trade(active=active, candle=candle)
            if closed_row is not None:
                return closed_row, "closed"

        if active is not None:
            return None, "open_at_end"
        return None, "window_end_unfilled"

    def _simulate_symbol_independent(
        self,
        *,
        symbol: str,
        start_ts: datetime,
        end_ts: datetime,
        eligible_symbols: set[str],
        eligible_families: set[str],
        eligible_entry_models: set[str],
        generate_on_new_15m_only: bool,
        max_candidates_per_bar: int | None,
        blocked_time_contract: list[dict[str, Any]],
        blocked_plan_ids: set[str],
    ) -> dict[str, Any]:
        candles_5m = self._load_symbol_candles(symbol=symbol, timeframe="5m", start_ts=start_ts, end_ts=end_ts)
        candles_15m = self._load_symbol_candles(symbol=symbol, timeframe="15m", start_ts=start_ts, end_ts=end_ts)
        candles_5m = [candle for candle in candles_5m if self._normalize_ts(candle.ts) is not None]
        candles_15m = [candle for candle in candles_15m if self._normalize_ts(candle.ts) is not None]
        warmup_5m_bars = max(self._safe_int(self.settings.auto_trading_historical_walk_forward_warmup_5m_bars, 300), 30)
        min_15m_bars = max(self._safe_int(self.settings.auto_trading_historical_walk_forward_min_15m_bars, 60), 30)
        max_5m_window = max(
            self._safe_int(self.settings.auto_trading_historical_walk_forward_max_5m_window_bars, 300),
            warmup_5m_bars,
        )
        max_15m_window = max(
            self._safe_int(self.settings.auto_trading_historical_walk_forward_max_15m_window_bars, 300),
            min_15m_bars,
        )
        if len(candles_5m) < warmup_5m_bars or len(candles_15m) < min_15m_bars:
            return {
                "symbol": symbol,
                "eligible_bar_count": 0,
                "generated_contract_candidate_count": 0,
                "selected_contract_candidate_count": 0,
                "closed_trade_count": 0,
                "no_candidate_bar_count": 0,
                "unfilled_candidate_count": 0,
                "open_at_end_candidate_count": 0,
                "trade_rows": [],
            }

        rows: list[dict[str, Any]] = []
        existing_zones: list[Zone] = []
        eligible_bar_count = 0
        generated_contract_candidate_count = 0
        selected_contract_candidate_count = 0
        no_candidate_bar_count = 0
        unfilled_candidate_count = 0
        open_at_end_candidate_count = 0
        idx_15 = -1

        for idx_5, candle in enumerate(candles_5m):
            current_ts = self._normalize_ts(candle.ts)
            if current_ts is None:
                continue
            advanced_15m = False
            while idx_15 + 1 < len(candles_15m):
                next_ts = self._normalize_ts(candles_15m[idx_15 + 1].ts)
                if next_ts is None or next_ts > current_ts:
                    break
                idx_15 += 1
                advanced_15m = True
            if idx_5 + 1 < warmup_5m_bars or idx_15 + 1 < min_15m_bars:
                continue

            eligible_bar_count += 1
            if generate_on_new_15m_only and not advanced_15m:
                continue

            candles_5m_window = candles_5m[max(0, idx_5 + 1 - max_5m_window) : idx_5 + 1]
            candles_15m_window = candles_15m[max(0, idx_15 + 1 - max_15m_window) : idx_15 + 1]
            existing_zones, ranked = self._generate_ranked_plans(
                symbol=symbol,
                current_ts=current_ts,
                candles_5m=candles_5m_window,
                candles_15m=candles_15m_window,
                existing_zones=existing_zones,
                active_thesis_clusters=0,
            )

            contract_ranked: list[RankedPlan] = []
            seen_thesis_keys: set[str] = set()
            for item in ranked:
                if not self._contract_matches(
                    plan=item.plan,
                    eligible_symbols=eligible_symbols,
                    eligible_families=eligible_families,
                    eligible_entry_models=eligible_entry_models,
                ):
                    continue
                if not self._candidate_passes_selection_filters(
                    plan=item.plan,
                    generated_ts=current_ts,
                    blocked_time_contract=blocked_time_contract,
                    blocked_plan_ids=blocked_plan_ids,
                ):
                    continue
                thesis_key = self._thesis_key(item.plan)
                if thesis_key in seen_thesis_keys:
                    continue
                seen_thesis_keys.add(thesis_key)
                contract_ranked.append(item)

            generated_contract_candidate_count += len(contract_ranked)
            if not contract_ranked:
                no_candidate_bar_count += 1
                continue

            limit = max_candidates_per_bar
            if limit is not None and limit > 0:
                selected_ranked = contract_ranked[:limit]
            else:
                selected_ranked = contract_ranked

            for item in selected_ranked:
                cloned = self._clone_for_walk_forward(ranked=item, generated_ts=current_ts)
                thesis_key = self._thesis_key(cloned)
                selected_contract_candidate_count += 1
                closed_row, status = self._simulate_independent_plan(
                    plan=cloned,
                    generated_ts=current_ts,
                    generated_idx_5=idx_5,
                    thesis_key=thesis_key,
                    candles_5m=candles_5m,
                )
                if closed_row is not None:
                    rows.append(closed_row)
                elif status == "open_at_end":
                    open_at_end_candidate_count += 1
                else:
                    unfilled_candidate_count += 1

        return {
            "symbol": symbol,
            "eligible_bar_count": int(eligible_bar_count),
            "generated_contract_candidate_count": int(generated_contract_candidate_count),
            "selected_contract_candidate_count": int(selected_contract_candidate_count),
            "closed_trade_count": int(len(rows)),
            "no_candidate_bar_count": int(no_candidate_bar_count),
            "unfilled_candidate_count": int(unfilled_candidate_count),
            "open_at_end_candidate_count": int(open_at_end_candidate_count),
            "trade_rows": rows,
        }

    def _simulate_symbol_from_historical_plans(
        self,
        *,
        symbol: str,
        start_ts: datetime,
        end_ts: datetime,
        eligible_symbols: set[str],
        eligible_families: set[str],
        eligible_entry_models: set[str],
        blocked_time_contract: list[dict[str, Any]],
        blocked_plan_ids: set[str],
    ) -> dict[str, Any]:
        candles_5m = self._load_symbol_candles(symbol=symbol, timeframe="5m", start_ts=start_ts, end_ts=end_ts)
        candles_5m = [candle for candle in candles_5m if self._normalize_ts(candle.ts) is not None]
        if not candles_5m:
            return {
                "symbol": symbol,
                "eligible_bar_count": 0,
                "generated_contract_candidate_count": 0,
                "selected_contract_candidate_count": 0,
                "closed_trade_count": 0,
                "no_candidate_bar_count": 0,
                "unfilled_candidate_count": 0,
                "open_at_end_candidate_count": 0,
                "trade_rows": [],
            }

        plans = self._load_historical_symbol_plans(
            symbol=symbol,
            start_ts=start_ts,
            end_ts=end_ts,
            eligible_symbols=eligible_symbols,
            eligible_families=eligible_families,
            eligible_entry_models=eligible_entry_models,
        )
        candle_ts_values = [self._normalize_ts(candle.ts) for candle in candles_5m]
        rows: list[dict[str, Any]] = []
        unfilled_candidate_count = 0
        open_at_end_candidate_count = 0
        selected_contract_candidate_count = 0

        for plan in plans:
            generated_ts = self._normalize_ts(getattr(plan, "valid_from", None))
            if generated_ts is None:
                continue
            if not self._candidate_passes_selection_filters(
                plan=plan,
                generated_ts=generated_ts,
                blocked_time_contract=blocked_time_contract,
                blocked_plan_ids=blocked_plan_ids,
            ):
                continue
            generated_idx_5 = bisect_left(candle_ts_values, generated_ts)
            if generated_idx_5 >= len(candles_5m):
                continue
            selected_contract_candidate_count += 1
            thesis_key = self._thesis_key(plan)
            closed_row, status = self._simulate_independent_plan(
                plan=plan,
                generated_ts=generated_ts,
                generated_idx_5=generated_idx_5,
                thesis_key=thesis_key,
                candles_5m=candles_5m,
            )
            if closed_row is not None:
                rows.append(closed_row)
            elif status == "open_at_end":
                open_at_end_candidate_count += 1
            else:
                unfilled_candidate_count += 1

        return {
            "symbol": symbol,
            "eligible_bar_count": int(len(candles_5m)),
            "generated_contract_candidate_count": int(len(plans)),
            "selected_contract_candidate_count": int(selected_contract_candidate_count),
            "closed_trade_count": int(len(rows)),
            "no_candidate_bar_count": 0,
            "unfilled_candidate_count": int(unfilled_candidate_count),
            "open_at_end_candidate_count": int(open_at_end_candidate_count),
            "trade_rows": rows,
        }

    def _build_raw_candle_plan(
        self,
        *,
        symbol: str,
        generated_ts: datetime,
        family: str,
        entry_model: str,
        direction: str,
        entry_price: float,
        sl: float,
        tp1: float,
        tp2: float,
        tp3: float,
        time_stop_max_bars: int,
        extra_validity: dict[str, Any] | None = None,
    ) -> Plan | None:
        risk_abs = abs(float(entry_price) - float(sl))
        if risk_abs <= 1e-9:
            return None
        if direction == "long":
            if not (sl < entry_price < tp1 < tp2 < tp3):
                return None
        else:
            if not (sl > entry_price > tp1 > tp2 > tp3):
                return None
        plan_id = (
            f"raw_{symbol.lower()}_{generated_ts.strftime('%Y%m%d%H%M')}_"
            f"{family}_{entry_model.lower()}_{direction}"
        )[:50]
        validity = {
            "strategy_family": family,
            "strategy_grade": "A",
            "strategy_family_time_stop_max_bars": int(time_stop_max_bars),
            "thesis_cluster_id": f"{symbol}:{family}:{direction}:{generated_ts.strftime('%Y%m%d%H%M')}",
            "historical_raw_signal": True,
        }
        validity.update(dict(extra_validity or {}))
        validity.update(
            self._raw_candle_fast_failure_validity(
                symbol=symbol,
                family=family,
                entry_model=entry_model,
                generated_ts=generated_ts,
            )
        )
        return Plan(
            plan_id=plan_id,
            zone_id=f"raw_zone_{plan_id}"[:50],
            symbol=symbol,
            timeframe="5m",
            direction=direction,
            entry_model=entry_model,
            entry_price=float(entry_price),
            entry_condition="historical_raw_candle_signal",
            sl=float(sl),
            tp1=float(tp1),
            tp2=float(tp2),
            tp3=float(tp3),
            split={"tp1": 0.4, "tp2": 0.3, "runner": 0.3},
            rr_min=1.0,
            rr_base=2.0,
            rr_opt=3.0,
            ev=0.0,
            cost_est=0.0,
            confidence=0.5,
            validity=validity,
            state="PLANNED",
            valid_from=generated_ts,
            valid_until=generated_ts + timedelta(minutes=5 * max(int(time_stop_max_bars), 6)),
            strategy_version=str(self.settings.strategy_version or ""),
        )

    def _raw_candle_fast_failure_validity(
        self,
        *,
        symbol: str,
        family: str,
        entry_model: str,
        generated_ts: datetime,
    ) -> dict[str, Any]:
        if str(symbol or "").strip().upper() != "BTCUSDC":
            return {}
        if str(family or "").strip().lower() != "sweep_reversal":
            return {}
        if str(entry_model or "").strip().upper() != "LIMIT":
            return {}
        if not self._safe_bool(getattr(self.settings, "btc_sweep_reversal_limit_fast_failure_enabled", False)):
            return {}
        allowed_sessions = {
            item.strip().lower()
            for item in str(getattr(self.settings, "btc_sweep_reversal_limit_fast_failure_allowed_sessions", "") or "").split(",")
            if item.strip()
        }
        session_name = str(
            (self.session_guidance.snapshot(now=generated_ts).get("current_session") or {}).get("name") or "inactive"
        ).strip().lower() or "inactive"
        if allowed_sessions and session_name not in allowed_sessions:
            return {}
        max_bars = max(self._safe_int(getattr(self.settings, "btc_sweep_reversal_limit_fast_failure_max_bars", 0), 18), 0)
        stop_r = self._safe_float(getattr(self.settings, "btc_sweep_reversal_limit_fast_failure_stop_r", 0.0), 0.00000001)
        requires_sl_touch = self._safe_bool(getattr(self.settings, "btc_sweep_reversal_limit_fast_failure_requires_sl_touch", False))
        if max_bars <= 0 or stop_r <= 0.0 or stop_r >= 1.0:
            return {}
        return {
            "strategy_fast_failure_enabled": True,
            "strategy_fast_failure_policy": "btc_sweep_reversal_limit_initial_guard_stop",
            "strategy_fast_failure_session_name": session_name,
            "strategy_fast_failure_max_bars": max_bars,
            "strategy_fast_failure_stop_r": round(stop_r, 8),
            "strategy_fast_failure_requires_sl_touch": requires_sl_touch,
        }

    @staticmethod
    def _raw_signal_feature_payload(
        *,
        signal_family: str,
        direction: str,
        latest_open: float,
        latest_close: float,
        latest_high: float,
        latest_low: float,
        prior_high: float,
        prior_low: float,
        atr15: float,
        ema_fast: float,
        ema_slow: float,
        entry_price: float,
        sl: float,
    ) -> dict[str, Any]:
        range_abs = max(float(latest_high) - float(latest_low), 1e-9)
        atr_abs = max(float(atr15), 1e-9)
        risk_abs = max(abs(float(entry_price) - float(sl)), 1e-9)
        close_position = (float(latest_close) - float(latest_low)) / range_abs
        body_fraction = abs(float(latest_close) - float(latest_open)) / range_abs
        prior_range = max(float(prior_high) - float(prior_low), 0.0)
        if str(direction or "").strip().lower() == "short":
            sweep_distance_abs = max(float(latest_high) - float(prior_high), 0.0)
            reclaim_distance_abs = max(float(prior_high) - float(latest_close), 0.0)
            entry_offset_abs = max(float(entry_price) - float(latest_close), 0.0)
            directional_close_position = 1.0 - close_position
            directional_close_vs_ema_fast_abs = float(ema_fast) - float(latest_close)
        else:
            sweep_distance_abs = max(float(prior_low) - float(latest_low), 0.0)
            reclaim_distance_abs = max(float(latest_close) - float(prior_low), 0.0)
            entry_offset_abs = max(float(latest_close) - float(entry_price), 0.0)
            directional_close_position = close_position
            directional_close_vs_ema_fast_abs = float(latest_close) - float(ema_fast)
        return {
            "signal_family": str(signal_family or "").strip().lower(),
            "directional_close_position": round(float(directional_close_position), 4),
            "close_position": round(float(close_position), 4),
            "body_fraction": round(float(body_fraction), 4),
            "range_atr": round(float(range_abs / atr_abs), 4),
            "body_atr": round(float(abs(float(latest_close) - float(latest_open)) / atr_abs), 4),
            "sweep_distance_atr": round(float(sweep_distance_abs / atr_abs), 4),
            "reclaim_distance_atr": round(float(reclaim_distance_abs / atr_abs), 4),
            "entry_offset_atr": round(float(entry_offset_abs / atr_abs), 4),
            "entry_offset_r": round(float(entry_offset_abs / risk_abs), 4),
            "risk_atr": round(float(risk_abs / atr_abs), 4),
            "prior_range_atr": round(float(prior_range / atr_abs), 4),
            "ema_spread_atr": round(float(abs(float(ema_fast) - float(ema_slow)) / atr_abs), 4),
            "directional_close_vs_ema_fast_atr": round(float(directional_close_vs_ema_fast_abs / atr_abs), 4),
        }

    def _generate_raw_candle_candidates(
        self,
        *,
        symbol: str,
        current_ts: datetime,
        candles_5m_window: list[Candle],
        candles_15m_window: list[Candle],
        eligible_families: set[str],
        eligible_entry_models: set[str],
    ) -> list[Plan]:
        if len(candles_5m_window) < 36 or len(candles_15m_window) < 24:
            return []
        atr15 = self._atr(candles_15m_window[-24:], length=14)
        if atr15 <= 1e-9:
            return []

        candidates: list[Plan] = []
        recent_5 = candles_5m_window[-6:]
        latest_5 = recent_5[-1]
        latest_close = float(latest_5.c)
        latest_open = float(latest_5.o)
        latest_high = float(latest_5.h)
        latest_low = float(latest_5.l)
        latest_range = max(latest_high - latest_low, 1e-9)
        close_position = (latest_close - latest_low) / latest_range
        prior_5 = candles_5m_window[-30:-6]
        prior_low = min(float(c.l) for c in prior_5)
        prior_high = max(float(c.h) for c in prior_5)

        closes_15 = [float(c.c) for c in candles_15m_window[-60:]]
        ema_fast = self._ema(closes_15[-30:], 20)
        ema_slow = self._ema(closes_15[-60:], 50)
        ema_fast_prev = self._ema(closes_15[-31:-1], 20) if len(closes_15) >= 31 else ema_fast
        trend_up = ema_fast > ema_slow and ema_fast >= ema_fast_prev and latest_close >= ema_fast
        trend_down = ema_fast < ema_slow and ema_fast <= ema_fast_prev and latest_close <= ema_fast

        if "sweep_reversal" in eligible_families:
            if latest_low < prior_low - atr15 * 0.08 and latest_close > prior_low and close_position >= 0.4:
                entry_model = "LIMIT" if close_position >= 0.68 else "SWEEP_CONFIRM" if close_position >= 0.52 else "CONFIRM"
                if entry_model in eligible_entry_models:
                    entry_price = latest_low + latest_range * 0.35 if entry_model == "LIMIT" else latest_close - latest_range * 0.12 if entry_model == "SWEEP_CONFIRM" else latest_close
                    sl = min(latest_low, prior_low) - atr15 * 0.18
                    risk = entry_price - sl
                    if risk > atr15 * 0.08:
                        plan = self._build_raw_candle_plan(
                            symbol=symbol,
                            generated_ts=current_ts,
                            family="sweep_reversal",
                            entry_model=entry_model,
                            direction="long",
                            entry_price=entry_price,
                            sl=sl,
                            tp1=entry_price + risk,
                            tp2=entry_price + risk * 2.0,
                            tp3=entry_price + risk * 3.0,
                            time_stop_max_bars=18,
                            extra_validity={
                                "raw_signal_features": self._raw_signal_feature_payload(
                                    signal_family="sweep_reversal",
                                    direction="long",
                                    latest_open=latest_open,
                                    latest_close=latest_close,
                                    latest_high=latest_high,
                                    latest_low=latest_low,
                                    prior_high=prior_high,
                                    prior_low=prior_low,
                                    atr15=atr15,
                                    ema_fast=ema_fast,
                                    ema_slow=ema_slow,
                                    entry_price=entry_price,
                                    sl=sl,
                                )
                            },
                        )
                        if plan is not None:
                            candidates.append(plan)
            if latest_high > prior_high + atr15 * 0.08 and latest_close < prior_high and close_position <= 0.6:
                entry_model = "LIMIT" if close_position <= 0.32 else "SWEEP_CONFIRM" if close_position <= 0.48 else "CONFIRM"
                if entry_model in eligible_entry_models:
                    entry_price = latest_high - latest_range * 0.35 if entry_model == "LIMIT" else latest_close + latest_range * 0.12 if entry_model == "SWEEP_CONFIRM" else latest_close
                    sl = max(latest_high, prior_high) + atr15 * 0.18
                    risk = sl - entry_price
                    if risk > atr15 * 0.08:
                        plan = self._build_raw_candle_plan(
                            symbol=symbol,
                            generated_ts=current_ts,
                            family="sweep_reversal",
                            entry_model=entry_model,
                            direction="short",
                            entry_price=entry_price,
                            sl=sl,
                            tp1=entry_price - risk,
                            tp2=entry_price - risk * 2.0,
                            tp3=entry_price - risk * 3.0,
                            time_stop_max_bars=18,
                            extra_validity={
                                "raw_signal_features": self._raw_signal_feature_payload(
                                    signal_family="sweep_reversal",
                                    direction="short",
                                    latest_open=latest_open,
                                    latest_close=latest_close,
                                    latest_high=latest_high,
                                    latest_low=latest_low,
                                    prior_high=prior_high,
                                    prior_low=prior_low,
                                    atr15=atr15,
                                    ema_fast=ema_fast,
                                    ema_slow=ema_slow,
                                    entry_price=entry_price,
                                    sl=sl,
                                )
                            },
                        )
                        if plan is not None:
                            candidates.append(plan)

        if "trend_continuation" in eligible_families:
            pullback_5 = candles_5m_window[-12:]
            pullback_low = min(float(c.l) for c in pullback_5)
            pullback_high = max(float(c.h) for c in pullback_5)
            recent_high_15 = max(float(c.h) for c in candles_15m_window[-12:])
            recent_low_15 = min(float(c.l) for c in candles_15m_window[-12:])
            if trend_up:
                pullback_depth = recent_high_15 - pullback_low
                resumed_up = latest_close > latest_open and latest_close >= max(float(c.h) for c in recent_5[:-1])
                if atr15 * 0.25 <= pullback_depth <= atr15 * 2.0 and resumed_up:
                    entry_model = "LIMIT" if latest_close >= ema_fast else "CONFIRM"
                    if entry_model in eligible_entry_models:
                        entry_price = latest_close - atr15 * 0.18 if entry_model == "LIMIT" else latest_close
                        sl = pullback_low - atr15 * 0.18
                        risk = entry_price - sl
                        if risk > atr15 * 0.08:
                            plan = self._build_raw_candle_plan(
                                symbol=symbol,
                                generated_ts=current_ts,
                                family="trend_continuation",
                                entry_model=entry_model,
                                direction="long",
                                entry_price=entry_price,
                                sl=sl,
                                tp1=entry_price + risk,
                                tp2=entry_price + risk * 2.0,
                                tp3=entry_price + risk * 3.0,
                                time_stop_max_bars=24,
                            )
                            if plan is not None:
                                candidates.append(plan)
            if trend_down:
                pullback_depth = pullback_high - recent_low_15
                resumed_down = latest_close < latest_open and latest_close <= min(float(c.l) for c in recent_5[:-1])
                if atr15 * 0.25 <= pullback_depth <= atr15 * 2.0 and resumed_down:
                    entry_model = "LIMIT" if latest_close <= ema_fast else "CONFIRM"
                    if entry_model in eligible_entry_models:
                        entry_price = latest_close + atr15 * 0.18 if entry_model == "LIMIT" else latest_close
                        sl = pullback_high + atr15 * 0.18
                        risk = sl - entry_price
                        if risk > atr15 * 0.08:
                            plan = self._build_raw_candle_plan(
                                symbol=symbol,
                                generated_ts=current_ts,
                                family="trend_continuation",
                                entry_model=entry_model,
                                direction="short",
                                entry_price=entry_price,
                                sl=sl,
                                tp1=entry_price - risk,
                                tp2=entry_price - risk * 2.0,
                                tp3=entry_price - risk * 3.0,
                                time_stop_max_bars=24,
                            )
                            if plan is not None:
                                candidates.append(plan)

        candidates.sort(
            key=lambda plan: (
                0 if str((plan.validity or {}).get("strategy_family") or "") == "trend_continuation" else 1,
                0 if str(plan.entry_model or "").upper() == "LIMIT" else 1,
                str(plan.plan_id or ""),
            )
        )
        return candidates

    def _simulate_symbol_raw_candle_heuristic(
        self,
        *,
        symbol: str,
        start_ts: datetime,
        end_ts: datetime,
        eligible_symbols: set[str],
        eligible_families: set[str],
        eligible_entry_models: set[str],
        generate_on_new_15m_only: bool,
        max_candidates_per_bar: int | None,
        blocked_time_contract: list[dict[str, Any]],
        blocked_plan_ids: set[str],
    ) -> dict[str, Any]:
        candles_5m = self._load_symbol_candles(symbol=symbol, timeframe="5m", start_ts=start_ts, end_ts=end_ts)
        candles_15m = self._load_symbol_candles(symbol=symbol, timeframe="15m", start_ts=start_ts, end_ts=end_ts)
        candles_5m = [candle for candle in candles_5m if self._normalize_ts(candle.ts) is not None]
        candles_15m = [candle for candle in candles_15m if self._normalize_ts(candle.ts) is not None]
        if len(candles_5m) < 72 or len(candles_15m) < 40:
            return {
                "symbol": symbol,
                "eligible_bar_count": 0,
                "generated_contract_candidate_count": 0,
                "selected_contract_candidate_count": 0,
                "closed_trade_count": 0,
                "no_candidate_bar_count": 0,
                "unfilled_candidate_count": 0,
                "open_at_end_candidate_count": 0,
                "trade_rows": [],
            }

        rows: list[dict[str, Any]] = []
        eligible_bar_count = 0
        generated_contract_candidate_count = 0
        selected_contract_candidate_count = 0
        no_candidate_bar_count = 0
        unfilled_candidate_count = 0
        open_at_end_candidate_count = 0
        idx_15 = -1

        for idx_5, candle in enumerate(candles_5m):
            current_ts = self._normalize_ts(candle.ts)
            if current_ts is None:
                continue
            advanced_15m = False
            while idx_15 + 1 < len(candles_15m):
                next_ts = self._normalize_ts(candles_15m[idx_15 + 1].ts)
                if next_ts is None or next_ts > current_ts:
                    break
                idx_15 += 1
                advanced_15m = True
            if idx_5 + 1 < 72 or idx_15 + 1 < 40:
                continue

            eligible_bar_count += 1
            if generate_on_new_15m_only and not advanced_15m:
                continue

            candidates = self._generate_raw_candle_candidates(
                symbol=symbol,
                current_ts=current_ts,
                candles_5m_window=candles_5m[max(0, idx_5 + 1 - 90) : idx_5 + 1],
                candles_15m_window=candles_15m[max(0, idx_15 + 1 - 80) : idx_15 + 1],
                eligible_families=eligible_families,
                eligible_entry_models=eligible_entry_models,
            )
            candidates = [
                plan
                for plan in candidates
                if self._candidate_passes_selection_filters(
                    plan=plan,
                    generated_ts=current_ts,
                    blocked_time_contract=blocked_time_contract,
                    blocked_plan_ids=blocked_plan_ids,
                )
            ]
            generated_contract_candidate_count += len(candidates)
            if not candidates:
                no_candidate_bar_count += 1
                continue

            selected = candidates[: max_candidates_per_bar or len(candidates)]
            for plan in selected:
                selected_contract_candidate_count += 1
                closed_row, status = self._simulate_independent_plan(
                    plan=plan,
                    generated_ts=current_ts,
                    generated_idx_5=idx_5,
                    thesis_key=self._thesis_key(plan),
                    candles_5m=candles_5m,
                )
                if closed_row is not None:
                    rows.append(closed_row)
                elif status == "open_at_end":
                    open_at_end_candidate_count += 1
                else:
                    unfilled_candidate_count += 1

        return {
            "symbol": symbol,
            "eligible_bar_count": int(eligible_bar_count),
            "generated_contract_candidate_count": int(generated_contract_candidate_count),
            "selected_contract_candidate_count": int(selected_contract_candidate_count),
            "closed_trade_count": int(len(rows)),
            "no_candidate_bar_count": int(no_candidate_bar_count),
            "unfilled_candidate_count": int(unfilled_candidate_count),
            "open_at_end_candidate_count": int(open_at_end_candidate_count),
            "trade_rows": rows,
        }

    def _simulate_symbol(
        self,
        *,
        symbol: str,
        start_ts: datetime,
        end_ts: datetime,
        eligible_symbols: set[str],
        eligible_families: set[str],
        eligible_entry_models: set[str],
        generate_on_new_15m_only: bool,
        independent_signal_mode: bool = False,
        max_candidates_per_bar: int | None = None,
        source_mode: str = "engine_regenerated",
        blocked_time_contract: list[dict[str, Any]] | None = None,
        blocked_plan_ids: set[str] | None = None,
    ) -> dict[str, Any]:
        blocked_time_contract = list(blocked_time_contract or [])
        blocked_plan_ids = set(blocked_plan_ids or set())
        if source_mode == "raw_candle_heuristic":
            return self._simulate_symbol_raw_candle_heuristic(
                symbol=symbol,
                start_ts=start_ts,
                end_ts=end_ts,
                eligible_symbols=eligible_symbols,
                eligible_families=eligible_families,
                eligible_entry_models=eligible_entry_models,
                generate_on_new_15m_only=generate_on_new_15m_only,
                max_candidates_per_bar=max_candidates_per_bar,
                blocked_time_contract=blocked_time_contract,
                blocked_plan_ids=blocked_plan_ids,
            )
        if source_mode == "historical_generated_plans":
            return self._simulate_symbol_from_historical_plans(
                symbol=symbol,
                start_ts=start_ts,
                end_ts=end_ts,
                eligible_symbols=eligible_symbols,
                eligible_families=eligible_families,
                eligible_entry_models=eligible_entry_models,
                blocked_time_contract=blocked_time_contract,
                blocked_plan_ids=blocked_plan_ids,
            )
        if independent_signal_mode:
            return self._simulate_symbol_independent(
                symbol=symbol,
                start_ts=start_ts,
                end_ts=end_ts,
                eligible_symbols=eligible_symbols,
                eligible_families=eligible_families,
                eligible_entry_models=eligible_entry_models,
                generate_on_new_15m_only=generate_on_new_15m_only,
                max_candidates_per_bar=max_candidates_per_bar,
                blocked_time_contract=blocked_time_contract,
                blocked_plan_ids=blocked_plan_ids,
            )
        candles_5m = self._load_symbol_candles(symbol=symbol, timeframe="5m", start_ts=start_ts, end_ts=end_ts)
        candles_15m = self._load_symbol_candles(symbol=symbol, timeframe="15m", start_ts=start_ts, end_ts=end_ts)
        candles_5m = [candle for candle in candles_5m if self._normalize_ts(candle.ts) is not None]
        candles_15m = [candle for candle in candles_15m if self._normalize_ts(candle.ts) is not None]
        warmup_5m_bars = max(self._safe_int(self.settings.auto_trading_historical_walk_forward_warmup_5m_bars, 300), 30)
        min_15m_bars = max(self._safe_int(self.settings.auto_trading_historical_walk_forward_min_15m_bars, 60), 30)
        max_5m_window = max(
            self._safe_int(self.settings.auto_trading_historical_walk_forward_max_5m_window_bars, 300),
            warmup_5m_bars,
        )
        max_15m_window = max(
            self._safe_int(self.settings.auto_trading_historical_walk_forward_max_15m_window_bars, 300),
            min_15m_bars,
        )
        if len(candles_5m) < warmup_5m_bars or len(candles_15m) < min_15m_bars:
            return {
                "symbol": symbol,
                "eligible_bar_count": 0,
                "generated_contract_candidate_count": 0,
                "selected_contract_candidate_count": 0,
                "closed_trade_count": 0,
                "no_candidate_bar_count": 0,
                "trade_rows": [],
            }

        rows: list[dict[str, Any]] = []
        existing_zones: list[Zone] = []
        pending: _PendingPlan | None = None
        active: _ActiveTrade | None = None
        blocked_until_by_thesis: dict[str, datetime] = {}
        eligible_bar_count = 0
        generated_contract_candidate_count = 0
        selected_contract_candidate_count = 0
        no_candidate_bar_count = 0
        idx_15 = -1

        for idx_5, candle in enumerate(candles_5m):
            current_ts = self._normalize_ts(candle.ts)
            if current_ts is None:
                continue
            advanced_15m = False
            while idx_15 + 1 < len(candles_15m):
                next_ts = self._normalize_ts(candles_15m[idx_15 + 1].ts)
                if next_ts is None or next_ts > current_ts:
                    break
                idx_15 += 1
                advanced_15m = True
            if idx_5 + 1 < warmup_5m_bars or idx_15 + 1 < min_15m_bars:
                continue

            eligible_bar_count += 1
            fills_happened_this_bar = False

            if pending is not None:
                if current_ts > self._normalize_ts(pending.plan.valid_until):
                    pending = None
                elif current_ts > pending.generated_ts and self._entry_touched(plan=pending.plan, candle=candle):
                    active = _ActiveTrade(
                        plan=pending.plan,
                        generated_ts=pending.generated_ts,
                        entry_ts=current_ts,
                        thesis_key=pending.thesis_key,
                    )
                    pending = None
                    fills_happened_this_bar = True

            if active is not None:
                closed_row = self._advance_active_trade(active=active, candle=candle)
                if closed_row is not None:
                    rows.append(closed_row)
                    blocked_until_by_thesis[active.thesis_key] = current_ts + timedelta(
                        minutes=max(self._safe_int(self.settings.thesis_time_bucket_minutes, 30), 5)
                    )
                    active = None
                    fills_happened_this_bar = True

            if pending is not None or active is not None or fills_happened_this_bar:
                continue
            if generate_on_new_15m_only and not advanced_15m:
                continue

            candles_5m_window = candles_5m[max(0, idx_5 + 1 - max_5m_window) : idx_5 + 1]
            candles_15m_window = candles_15m[max(0, idx_15 + 1 - max_15m_window) : idx_15 + 1]
            existing_zones, ranked = self._generate_ranked_plans(
                symbol=symbol,
                current_ts=current_ts,
                candles_5m=candles_5m_window,
                candles_15m=candles_15m_window,
                existing_zones=existing_zones,
                active_thesis_clusters=0,
            )

            contract_ranked: list[RankedPlan] = []
            for item in ranked:
                if self._contract_matches(
                    plan=item.plan,
                    eligible_symbols=eligible_symbols,
                    eligible_families=eligible_families,
                    eligible_entry_models=eligible_entry_models,
                ) and self._candidate_passes_selection_filters(
                    plan=item.plan,
                    generated_ts=current_ts,
                    blocked_time_contract=blocked_time_contract,
                    blocked_plan_ids=blocked_plan_ids,
                ):
                    contract_ranked.append(item)
            generated_contract_candidate_count += len(contract_ranked)
            chosen: RankedPlan | None = None
            for item in contract_ranked:
                thesis_key = self._thesis_key(item.plan)
                blocked_until = self._normalize_ts(blocked_until_by_thesis.get(thesis_key))
                if blocked_until is not None and current_ts < blocked_until:
                    continue
                chosen = item
                break

            if chosen is None:
                no_candidate_bar_count += 1
                continue

            cloned = self._clone_for_walk_forward(ranked=chosen, generated_ts=current_ts)
            pending = _PendingPlan(
                plan=cloned,
                generated_ts=current_ts,
                thesis_key=self._thesis_key(cloned),
            )
            selected_contract_candidate_count += 1

        return {
            "symbol": symbol,
            "eligible_bar_count": int(eligible_bar_count),
            "generated_contract_candidate_count": int(generated_contract_candidate_count),
            "selected_contract_candidate_count": int(selected_contract_candidate_count),
            "closed_trade_count": int(len(rows)),
            "no_candidate_bar_count": int(no_candidate_bar_count),
            "trade_rows": rows,
        }

    def generate(
        self,
        *,
        eligible_symbols: tuple[str, ...],
        eligible_families: tuple[str, ...],
        eligible_entry_models: tuple[str, ...],
        contract_scope: str,
        cache_key: str,
        generate_on_new_15m_only: bool = False,
        independent_signal_mode: bool = False,
        max_candidates_per_bar: int | None = None,
        source_mode: str = "engine_regenerated",
        blocked_strategy_time_contract_path: str = "",
        blocked_plan_ids_path: str = "",
    ) -> dict[str, Any]:
        normalized_symbols = tuple(str(item or "").strip().upper() for item in eligible_symbols if str(item or "").strip())
        normalized_families = tuple(str(item or "").strip().lower() for item in eligible_families if str(item or "").strip())
        normalized_entry_models = tuple(str(item or "").strip().upper() for item in eligible_entry_models if str(item or "").strip())
        normalized_blocked_strategy_time_contract_path = str(blocked_strategy_time_contract_path or "").strip()
        normalized_blocked_plan_ids_path = str(blocked_plan_ids_path or "").strip()
        latest_source_ts, latest_source_ts_by_symbol, first_source_ts, first_source_ts_by_symbol = self._source_ts_bounds(
            normalized_symbols
        )
        cached = self._load_cached_payload(
            cache_key=cache_key,
            latest_source_ts=latest_source_ts,
            latest_source_ts_by_symbol=latest_source_ts_by_symbol,
            first_source_ts=first_source_ts,
            first_source_ts_by_symbol=first_source_ts_by_symbol,
            generate_on_new_15m_only=generate_on_new_15m_only,
            independent_signal_mode=independent_signal_mode,
            max_candidates_per_bar=max_candidates_per_bar,
            source_mode=source_mode,
            contract_scope=contract_scope,
            eligible_symbols=normalized_symbols,
            eligible_families=normalized_families,
            eligible_entry_models=normalized_entry_models,
            blocked_strategy_time_contract_path=normalized_blocked_strategy_time_contract_path,
            blocked_plan_ids_path=normalized_blocked_plan_ids_path,
        )
        if cached is not None:
            return cached

        blocked_time_contract = self._load_blocked_strategy_time_contract(normalized_blocked_strategy_time_contract_path)
        blocked_plan_ids = self._load_blocked_plan_ids(normalized_blocked_plan_ids_path)

        first_candle_ts: datetime | None = None
        for symbol in normalized_symbols:
            candle = self.candle_repo.get_first_candle(symbol, "5m")
            ts = self._normalize_ts(getattr(candle, "ts", None) if candle is not None else None)
            if ts is None:
                continue
            if first_candle_ts is None or ts < first_candle_ts:
                first_candle_ts = ts
        end_ts = latest_source_ts
        symbol_summaries: list[dict[str, Any]] = []
        trade_rows: list[dict[str, Any]] = []
        if first_candle_ts is not None and end_ts is not None:
            eligible_symbol_set = set(normalized_symbols)
            eligible_family_set = set(normalized_families)
            eligible_entry_model_set = set(normalized_entry_models)
            for symbol in normalized_symbols:
                symbol_payload = self._simulate_symbol(
                    symbol=symbol,
                    start_ts=first_candle_ts,
                    end_ts=end_ts,
                    eligible_symbols=eligible_symbol_set,
                    eligible_families=eligible_family_set,
                    eligible_entry_models=eligible_entry_model_set,
                    generate_on_new_15m_only=generate_on_new_15m_only,
                    independent_signal_mode=independent_signal_mode,
                    max_candidates_per_bar=max_candidates_per_bar,
                    source_mode=source_mode,
                    blocked_time_contract=blocked_time_contract,
                    blocked_plan_ids=blocked_plan_ids,
                )
                symbol_summaries.append({key: value for key, value in symbol_payload.items() if key != "trade_rows"})
                trade_rows.extend(list(symbol_payload.get("trade_rows") or []))

        trade_rows.sort(
            key=lambda row: (
                self._parse_ts(row.get("closed_ts")) or datetime.min.replace(tzinfo=UTC),
                str(row.get("plan_id") or ""),
            )
        )
        payload = {
            "schema_version": self._CACHE_SCHEMA_VERSION,
            "generated_at": datetime.now(UTC).isoformat(),
            "strategy_version": str(self.settings.strategy_version),
            "contract_scope": str(contract_scope or ""),
            "eligible_symbols": list(normalized_symbols),
            "eligible_families": list(normalized_families),
            "eligible_entry_models": list(normalized_entry_models),
            "blocked_strategy_time_contract_path": normalized_blocked_strategy_time_contract_path,
            "blocked_plan_ids_path": normalized_blocked_plan_ids_path,
            "generate_on_new_15m_only": bool(generate_on_new_15m_only),
            "independent_signal_mode": bool(independent_signal_mode),
            "max_candidates_per_bar": None if max_candidates_per_bar is None else int(max_candidates_per_bar),
            "source_mode": str(source_mode or "engine_regenerated"),
            "replay_settings_fingerprint": self._replay_settings_fingerprint(),
            "first_source_ts": first_candle_ts.isoformat() if first_candle_ts is not None else "",
            "first_source_ts_by_symbol": first_source_ts_by_symbol,
            "simulation_start_ts": first_candle_ts.isoformat() if first_candle_ts is not None else "",
            "simulation_end_ts": end_ts.isoformat() if end_ts is not None else "",
            "latest_source_ts": latest_source_ts.isoformat() if latest_source_ts is not None else "",
            "latest_source_ts_by_symbol": latest_source_ts_by_symbol,
            "symbol_summaries": symbol_summaries,
            "trade_rows": trade_rows,
            "summary": (
                f"historical walk-forward {contract_scope}: {len(trade_rows)} closes "
                f"across {len(normalized_symbols)} symbols"
            ),
        }
        self._store_cached_payload(cache_key=cache_key, payload=payload)
        return payload
