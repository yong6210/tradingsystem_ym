from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path
from typing import Any, ClassVar

from app.core.config import ROOT_DIR, Settings, get_settings
from app.core.enums import ApprovalState, EntryModel, ExecutionMode, PlanState
from app.db.models import Plan
from app.services.common import clamp
from app.services.family_rollout import RolloutPolicyBootstrap
from app.services.safety_locks import SafetyLockService

_MODE_RANK = {
    ExecutionMode.SHADOW: 0,
    ExecutionMode.PAPER: 1,
    ExecutionMode.MICRO_LIVE: 2,
    ExecutionMode.LIVE: 3,
}


class ExecutionPlanningService:
    _PAPER_LINEAGE_OVERRIDE_FAMILIES: ClassVar[set[str]] = {"trend_continuation", "sweep_reversal"}
    _PAPER_LINEAGE_OVERRIDE_BLOCKS: ClassVar[set[str]] = {"thesis_duplicate_blocked", "thesis_active_cap_reached"}

    def __init__(
        self,
        settings: Settings | None = None,
        rollout_provider: Any | None = None,
    ):
        self.settings = settings or get_settings()
        self.rollout = rollout_provider or RolloutPolicyBootstrap()

    @staticmethod
    def _csv_set(value: str) -> set[str]:
        items = [item.strip().upper() for item in str(value or "").split(",") if item.strip()]
        return set(items)

    @staticmethod
    def _text(value: Any, default: str = "") -> str:
        return str(value or default)

    @staticmethod
    def _bool(value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value) if isfinite(float(value)) else False
        text = str(value).strip().lower()
        if text in {"1", "true", "yes", "y", "on"}:
            return True
        if text in {"0", "false", "no", "n", "off", "none", "null", ""}:
            return False
        return False

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        if value in (None, "", "None"):
            return default
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return default
        return parsed if isfinite(parsed) else default

    @staticmethod
    def _safe_int(value: Any, default: int = 0) -> int:
        if value in (None, "", "None"):
            return default
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return default
        return int(parsed) if isfinite(parsed) else default

    def _risk_allocator_contract(
        self,
        *,
        base_recommended_risk_r: float,
        candidate: dict[str, Any],
        validity: dict[str, Any],
        execution_mode: ExecutionMode,
    ) -> dict[str, Any]:
        capital_allocator = dict(candidate.get("capital_allocator") or validity.get("capital_allocator") or {})
        candidate_allocated_risk = candidate.get("allocated_risk_r")
        raw_allocated_risk = (
            candidate_allocated_risk
            if candidate_allocated_risk is not None and str(candidate_allocated_risk).strip() != ""
            else capital_allocator.get("allocated_risk_r", validity.get("allocated_risk_r"))
        )
        allocated_risk_r = self._safe_float(raw_allocated_risk, default=base_recommended_risk_r)
        if allocated_risk_r <= 0.0 and base_recommended_risk_r > 0.0:
            allocated_risk_r = base_recommended_risk_r
        allocation_weight = self._safe_float(
            candidate.get("allocation_weight", capital_allocator.get("allocation_weight", 1.0)),
            default=1.0,
        )
        enabled = self._bool(getattr(self.settings, "auto_trading_live_weighted_risk_allocator_enabled", True))
        live_mode = execution_mode in {ExecutionMode.MICRO_LIVE, ExecutionMode.LIVE}
        weighted_risk_r = base_recommended_risk_r
        applied = False
        reason_codes: list[str] = []
        if enabled and live_mode:
            weighted_risk_r = allocated_risk_r
            applied = abs(weighted_risk_r - base_recommended_risk_r) > 1e-9
            reason_codes.append("capital_allocator_weighted_risk")
        elif not enabled:
            reason_codes.append("weighted_allocator_disabled")
        else:
            reason_codes.append("non_live_execution_mode")

        max_risk_r = self._safe_float(
            getattr(self.settings, "auto_trading_live_weighted_risk_max_r", 1.0),
            default=1.0,
        )
        capped = False
        if live_mode and max_risk_r > 0.0 and weighted_risk_r > max_risk_r:
            weighted_risk_r = max_risk_r
            capped = True
            applied = True
            reason_codes.append("single_position_risk_cap")

        weighted_risk_r = round(max(weighted_risk_r, 0.0), 4)
        return {
            "enabled": bool(enabled),
            "applied": bool(applied),
            "live_mode": bool(live_mode),
            "base_recommended_risk_r": round(max(base_recommended_risk_r, 0.0), 4),
            "allocated_risk_r": round(max(allocated_risk_r, 0.0), 4),
            "allocation_weight": round(max(allocation_weight, 0.0), 4),
            "risk_sizing_r": weighted_risk_r,
            "max_risk_r": round(max_risk_r, 4),
            "capped": bool(capped),
            "capital_allocator_tier": str(capital_allocator.get("tier") or "neutral"),
            "capital_pressure": str(capital_allocator.get("capital_pressure") or "neutral"),
            "reason_codes": list(dict.fromkeys(reason_codes)),
        }

    @staticmethod
    def _symbol_list(values: list[Any] | None, *, limit: int = 4) -> str:
        symbols = [str(item or "").upper() for item in list(values or []) if str(item or "").strip()]
        if not symbols:
            return ""
        deduped = list(dict.fromkeys(symbols))
        head = deduped[: max(int(limit), 1)]
        if len(deduped) > len(head):
            head.append(f"+{len(deduped) - len(head)} more")
        return ", ".join(head)

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def coerce_execution_mode(value: Any, default: ExecutionMode = ExecutionMode.SHADOW) -> ExecutionMode:
        try:
            return value if isinstance(value, ExecutionMode) else ExecutionMode(str(value or default.value).upper())
        except ValueError:
            return default

    @classmethod
    def execution_mode_leq(cls, left: ExecutionMode, right: ExecutionMode) -> bool:
        return _MODE_RANK[left] <= _MODE_RANK[right]

    @classmethod
    def min_execution_mode(cls, left: ExecutionMode, right: ExecutionMode) -> ExecutionMode:
        return left if cls.execution_mode_leq(left, right) else right

    def active_execution_mode(self) -> ExecutionMode:
        return self.coerce_execution_mode(self.settings.auto_trading_execution_mode, default=ExecutionMode.SHADOW)

    def allowed_symbols(self) -> set[str]:
        return self._csv_set(self.settings.auto_trading_allowed_symbols)

    def allowed_families(self) -> set[str]:
        return {item.lower() for item in self._csv_set(self.settings.auto_trading_allowed_families)}

    def micro_live_allowed_symbols(self) -> set[str]:
        return self._csv_set(getattr(self.settings, "auto_trading_micro_live_allowed_symbols", ""))

    def micro_live_allowed_families(self) -> set[str]:
        return {item.lower() for item in self._csv_set(getattr(self.settings, "auto_trading_micro_live_allowed_families", ""))}

    def micro_live_allowed_entry_models(self) -> set[str]:
        return self._csv_set(getattr(self.settings, "auto_trading_micro_live_allowed_entry_models", ""))

    def micro_live_allowed_sessions(self) -> set[str]:
        items = [item.strip().lower() for item in str(self.settings.auto_trading_micro_live_allowed_sessions or "").split(",") if item.strip()]
        return set(items)

    @staticmethod
    def _entry_model_rejection_code(allowed_entry_models: set[str]) -> str:
        normalized = {str(item or "").strip().upper() for item in set(allowed_entry_models or set()) if str(item or "").strip()}
        if normalized == {EntryModel.LIMIT.value}:
            return "live_limit_only_entry_required"
        return "live_entry_model_not_allowed"

    def micro_live_direction_contract(self) -> dict[str, set[str]]:
        mapping: dict[str, set[str]] = {}
        raw = str(getattr(self.settings, "auto_trading_micro_live_direction_contract", "") or "")
        for item in raw.split(","):
            token = item.strip()
            if not token or ":" not in token:
                continue
            symbol, raw_directions = token.split(":", 1)
            normalized_symbol = str(symbol or "").strip().upper()
            if not normalized_symbol:
                continue
            directions = {
                direction.strip().upper()
                for direction in str(raw_directions or "").replace("/", "|").split("|")
                if direction.strip()
            }
            if directions:
                mapping[normalized_symbol] = directions
        return mapping

    def micro_live_session_direction_blocked_hours(self) -> dict[tuple[str, str, str], set[int]]:
        mapping: dict[tuple[str, str, str], set[int]] = {}
        raw = str(getattr(self.settings, "auto_trading_micro_live_session_direction_blocked_hours_utc", "") or "")
        for item in raw.split(","):
            token = item.strip()
            if not token:
                continue
            parts = [part.strip() for part in token.split(":", 3)]
            if len(parts) != 4:
                continue
            symbol, session_name, direction, raw_hours = parts
            normalized_symbol = str(symbol or "").strip().upper()
            normalized_session = str(session_name or "").strip().lower()
            normalized_direction = str(direction or "").strip().upper()
            if not normalized_symbol or not normalized_session or not normalized_direction:
                continue
            hours: set[int] = set()
            for raw_hour in str(raw_hours or "").replace("/", "|").split("|"):
                text = raw_hour.strip()
                if not text:
                    continue
                try:
                    hour = int(text)
                except ValueError:
                    continue
                if 0 <= hour <= 23:
                    hours.add(hour)
            if hours:
                mapping[(normalized_symbol, normalized_session, normalized_direction)] = hours
        return mapping

    def micro_live_symbol_family_entry_direction_blocked_hours(self) -> dict[tuple[str, str, str, str], set[int]]:
        mapping: dict[tuple[str, str, str, str], set[int]] = {}
        raw = str(
            getattr(self.settings, "auto_trading_micro_live_symbol_family_entry_direction_blocked_hours_utc", "") or ""
        )
        for item in raw.split(","):
            token = item.strip()
            if not token:
                continue
            parts = [part.strip() for part in token.split(":", 4)]
            if len(parts) != 5:
                continue
            symbol, family, entry_model, direction, raw_hours = parts
            normalized_symbol = str(symbol or "").strip().upper()
            normalized_family = str(family or "").strip().lower()
            normalized_entry_model = str(entry_model or "").strip().upper()
            normalized_direction = str(direction or "").strip().upper()
            if not normalized_symbol or not normalized_family or not normalized_entry_model or not normalized_direction:
                continue
            hours: set[int] = set()
            for raw_hour in str(raw_hours or "").replace("/", "|").split("|"):
                text = raw_hour.strip()
                if not text:
                    continue
                try:
                    hour = int(text)
                except ValueError:
                    continue
                if 0 <= hour <= 23:
                    hours.add(hour)
            if hours:
                mapping[(normalized_symbol, normalized_family, normalized_entry_model, normalized_direction)] = hours
        return mapping

    def micro_live_strategy_time_contract(
        self,
    ) -> list[dict[str, Any]]:
        raw_path = str(getattr(self.settings, "auto_trading_micro_live_strategy_time_contract_path", "") or "").strip()
        if not raw_path:
            return []
        path = self._runtime_contract_path(raw_path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        entries = self._json_list_payload(payload, key="blocked_buckets")
        contract: list[dict[str, Any]] = []
        for item in entries:
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
                contract.append(normalized)
        return contract

    @staticmethod
    def _parse_utc_timestamp(value: Any) -> datetime | None:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        return ExecutionPlanningService._utc(parsed)

    def micro_live_event_blackouts(self) -> list[dict[str, Any]]:
        raw_path = str(getattr(self.settings, "auto_trading_micro_live_event_blackout_path", "") or "").strip()
        if not raw_path:
            return []
        path = self._runtime_contract_path(raw_path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        entries = self._json_list_payload(payload, key="windows")
        windows: list[dict[str, Any]] = []
        for item in entries:
            row = dict(item or {})
            start_utc = self._parse_utc_timestamp(row.get("start_utc"))
            end_utc = self._parse_utc_timestamp(row.get("end_utc"))
            if start_utc is None or end_utc is None or end_utc <= start_utc:
                continue
            normalized: dict[str, Any] = {
                "label": str(row.get("label") or "").strip(),
                "start_utc": start_utc,
                "end_utc": end_utc,
                "symbols": {
                    str(item or "").strip().upper()
                    for item in list(row.get("symbols") or [])
                    if str(item or "").strip()
                },
                "strategy_families": {
                    str(item or "").strip().lower()
                    for item in list(row.get("strategy_families") or [])
                    if str(item or "").strip()
                },
                "entry_models": {
                    str(item or "").strip().upper()
                    for item in list(row.get("entry_models") or [])
                    if str(item or "").strip()
                },
                "directions": {
                    str(item or "").strip().upper()
                    for item in list(row.get("directions") or [])
                    if str(item or "").strip()
                },
                "sessions": {
                    str(item or "").strip().lower()
                    for item in list(row.get("sessions") or [])
                    if str(item or "").strip()
                },
            }
            windows.append(normalized)
        return windows

    @staticmethod
    def _matches_event_blackout(
        current_utc: datetime,
        *,
        symbol: str,
        family: str,
        entry_model: str,
        direction: str,
        session_name: str,
        blackout_row: dict[str, Any],
    ) -> bool:
        start_utc = blackout_row.get("start_utc")
        end_utc = blackout_row.get("end_utc")
        if not isinstance(start_utc, datetime) or not isinstance(end_utc, datetime):
            return False
        if not (start_utc <= current_utc < end_utc):
            return False
        symbols = set(blackout_row.get("symbols") or set())
        if symbols and symbol not in symbols:
            return False
        families = set(blackout_row.get("strategy_families") or set())
        if families and family not in families:
            return False
        entry_models = set(blackout_row.get("entry_models") or set())
        if entry_models and entry_model not in entry_models:
            return False
        directions = set(blackout_row.get("directions") or set())
        if directions and direction not in directions:
            return False
        sessions = set(blackout_row.get("sessions") or set())
        if sessions and session_name not in sessions:
            return False
        return True

    def micro_live_plan_blocklist(self) -> set[str]:
        raw_path = str(getattr(self.settings, "auto_trading_micro_live_plan_blocklist_path", "") or "").strip()
        if not raw_path:
            return set()
        path = self._runtime_contract_path(raw_path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return set()
        plan_ids = self._json_list_payload(payload, key="blocked_plan_ids")
        return {
            str(plan_id or "").strip()
            for plan_id in plan_ids
            if str(plan_id or "").strip()
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

    @staticmethod
    def _runtime_contract_path(raw_path: str) -> Path:
        path = Path(str(raw_path or "")).expanduser()
        if path.is_absolute():
            return path
        return (ROOT_DIR / path).resolve()

    @staticmethod
    def _entry_type(entry_model: str) -> str:
        model = str(entry_model or "").upper()
        if model == EntryModel.LIMIT.value:
            return "limit"
        return "stop_market"

    @staticmethod
    def _matches_strategy_time_bucket(
        current_utc: datetime,
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
            "year_utc": int(current_utc.year),
            "month_utc": int(current_utc.month),
            "day_utc": int(current_utc.day),
            "weekday_utc": int(current_utc.weekday()),
            "hour_utc": int(current_utc.hour),
            "minute_utc": int(current_utc.minute),
        }
        for key, actual in checks.items():
            expected = contract_row.get(key)
            if expected is None:
                continue
            if int(expected) != actual:
                return False
        return True

    @staticmethod
    def _entry_semantics(entry_model: str) -> str:
        model = str(entry_model or "").upper()
        if model == EntryModel.LIMIT.value:
            return "limit on touch"
        if model == EntryModel.CONFIRM.value:
            return "touch then confirm"
        if model == EntryModel.SWEEP_CONFIRM.value:
            return "sweep then confirm"
        return "server plan required"

    @classmethod
    def _tp_targets(cls, plan: Plan) -> list[dict[str, Any]]:
        split = dict(plan.split or {})
        return [
            {"label": "TP1", "price": cls._safe_float(plan.tp1), "size_fraction": cls._safe_float(split.get("tp1"))},
            {"label": "TP2", "price": cls._safe_float(plan.tp2), "size_fraction": cls._safe_float(split.get("tp2"))},
            {"label": "TP3", "price": cls._safe_float(plan.tp3), "size_fraction": cls._safe_float(split.get("runner"))},
        ]

    @classmethod
    def _session_name(cls, candidate: dict[str, Any], operating_lock: dict[str, Any]) -> str:
        session_guidance = dict(candidate.get("session_guidance") or {})
        guidance_state = str(session_guidance.get("state") or "").strip().lower()
        if guidance_state == "dead_session" or cls._bool(session_guidance.get("dead_session")):
            return "dead_session"

        current_session = dict(operating_lock or {}).get("current_session") or {}
        guidance_current_session = dict(session_guidance.get("current_session") or {})
        for value in (
            current_session.get("name"),
            guidance_current_session.get("name"),
            session_guidance.get("session_name"),
            guidance_state,
        ):
            session_name = str(value or "").strip().lower()
            if not session_name:
                continue
            if session_name == "inactive":
                return "dead_session"
            return session_name
        return "unknown"

    @staticmethod
    def _rollout_reason(allowed_mode: ExecutionMode) -> tuple[str, str]:
        if allowed_mode == ExecutionMode.SHADOW:
            return "rollout_shadow_only", "Rollout policy currently allows shadow-only tracking for this family."
        if allowed_mode == ExecutionMode.PAPER:
            return "paper_rollout_enabled", "Plan is approved for automated paper execution under the current family rollout cap."
        if allowed_mode == ExecutionMode.MICRO_LIVE:
            return "micro_live_rollout_enabled", "Plan is approved for automated micro-live execution under the current rollout cap."
        return "live_rollout_enabled", "Plan is approved for automated live execution under the current rollout cap."

    @staticmethod
    def _playbook_contract(state: ApprovalState, *, reason_code: str, reason: str) -> dict[str, str]:
        if state == ApprovalState.BLOCKED:
            return {
                "playbook_go_no_go": "NO_GO",
                "playbook_code": reason_code or "no_go_execution_blocked",
                "playbook_action": "block_new_entries_until_execution_issue_is_cleared",
                "playbook_message": reason,
            }
        if state == ApprovalState.APPROVED_MANUAL:
            return {
                "playbook_go_no_go": "MANUAL_REVIEW",
                "playbook_code": reason_code or "manual_review_execution_gate",
                "playbook_action": "review_execution_gate_before_submit",
                "playbook_message": reason,
            }
        if state == ApprovalState.APPROVED_SHADOW:
            return {
                "playbook_go_no_go": "GO",
                "playbook_code": reason_code or "go_shadow_only_execution",
                "playbook_action": "record_shadow_only_execution_path",
                "playbook_message": reason,
            }
        return {
            "playbook_go_no_go": "GO",
            "playbook_code": reason_code or "go_execution_auto_submit",
            "playbook_action": "allow_auto_submit",
            "playbook_message": reason,
        }

    @staticmethod
    def _outcome_penalty_reason(code: str, message: str) -> dict[str, Any]:
        return {
            "code": code,
            "message": message,
            "blocking": False,
        }

    @staticmethod
    def _find_axis_bucket(rows: list[dict[str, Any]] | None, bucket: str) -> dict[str, Any]:
        target = str(bucket or "")
        for row in rows or []:
            if str(row.get("bucket") or row.get("key") or "") == target:
                return dict(row)
        return {}

    @staticmethod
    def _find_decomposition_bucket(payload: dict[str, Any] | None, *, axis: str, bucket: str) -> dict[str, Any]:
        rows = list(dict(payload or {}).get("decomposition", {}).get(axis, []) or [])
        target = str(bucket or "")
        for row in rows:
            if str(row.get("key") or "") == target:
                return dict(row)
        return {}

    @staticmethod
    def _thin_sample_from_mode_row(row: dict[str, Any]) -> bool:
        if not row:
            return True
        if str(row.get("confidence") or "low") == "low":
            return True
        sample_note = str(row.get("sample_note") or "").lower()
        return "thin" in sample_note

    def _outcome_approval_penalty(
        self,
        *,
        executable_plan: dict[str, Any],
        candidate_row: dict[str, Any] | None,
        safety_state: dict[str, Any] | None = None,
        outcome_inputs: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        payload = dict(outcome_inputs or {})
        if not payload:
            return None

        execution_degradation = dict(payload.get("execution_degradation_advisory_summary") or {})
        mode_advisory = dict(payload.get("mode_advisory_summary") or {})
        score_to_outcome = dict(payload.get("score_to_outcome_funnel_summary") or {})
        if not any([execution_degradation, mode_advisory, score_to_outcome]):
            return None

        family = str(executable_plan.get("strategy_family") or "unknown")
        safety = dict(safety_state or {})
        sir_rollout_readiness = dict(safety.get("session_impulse_retest_rollout_readiness") or {})
        sir_rollout_status = str(sir_rollout_readiness.get("status") or "")
        regime = str(dict(executable_plan.get("context_snapshot") or {}).get("regime") or "unknown")
        candidate = dict(candidate_row or {})
        session_name = self._session_name(candidate, dict(candidate.get("operating_lock") or {}))

        family_mode = self._find_axis_bucket(list(mode_advisory.get("family") or []), family)
        regime_mode = self._find_axis_bucket(list(mode_advisory.get("regime") or []), regime)
        session_mode = self._find_axis_bucket(list(mode_advisory.get("session") or []), session_name)

        family_funnel = self._find_decomposition_bucket(score_to_outcome, axis="family", bucket=family)
        regime_funnel = self._find_decomposition_bucket(score_to_outcome, axis="regime", bucket=regime)
        session_funnel = self._find_decomposition_bucket(score_to_outcome, axis="session", bucket=session_name)

        degradation_status = str(execution_degradation.get("status") or "healthy").lower()
        degradation_advisory_only = self._bool(execution_degradation.get("advisory_only"))
        degradation_sample = dict(execution_degradation.get("sample_context") or {})
        material_degradation_sample = (not degradation_advisory_only) and any(
            self._safe_int(degradation_sample.get(key), default=0) > 0
            for key in ("plans_matured", "fill_events_total", "closed_plans")
        )
        mode_rows = [row for row in [family_mode, regime_mode, session_mode] if row]
        adverse_mode_rows = [
            row
            for row in mode_rows
            if str(row.get("advisory_state") or "") in {"watch", "research_only"} and not self._thin_sample_from_mode_row(row)
        ]

        reason_codes: list[str] = []
        if degradation_status in {"watch", "manual_review"}:
            reason_codes.append(f"execution_degradation:{degradation_status}")

        for axis, row in (("family", family_mode), ("regime", regime_mode), ("session", session_mode)):
            advisory_state = str(row.get("advisory_state") or "")
            if advisory_state in {"watch", "research_only"} and not self._thin_sample_from_mode_row(row):
                reason_codes.append(f"mode_advisory:{axis}:{advisory_state}")

        post_cost_reason = None
        post_cost_rate = None
        post_cost_closed = 0
        for axis, row in (("family", family_funnel), ("regime", regime_funnel), ("session", session_funnel)):
            closed = int(row.get("closed", 0) or 0)
            rate = float(row.get("baseline_cost_profitable_rate_from_closed", 0.0) or 0.0)
            if closed >= 4 and rate <= 0.3:
                post_cost_reason = f"post_cost_conversion:weak_{axis}_alignment"
                post_cost_rate = rate
                post_cost_closed = closed
                break

        if post_cost_reason:
            reason_codes.append(post_cost_reason)

        deduped_reason_codes = list(dict.fromkeys(reason_codes))
        if not deduped_reason_codes:
            return {
                "available": True,
                "status": "healthy",
                "penalty_tier": "none",
                "applied": False,
                "summary": "outcome-aware approval penalty found no material degradation or post-cost conversion issue",
                "reason_codes": [],
                "source_summary": {
                    "execution_degradation_status": degradation_status or "healthy",
                    "mode_advisory_state": str((adverse_mode_rows[:1] or [{}])[0].get("advisory_state") or "keep_current_mode"),
                    "baseline_cost_profitable_rate_from_closed": float(
                        dict(score_to_outcome.get("historical_execution_outcomes") or {}).get(
                            "baseline_cost_profitable_rate_from_closed",
                            0.0,
                        )
                        or 0.0
                    ),
                },
            }

        status = "watch"
        penalty_tier = "reason_only"
        sir_bootstrap_outcome_advisory_only = (
            family == "session_impulse_retest"
            and sir_rollout_status == "live_bootstrap_collecting"
            and not material_degradation_sample
        )
        if (
            degradation_status == "manual_review"
            and not degradation_advisory_only
            and not sir_bootstrap_outcome_advisory_only
        ) or (
            post_cost_reason and adverse_mode_rows
        ):
            status = "manual_review"
            penalty_tier = "downgrade_to_manual"
        if sir_bootstrap_outcome_advisory_only:
            status = "watch"
            penalty_tier = "reason_only"

        summary = "execution degradation and post-cost outcome signals require closer review before new live entries"
        if penalty_tier == "downgrade_to_manual":
            summary = "execution degradation and post-cost outcome signals require manual review before new live entries"
        elif sir_bootstrap_outcome_advisory_only:
            summary = "SIR live bootstrap has no material live execution sample yet; outcome controls stay advisory until closes accumulate"

        return {
            "available": True,
            "status": status,
            "penalty_tier": penalty_tier,
            "applied": True,
            "summary": summary,
            "reason_codes": deduped_reason_codes,
            "source_summary": {
                "execution_degradation_status": degradation_status or "healthy",
                "mode_advisory_state": str((adverse_mode_rows[:1] or [{}])[0].get("advisory_state") or "keep_current_mode"),
                "baseline_cost_profitable_rate_from_closed": (
                    float(post_cost_rate)
                    if isinstance(post_cost_rate, float)
                    else float(
                        dict(score_to_outcome.get("historical_execution_outcomes") or {}).get(
                            "baseline_cost_profitable_rate_from_closed",
                            0.0,
                        )
                        or 0.0
                    )
                ),
                "post_cost_closed": int(post_cost_closed),
                "execution_degradation_policy": (
                    "advisory_until_material_sir_live_execution_sample"
                    if sir_bootstrap_outcome_advisory_only
                    else "advisory_only"
                    if degradation_advisory_only
                    else "standard"
                ),
            },
        }

    def build_executable_plan(
        self,
        *,
        plan: Plan,
        context: Any | None,
        candidate_row: dict[str, Any] | None,
        execution_mode: ExecutionMode | None = None,
    ) -> dict[str, Any]:
        validity = dict(plan.validity or {})
        candidate = dict(candidate_row or {})
        effective_mode = execution_mode or self.active_execution_mode()
        base_recommended_risk_r = self._safe_float(
            validity.get("recommended_risk_r", candidate.get("recommended_risk_r", 0.0))
        )
        risk_allocator = self._risk_allocator_contract(
            base_recommended_risk_r=base_recommended_risk_r,
            candidate=candidate,
            validity=validity,
            execution_mode=effective_mode,
        )
        recommended_risk_r = self._safe_float(risk_allocator.get("risk_sizing_r"), default=base_recommended_risk_r)
        family = self._text(validity.get("strategy_family"), "legacy_zone_plan").lower()
        tf = self._text(plan.timeframe, "5m")
        valid_for_seconds = max(
            0,
            int((self._utc(plan.valid_until) - datetime.now(timezone.utc)).total_seconds()),
        )
        transition_edge_variant_payload = dict(validity.get("transition_edge_variant") or candidate.get("transition_edge_variant") or {})
        transition_edge_variant_applied = self._bool(
            validity.get("transition_edge_variant_applied")
            or candidate.get("transition_edge_variant_applied")
        )
        entry_model = self._text(plan.entry_model)
        entry_type = self._entry_type(entry_model)
        entry_price = self._safe_float(plan.entry_price)
        entry_trigger_price = entry_price if entry_type != "limit" else None
        entry_limit_price = entry_price if entry_type == "limit" else None
        timeout_seconds = min(max(valid_for_seconds, 0), 900 if entry_type == "limit" else 1200)
        scorecard = dict(validity.get("strategy_scorecard") or {})
        return {
            "plan_id": plan.plan_id,
            "symbol": plan.symbol,
            "tf": tf,
            "strategy_version": plan.strategy_version,
            "strategy_family": family,
            "strategy_mode": self._text(validity.get("strategy_mode"), getattr(self.settings.strategy_mode, "value", "A_ONLY")),
            "execution_mode": effective_mode.value,
            "transition_edge_variant_applied": transition_edge_variant_applied,
            "transition_edge_variant_variant": self._text(transition_edge_variant_payload.get("variant")),
            "thesis_fingerprint": validity.get("thesis_fingerprint") or candidate.get("thesis_fingerprint"),
            "thesis_cluster_id": self._text(validity.get("thesis_cluster_id") or candidate.get("thesis_cluster_id")),
            "thesis_primary_symbol": self._text(
                validity.get("thesis_primary_symbol") or candidate.get("thesis_primary_symbol") or plan.symbol
            ),
            "direction": plan.direction,
            "setup_grade": self._text(validity.get("strategy_grade"), candidate.get("strategy_grade") or "B"),
            "setup_score": self._safe_float(
                validity.get("strategy_family_score", validity.get("confluence_score", candidate.get("final_rank_score", 0.0)))
            ),
            "entry_model": entry_model,
            "entry_type": entry_type,
            "entry_semantics": self._entry_semantics(entry_model),
            "entry_trigger_price": entry_trigger_price,
            "entry_limit_price": entry_limit_price,
            "entry_timeout_seconds": timeout_seconds,
            "cancel_if_not_filled": True,
            "stop_price": self._safe_float(plan.sl),
            "tp_targets": self._tp_targets(plan),
            "recommended_risk_r": recommended_risk_r,
            "base_recommended_risk_r": risk_allocator["base_recommended_risk_r"],
            "allocated_risk_r": risk_allocator["allocated_risk_r"],
            "allocation_weight": risk_allocator["allocation_weight"],
            "risk_sizing_r": risk_allocator["risk_sizing_r"],
            "risk_allocator": risk_allocator,
            "max_position_notional": round(
                max(0.0, recommended_risk_r) * self._safe_float(self.settings.auto_trading_notional_per_r, default=25.0),
                4,
            ),
            "expected_fee_bps": self._safe_float(
                self.settings.taker_fee_bps if entry_type != "limit" else self.settings.maker_fee_bps,
                default=4.0 if entry_type != "limit" else 2.0,
            ),
            "max_slippage_bps": self._safe_float(self.settings.auto_trading_max_slippage_bps, default=12.0),
            "valid_from": self._utc(plan.valid_from),
            "valid_until": self._utc(plan.valid_until),
            "kill_if_transition_lock": True,
            "kill_if_regime_changes": True,
            "expected_summary": {
                "expected_win_prob": self._safe_float(candidate.get("expected_win_prob", validity.get("expected_win_prob", 0.0))),
                "expected_ev_r": self._safe_float(candidate.get("expected_ev_r", validity.get("expected_ev_r", plan.ev))),
                "expected_source": "runtime_candidate_overlay",
                "expected_summary": self._text(candidate.get("expected_summary"), validity.get("expected_summary", "")),
            },
            "context_snapshot": {
                "regime": self._text(validity.get("regime"), candidate.get("regime") or "range"),
                "risk_label": self._text((candidate.get("session_guidance") or {}).get("risk_label"), candidate.get("risk_reason") or "normal"),
                "transition_state": self._text(validity.get("transition_state"), getattr(context, "transition_state", "none")),
                "session_guidance": self._text((candidate.get("session_guidance") or {}).get("state"), "unknown"),
                "portfolio_headroom_state": "open" if self._bool(candidate.get("accepted")) else "constrained",
                "deployment_go_no_go": self._text(candidate.get("deployment_go_no_go"), "MANUAL_REVIEW"),
                "block_reason": self._text(candidate.get("block_reason")),
                "block_reason_message": self._text(candidate.get("block_reason_message")),
            },
            "mirror_plan_note": "chart score != deployment approval; chart plan != live order instruction",
            "strategy_scorecard_buckets": dict(scorecard.get("buckets") or validity.get("strategy_scorecard_buckets") or {}),
            "strategy_scorecard_raw_components": dict(scorecard.get("raw_components") or validity.get("strategy_scorecard_raw_components") or {}),
        }

    @staticmethod
    def _transition_edge_variant_applied(
        *,
        plan: Plan,
        executable_plan: dict[str, Any],
        candidate: dict[str, Any],
    ) -> bool:
        validity = dict(plan.validity or {})
        return ExecutionPlanningService._bool(
            executable_plan.get("transition_edge_variant_applied")
            or candidate.get("transition_edge_variant_applied")
            or validity.get("transition_edge_variant_applied")
        )

    @staticmethod
    def _transition_edge_variant_name(
        *,
        plan: Plan,
        executable_plan: dict[str, Any],
        candidate: dict[str, Any],
    ) -> str:
        validity = dict(plan.validity or {})
        payload = dict(executable_plan.get("transition_edge_variant") or {})
        payload.update(dict(candidate.get("transition_edge_variant") or {}))
        payload.update(dict(validity.get("transition_edge_variant") or {}))
        return str(
            executable_plan.get("transition_edge_variant_variant")
            or payload.get("variant")
            or ""
        )

    @staticmethod
    def _stable_fraction(seed: str) -> float:
        digest = hashlib.sha1(seed.encode("utf-8")).digest()
        numerator = int.from_bytes(digest[:8], "big", signed=False)
        denominator = float((1 << 64) - 1)
        return numerator / denominator if denominator > 0 else 0.0

    def _transition_edge_variant_sampling_decision(
        self,
        *,
        plan: Plan,
        executable_plan: dict[str, Any],
    ) -> tuple[bool, float | None, float]:
        ratio = clamp(self._safe_float(self.settings.transition_edge_variant_partial_activation_ratio, default=0.3), 0.0, 1.0)
        if ratio <= 0.0:
            return False, None, ratio
        if ratio >= 1.0:
            return True, 0.0, ratio
        cluster_id = str(executable_plan.get("thesis_cluster_id") or "").strip()
        seed = "|".join(
            [
                str(plan.plan_id or ""),
                str(plan.symbol or ""),
                str(plan.direction or ""),
                cluster_id,
                str(executable_plan.get("transition_edge_variant_variant") or ""),
            ]
        )
        fraction = self._stable_fraction(seed)
        return fraction < ratio, fraction, ratio

    def _session_impulse_retest_sampling_decision(
        self,
        *,
        plan: Plan,
        executable_plan: dict[str, Any],
    ) -> tuple[bool, float | None, float]:
        ratio = clamp(
            self._safe_float(getattr(self.settings, "session_impulse_retest_partial_activation_ratio", 0.0), default=0.3),
            0.0,
            1.0,
        )
        if ratio <= 0.0:
            return False, None, ratio
        if ratio >= 1.0:
            return True, 0.0, ratio
        cluster_id = str(executable_plan.get("thesis_cluster_id") or "").strip()
        seed = "|".join(
            [
                str(plan.plan_id or ""),
                str(plan.symbol or ""),
                str(plan.direction or ""),
                cluster_id,
                "session_impulse_retest",
            ]
        )
        fraction = self._stable_fraction(seed)
        return fraction < ratio, fraction, ratio

    def approve(
        self,
        *,
        plan: Plan,
        executable_plan: dict[str, Any],
        candidate_row: dict[str, Any] | None,
        metrics: dict[str, Any],
        requested_execution_mode: ExecutionMode | None = None,
        strict_requested_mode: bool = False,
        safety_state: dict[str, Any] | None = None,
        current_exposure_count: int = 0,
        daily_new_entry_count: int = 0,
        live_cluster_guard: dict[str, Any] | None = None,
        micro_live_symbol_priority_guard: dict[str, Any] | None = None,
        paper_lineage_override: bool = False,
        outcome_inputs: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        candidate = dict(candidate_row or {})
        safety = dict(safety_state or {})
        cluster_guard = dict(live_cluster_guard or {})
        symbol_priority_guard = dict(micro_live_symbol_priority_guard or {})
        requested_mode = self.coerce_execution_mode(requested_execution_mode or executable_plan.get("execution_mode"))
        family = str(executable_plan.get("strategy_family") or "legacy_zone_plan").lower()
        rollout_policy = self.rollout.get(family)
        allowed_execution_mode = self.min_execution_mode(requested_mode, rollout_policy.max_execution_mode)

        symbol = str(plan.symbol or "").upper()
        transition_edge_variant_applied = self._transition_edge_variant_applied(
            plan=plan,
            executable_plan=executable_plan,
            candidate=candidate,
        )
        transition_edge_variant_variant = self._transition_edge_variant_name(
            plan=plan,
            executable_plan=executable_plan,
            candidate=candidate,
        )
        transition_edge_variant_disabled_active = self._bool(safety.get("transition_edge_variant_disabled_active", False))
        transition_edge_variant_sampling_selected: bool | None = None
        transition_edge_variant_sampling_fraction: float | None = None
        transition_edge_variant_sampling_ratio = 0.0
        metrics_grade = str(metrics.get("grade") or "F").upper()
        metrics_recommendation = str(metrics.get("recommendation") or "do-not-deploy")
        risk_state = str(metrics.get("risk_state") or "CLOSED")
        operating_lock = dict(metrics.get("operating_lock") or {})
        deployment_go_no_go = str(candidate.get("deployment_go_no_go") or "NO_GO")
        deployment_code = str(candidate.get("deployment_code") or "no_go_runtime_candidate_missing")
        deployment_message = str(candidate.get("deployment_message") or "NO_GO: runtime candidate is unavailable.")
        block_reason = str(candidate.get("block_reason") or "")
        block_reason_message = str(candidate.get("block_reason_message") or deployment_message)
        risk_reason = str(metrics.get("risk_reason") or candidate.get("risk_reason") or "normal")
        session_guidance = dict(candidate.get("session_guidance") or {})
        setup_score = self._safe_float(executable_plan.get("setup_score", 0.0))
        recommended_risk_r = self._safe_float(executable_plan.get("recommended_risk_r", 0.0))
        setup_grade = str(executable_plan.get("setup_grade") or "").upper()
        session_name = self._session_name(candidate, operating_lock)
        if session_name:
            safety["session_name"] = session_name
        requested_mode_exceeds_cap = _MODE_RANK[requested_mode] > _MODE_RANK[rollout_policy.max_execution_mode]
        override_applied = False
        override_block_applied = False
        override_reason = ""
        override_source = ""
        outcome_approval_penalty = self._outcome_approval_penalty(
            executable_plan=executable_plan,
            candidate_row=candidate_row,
            safety_state=safety,
            outcome_inputs=outcome_inputs,
        )

        thesis_rejected_reason = str(candidate.get("thesis_rejected_reason") or "")
        paper_lineage_candidate = (
            paper_lineage_override
            and requested_mode == ExecutionMode.PAPER
            and family in self._PAPER_LINEAGE_OVERRIDE_FAMILIES
            and setup_grade == "A"
        )
        override_block_candidate = block_reason in self._PAPER_LINEAGE_OVERRIDE_BLOCKS or thesis_rejected_reason == "duplicate_active_thesis"
        if paper_lineage_candidate and (not block_reason or override_block_candidate):
            override_applied = True
            override_source = "paper_lineage_override"
            override_block_applied = override_block_candidate
            if not override_block_candidate:
                override_reason = "paper lineage override allowed eligible A-grade PAPER sampling."
            elif block_reason == "thesis_active_cap_reached":
                override_reason = "paper lineage override bypassed thesis active-cap block for eligible A-grade PAPER sampling."
            else:
                override_reason = "paper lineage override bypassed thesis duplicate block for eligible A-grade PAPER sampling."
        paper_lineage_sampling_mode = override_applied and requested_mode == ExecutionMode.PAPER
        lineage_override_extra_reasons: list[dict[str, Any]] = []

        effective_block_reason = "" if override_block_applied else block_reason
        effective_block_reason_message = "" if override_block_applied else block_reason_message

        def validation_block_detail() -> dict[str, Any]:
            reason_codes = [
                str(item or "")
                for item in list(metrics.get("reason_codes") or metrics.get("reasons") or [])
                if str(item or "").strip()
            ]
            min_sample = self._safe_int(getattr(self.settings, "min_zone_sample_for_full_confidence", 30), default=30)
            sample_size = max(
                self._safe_int(metrics.get("sample_size")),
                self._safe_int(metrics.get("trade_count")),
                self._safe_int(metrics.get("closed_trades")),
            )
            win_rate = self._safe_float(metrics.get("win_rate"))
            expectancy_r = self._safe_float(metrics.get("expectancy_r"), default=self._safe_float(metrics.get("ev"), default=self._safe_float(metrics.get("ev_r"))))
            total_score = self._safe_float(metrics.get("total_score"))

            root_causes: list[dict[str, Any]] = []
            seen_root_codes: set[str] = set()

            def add_root_cause(code: str, message: str, evidence: dict[str, Any] | None = None) -> None:
                if code in seen_root_codes:
                    return
                seen_root_codes.add(code)
                item: dict[str, Any] = {"code": code, "message": message}
                if evidence:
                    item["evidence"] = evidence
                root_causes.append(item)

            if sample_size <= 0:
                add_root_cause(
                    "validation_sample_missing",
                    "No closed validation sample is available for this symbol/contract.",
                    {"sample_size": sample_size, "required_sample": min_sample},
                )
            elif sample_size < max(1, min_sample):
                add_root_cause(
                    "validation_sample_below_confidence_floor",
                    "Validation sample is below the configured confidence floor.",
                    {"sample_size": sample_size, "required_sample": min_sample},
                )
            if expectancy_r <= 0.0:
                add_root_cause(
                    "validation_expectancy_non_positive",
                    "Validation expectancy is not positive after costs.",
                    {"expectancy_r": expectancy_r},
                )
            if win_rate <= 0.0:
                add_root_cause(
                    "validation_win_rate_missing_or_zero",
                    "Validation win rate is missing or zero.",
                    {"win_rate": win_rate},
                )
            if metrics_grade == "F" or total_score < 45.0:
                add_root_cause(
                    "validation_score_below_deploy_floor",
                    "Validation score is below the do-not-deploy floor.",
                    {"grade": metrics_grade, "total_score": total_score, "deploy_floor": 45.0},
                )
            if risk_state != "OPEN":
                add_root_cause(
                    "risk_gate_not_open",
                    "Runtime risk gate is not open.",
                    {"risk_state": risk_state, "risk_reason": risk_reason},
                )
            if deployment_go_no_go != "GO":
                add_root_cause(
                    "runtime_deployment_gate_not_go",
                    "Runtime deployment gate is not GO.",
                    {"deployment_go_no_go": deployment_go_no_go, "deployment_code": deployment_code},
                )
            if block_reason:
                add_root_cause(
                    "runtime_candidate_blocked",
                    "Runtime candidate has a blocking reason.",
                    {"block_reason": block_reason},
                )
            if not root_causes:
                add_root_cause(
                    "validation_recommendation_do_not_deploy",
                    "Validation recommendation is do-not-deploy.",
                    {"recommendation": metrics_recommendation},
                )

            primary_cause = str(root_causes[0].get("code") or "validation_do_not_deploy")
            detail = {
                "recommendation": metrics_recommendation,
                "grade": metrics_grade,
                "risk_state": risk_state,
                "risk_reason": risk_reason,
                "deployment_code": deployment_code,
                "deployment_message": deployment_message,
                "candidate_block_reason": block_reason,
                "candidate_block_reason_message": block_reason_message if block_reason else "",
                "reason_codes": reason_codes[:8],
                "primary_cause": primary_cause,
                "root_causes": root_causes[:8],
            }
            numeric_fields = (
                "win_rate",
                "expectancy_r",
                "ev",
                "ev_r",
                "sample_size",
                "trade_count",
                "closed_trades",
                "total_score",
                "p1r",
                "p2r",
                "p3r",
                "max_drawdown",
                "max_drawdown_pct",
                "profit_factor",
            )
            metrics_numeric = {
                key: metrics.get(key)
                for key in numeric_fields
                if metrics.get(key) not in {None, ""}
            }
            if metrics_numeric:
                detail["metrics"] = metrics_numeric
            return detail

        def result(state: ApprovalState, reason_code: str, reason: str, extra_reasons: list[dict[str, Any]] | None = None) -> dict[str, Any]:
            final_state = state
            final_reason_code = reason_code
            final_reason = reason
            applied_penalty = dict(outcome_approval_penalty or {})
            if (
                state == ApprovalState.APPROVED_AUTO
                and not paper_lineage_sampling_mode
                and applied_penalty
                and self._bool(applied_penalty.get("available"))
                and str(applied_penalty.get("penalty_tier") or "") == "downgrade_to_manual"
            ):
                final_state = ApprovalState.APPROVED_MANUAL
                final_reason_code = "outcome_penalty_manual_review"
                final_reason = str(applied_penalty.get("summary") or reason)

            playbook = self._playbook_contract(final_state, reason_code=final_reason_code, reason=final_reason)
            primary_submit_blocking = final_state != ApprovalState.APPROVED_AUTO
            approval_reasons = [
                {
                    "code": reason_code,
                    "message": reason,
                    "blocking": final_state == ApprovalState.BLOCKED,
                    "submit_blocking": primary_submit_blocking,
                    "blocking_scope": "submit" if primary_submit_blocking else "none",
                }
            ]
            for item in extra_reasons or []:
                item_submit_blocking = self._bool(item.get("submit_blocking"))
                approval_reasons.append(
                    {
                        "code": str(item.get("code") or ""),
                        "message": str(item.get("message") or ""),
                        "blocking": self._bool(item.get("blocking")),
                        "submit_blocking": item_submit_blocking,
                        "blocking_scope": str(item.get("blocking_scope") or ("submit" if item_submit_blocking else "none")),
                    }
                )
            if applied_penalty and self._bool(applied_penalty.get("available")):
                for code in list(applied_penalty.get("reason_codes") or []):
                    approval_reasons.append(
                        self._outcome_penalty_reason(
                            code=str(code),
                            message=str(applied_penalty.get("summary") or "outcome-aware approval penalty applied"),
                        )
                    )
            return {
                "plan_id": plan.plan_id,
                "symbol": plan.symbol,
                "approval_state": final_state.value,
                "allowed_execution_mode": allowed_execution_mode.value,
                "strategy_mode": executable_plan.get("strategy_mode", getattr(self.settings.strategy_mode, "value", "A_ONLY")),
                "execution_mode": requested_mode.value,
                "deployment_go_no_go": deployment_go_no_go,
                "deployment_code": deployment_code,
                "deployment_message": deployment_message,
                "playbook_go_no_go": playbook["playbook_go_no_go"],
                "playbook_code": playbook["playbook_code"],
                "playbook_action": playbook["playbook_action"],
                "playbook_message": playbook["playbook_message"],
                "approval_reasons": approval_reasons,
                "approved_at": now,
                "expires_at": self._utc(plan.valid_until),
                "validation_grade": metrics_grade,
                "validation_recommendation": metrics_recommendation,
                "validation_block_detail": validation_block_detail() if final_reason_code == "validation_do_not_deploy" else None,
                "risk_state": risk_state,
                "risk_reason": risk_reason,
                "operating_lock": operating_lock,
                "session_guidance": session_guidance,
                "block_reason": effective_block_reason,
                "block_reason_message": effective_block_reason_message,
                "paper_lineage_override_applied": override_applied,
                "paper_lineage_override_reason": override_reason,
                "paper_lineage_override_source": override_source,
                "transition_edge_variant_applied": transition_edge_variant_applied,
                "transition_edge_variant_variant": transition_edge_variant_variant or None,
                "transition_edge_variant_disabled_active": transition_edge_variant_disabled_active,
                "transition_edge_variant_partial_activation_ratio": round(float(transition_edge_variant_sampling_ratio), 4),
                "transition_edge_variant_sampling_selected": transition_edge_variant_sampling_selected,
                "transition_edge_variant_sampling_fraction": (
                    round(float(transition_edge_variant_sampling_fraction), 6)
                    if transition_edge_variant_sampling_fraction is not None
                    else None
                ),
                "top_candidate": bool(candidate),
                "auto_trading_enabled": self._bool(self.settings.auto_trading_enabled),
                "rollout_policy": rollout_policy.to_dict(),
                "safety_state": safety,
                "live_cluster_guard": cluster_guard or None,
                "micro_live_symbol_priority_guard": symbol_priority_guard or None,
                "outcome_approval_penalty": applied_penalty or None,
            }

        if plan.state not in {PlanState.PLANNED.value, PlanState.ARMED.value}:
            return result(
                ApprovalState.BLOCKED,
                "stale_plan_state",
                f"Plan state {plan.state} is not eligible for a new entry.",
            )
        if self._utc(plan.valid_until) <= now:
            return result(ApprovalState.BLOCKED, "stale_plan_expired", "Plan validity already expired.")
        if self._bool(self.settings.auto_trading_close_only):
            return result(ApprovalState.BLOCKED, "close_only_mode", "Close-only mode is active; no new entries are allowed.")
        if not self._bool(safety.get("new_entry_allowed", True)):
            return result(
                ApprovalState.BLOCKED,
                str(safety.get("blocking_reason_code") or "safety_lock_active"),
                str(safety.get("blocking_reason_message") or "A safety lock blocks new entries."),
            )
        if not candidate:
            return result(ApprovalState.BLOCKED, "no_runtime_candidate", "No runtime-assessed candidate exists for this plan.")
        if deployment_go_no_go == "NO_GO":
            return result(ApprovalState.BLOCKED, deployment_code or "runtime_no_go", deployment_message)
        if self._bool(operating_lock.get("active")) or risk_state == "CLOSED":
            return result(ApprovalState.BLOCKED, "runtime_gate_closed", deployment_message or "Runtime gate is closed.")
        if not override_applied and (
            candidate.get("thesis_rejected_reason") == "duplicate_active_thesis" or block_reason == "thesis_duplicate_blocked"
        ):
            return result(
                ApprovalState.BLOCKED,
                "thesis_duplicate_blocked",
                block_reason_message or "An active candidate with the same thesis already exists.",
            )
        if effective_block_reason:
            effective_message = effective_block_reason_message or "Plan is blocked by runtime portfolio gate."
            return result(
                ApprovalState.BLOCKED,
                effective_block_reason,
                effective_message,
            )
        if transition_edge_variant_applied and transition_edge_variant_disabled_active:
            matching_variant_locks = list(safety.get("transition_edge_variant_matching_locks") or [])
            lock_message = "Transition edge variant is temporarily disabled by safety lock."
            if matching_variant_locks:
                lock_message = str(matching_variant_locks[0].get("reason_message") or lock_message)
            return result(
                ApprovalState.APPROVED_SHADOW,
                SafetyLockService.TRANSITION_EDGE_VARIANT_DISABLED_REASON,
                lock_message,
            )
        if symbol and self.allowed_symbols() and symbol not in self.allowed_symbols():
            if not paper_lineage_sampling_mode:
                return result(
                    ApprovalState.BLOCKED,
                    "symbol_not_live_enabled",
                    f"{symbol} is not in the current auto-trading allowlist.",
                )
            lineage_override_extra_reasons.append(
                {
                    "code": "paper_lineage_override_bypassed_symbol_allowlist",
                    "message": f"PAPER lineage sampling bypassed the auto-trading symbol allowlist for {symbol}.",
                    "blocking": False,
                }
            )
        if family and self.allowed_families() and family not in self.allowed_families():
            if not paper_lineage_sampling_mode:
                return result(
                    ApprovalState.BLOCKED,
                    "family_not_live_enabled",
                    f"{family} is not in the current auto-trading family allowlist.",
                )
            lineage_override_extra_reasons.append(
                {
                    "code": "paper_lineage_override_bypassed_family_allowlist",
                    "message": f"PAPER lineage sampling bypassed the auto-trading family allowlist for {family}.",
                    "blocking": False,
                }
            )
        if executable_plan.get("strategy_mode") == "RESEARCH":
            return result(
                ApprovalState.APPROVED_SHADOW,
                "mode_policy_research_only",
                "Research mode is shadow-only by policy.",
            )
        if requested_mode == ExecutionMode.LIVE and strict_requested_mode:
            return result(
                ApprovalState.BLOCKED,
                "live_mode_not_enabled",
                "Full LIVE mode is not enabled yet; MICRO_LIVE is the highest supported live path.",
            )
        if strict_requested_mode and requested_mode_exceeds_cap:
            return result(
                ApprovalState.BLOCKED,
                "rollout_mode_cap_exceeded",
                f"Requested execution mode {requested_mode.value} exceeds the family rollout cap {rollout_policy.max_execution_mode.value}.",
            )
        if rollout_policy.allowed_sessions and session_name not in set(rollout_policy.allowed_sessions):
            return result(
                ApprovalState.BLOCKED,
                "rollout_session_not_allowed",
                f"Current session {session_name} is outside the allowed rollout sessions for {family}.",
            )
        if self.settings.auto_trading_require_validation_go and metrics_recommendation == "do-not-deploy":
            if not paper_lineage_sampling_mode:
                return result(
                    ApprovalState.BLOCKED,
                    "validation_do_not_deploy",
                    "Validation recommendation is do-not-deploy.",
                )
            lineage_override_extra_reasons.append(
                {
                    "code": "paper_lineage_override_bypassed_validation_do_not_deploy",
                    "message": "PAPER lineage sampling bypassed the validation do-not-deploy gate while edge proof remains in sample-building mode.",
                    "blocking": False,
                }
            )
        if requested_mode in {ExecutionMode.LIVE, ExecutionMode.MICRO_LIVE} and not rollout_policy.live_enabled:
            if requested_mode_exceeds_cap:
                return result(
                    ApprovalState.BLOCKED,
                    "rollout_mode_cap_exceeded",
                    f"Requested execution mode {requested_mode.value} exceeds the family rollout cap {rollout_policy.max_execution_mode.value}.",
                )
            return result(
                ApprovalState.BLOCKED,
                "family_live_rollout_disabled",
                f"{family} is not enabled for live rollout.",
            )
        if requested_mode == ExecutionMode.MICRO_LIVE:
            strategy_mode = str(executable_plan.get("strategy_mode") or "")
            if strategy_mode != "A_ONLY":
                return result(
                    ApprovalState.BLOCKED,
                    "micro_live_requires_a_only",
                    "MICRO_LIVE is limited to A_ONLY strategy mode.",
                )
            micro_live_symbols = self.micro_live_allowed_symbols()
            if micro_live_symbols and symbol not in micro_live_symbols:
                return result(
                    ApprovalState.BLOCKED,
                    "micro_live_symbol_not_allowed",
                    f"{symbol} is outside the MICRO_LIVE symbol allowlist.",
                )
            micro_live_families = self.micro_live_allowed_families()
            if micro_live_families and family not in micro_live_families:
                return result(
                    ApprovalState.BLOCKED,
                    "micro_live_family_not_allowed",
                    f"{family} is outside the MICRO_LIVE family allowlist.",
                )
            micro_live_sessions = self.micro_live_allowed_sessions()
            if micro_live_sessions and session_name not in micro_live_sessions:
                return result(
                    ApprovalState.BLOCKED,
                    "micro_live_session_not_allowed",
                    f"Current session {session_name} is outside the MICRO_LIVE session allowlist.",
                )
            direction_contract = self.micro_live_direction_contract()
            allowed_directions = set(direction_contract.get(symbol) or set())
            current_direction = str(executable_plan.get("direction") or "").strip().upper()
            if allowed_directions and current_direction and current_direction not in allowed_directions:
                return result(
                    ApprovalState.BLOCKED,
                    "micro_live_direction_not_allowed",
                    f"{symbol} {current_direction} is outside the current MICRO_LIVE direction contract.",
                )
            blocked_hour_contract = self.micro_live_session_direction_blocked_hours()
            blocked_hours = set(blocked_hour_contract.get((symbol, session_name, current_direction)) or set())
            current_hour_utc = int(self._utc(now).hour)
            if blocked_hours and current_hour_utc in blocked_hours:
                return result(
                    ApprovalState.BLOCKED,
                    "micro_live_session_direction_hour_not_allowed",
                    (
                        f"{symbol} {session_name} {current_direction} is blocked for MICRO_LIVE at "
                        f"{current_hour_utc:02d}:00 UTC by the current session-direction hour contract."
                    ),
                )
            entry_model = str(executable_plan.get("entry_model") or plan.entry_model or "unknown").strip().upper() or "UNKNOWN"
            blocked_strategy_hour_contract = self.micro_live_symbol_family_entry_direction_blocked_hours()
            blocked_strategy_hours = set(
                blocked_strategy_hour_contract.get((symbol, family, entry_model, current_direction)) or set()
            )
            if blocked_strategy_hours and current_hour_utc in blocked_strategy_hours:
                return result(
                    ApprovalState.BLOCKED,
                    "micro_live_strategy_hour_not_allowed",
                    (
                        f"{symbol} {family} {entry_model} {current_direction} is blocked for MICRO_LIVE at "
                        f"{current_hour_utc:02d}:00 UTC by the current strategy-hour contract."
                    ),
                )
            current_utc = self._utc(now)
            event_blackouts = self.micro_live_event_blackouts()
            matching_blackout = next(
                (
                    blackout_row
                    for blackout_row in event_blackouts
                    if self._matches_event_blackout(
                        current_utc,
                        symbol=symbol,
                        family=family,
                        entry_model=entry_model,
                        direction=current_direction,
                        session_name=session_name,
                        blackout_row=blackout_row,
                    )
                ),
                None,
            )
            if matching_blackout:
                label = str(matching_blackout.get("label") or "major_event_blackout")
                start_utc = matching_blackout.get("start_utc")
                end_utc = matching_blackout.get("end_utc")
                start_text = start_utc.isoformat().replace("+00:00", "Z") if isinstance(start_utc, datetime) else "unknown"
                end_text = end_utc.isoformat().replace("+00:00", "Z") if isinstance(end_utc, datetime) else "unknown"
                return result(
                    ApprovalState.BLOCKED,
                    "micro_live_event_blackout_active",
                    (
                        f"{symbol} {family} {entry_model} is blocked for MICRO_LIVE during event blackout "
                        f"{label} ({start_text} -> {end_text})."
                    ),
                )
            strategy_time_contract = self.micro_live_strategy_time_contract()
            if any(
                self._matches_strategy_time_bucket(
                    current_utc,
                    symbol=symbol,
                    family=family,
                    entry_model=entry_model,
                    direction=current_direction,
                    contract_row=contract_row,
                )
                for contract_row in strategy_time_contract
            ):
                return result(
                    ApprovalState.BLOCKED,
                    "micro_live_strategy_time_bucket_not_allowed",
                    (
                        f"{symbol} {family} {entry_model} {current_direction} is blocked for MICRO_LIVE at "
                        f"weekday={int(current_utc.weekday())} {int(current_utc.hour):02d}:{int(current_utc.minute):02d} UTC "
                        "by the current strategy time-bucket contract."
                    ),
                )
            blocked_plan_ids = self.micro_live_plan_blocklist()
            if blocked_plan_ids and str(plan.plan_id or "").strip() in blocked_plan_ids:
                return result(
                    ApprovalState.BLOCKED,
                    "micro_live_plan_id_blocklisted",
                    (
                        f"plan_id {str(plan.plan_id or '').strip()} is blocked by the current MICRO_LIVE "
                        "historical plan blocklist contract."
                    ),
                )
            max_concurrent_positions = self._safe_int(
                self.settings.auto_trading_micro_live_max_concurrent_positions,
                default=2,
            )
            if current_exposure_count >= max_concurrent_positions:
                return result(
                    ApprovalState.BLOCKED,
                    "micro_live_position_cap_reached",
                    f"Open exposure count {current_exposure_count} reached the MICRO_LIVE concurrent position cap.",
                )
            daily_entry_cap = self._safe_int(self.settings.auto_trading_micro_live_max_daily_new_entries, default=2)
            if daily_entry_cap > 0 and daily_new_entry_count >= daily_entry_cap:
                return result(
                    ApprovalState.BLOCKED,
                    "micro_live_daily_entry_cap_reached",
                    f"Today's new entry count {daily_new_entry_count} reached the MICRO_LIVE daily cap.",
                )
            if self._bool(symbol_priority_guard.get("blocked")):
                preferred_symbol = str(symbol_priority_guard.get("preferred_symbol") or "")
                preferred_created_at = str(symbol_priority_guard.get("preferred_created_at") or "")
                preferred_suffix = f" (latest submit_ready at {preferred_created_at})" if preferred_created_at else ""
                return result(
                    ApprovalState.BLOCKED,
                    "micro_live_higher_priority_symbol_available",
                    f"{symbol} is currently fallback-only for MICRO_LIVE; prefer {preferred_symbol}{preferred_suffix}.",
                )
        if requested_mode in {ExecutionMode.LIVE, ExecutionMode.MICRO_LIVE}:
            entry_model = str(executable_plan.get("entry_model") or plan.entry_model or "unknown").strip().upper() or "UNKNOWN"
            allowed_entry_models = self.micro_live_allowed_entry_models()
            if allowed_entry_models and entry_model not in allowed_entry_models:
                reason_code = self._entry_model_rejection_code(allowed_entry_models)
                return result(
                    ApprovalState.BLOCKED,
                    reason_code,
                    (
                        f"The current live rollout contract is limit-only; {entry_model} entries remain paper/research only."
                        if reason_code == "live_limit_only_entry_required"
                        else (
                            f"{entry_model} is outside the current live rollout entry-model contract "
                            f"({','.join(sorted(allowed_entry_models))})."
                        )
                    ),
                )
        if requested_mode in {ExecutionMode.LIVE, ExecutionMode.MICRO_LIVE} and cluster_guard:
            window_cap = max(0, self._safe_int(cluster_guard.get("max_same_family_entries_per_window", 0)))
            window_minutes = max(0, self._safe_int(cluster_guard.get("cluster_window_minutes", 0)))
            window_count = max(0, self._safe_int(cluster_guard.get("recent_family_window_entry_count", 0)))
            if window_cap > 0 and window_count >= window_cap:
                symbols = self._symbol_list(cluster_guard.get("recent_family_window_symbols"))
                symbol_suffix = f" ({symbols})" if symbols else ""
                return result(
                    ApprovalState.BLOCKED,
                    "live_family_cluster_window_cap_reached",
                    f"{family} already has {window_count} recent family entries inside the last {window_minutes}m cluster window{symbol_suffix}.",
                )
            direction_cap = max(0, self._safe_int(cluster_guard.get("max_same_family_direction_exposures", 0)))
            direction_count = max(0, self._safe_int(cluster_guard.get("recent_family_direction_exposure_count", 0)))
            direction = str(cluster_guard.get("direction") or getattr(plan, "direction", "") or "").upper()
            if direction_cap > 0 and direction_count >= direction_cap:
                symbols = self._symbol_list(cluster_guard.get("recent_family_direction_exposure_symbols"))
                symbol_suffix = f" ({symbols})" if symbols else ""
                return result(
                    ApprovalState.BLOCKED,
                    "live_family_direction_exposure_cap_reached",
                    f"{family} already has {direction_count} active {direction or 'SAME-DIRECTION'} exposure(s) in {direction or 'the same direction'}{symbol_suffix}.",
                )
            loss_trigger = max(0, self._safe_int(cluster_guard.get("loss_cooldown_trigger_count", 0)))
            loss_minutes = max(0, self._safe_int(cluster_guard.get("loss_cooldown_minutes", 0)))
            loss_count = max(0, self._safe_int(cluster_guard.get("recent_family_loss_count", 0)))
            if loss_trigger > 0 and loss_count >= loss_trigger:
                symbols = self._symbol_list(cluster_guard.get("recent_family_loss_symbols"))
                symbol_suffix = f" ({symbols})" if symbols else ""
                return result(
                    ApprovalState.BLOCKED,
                    "live_family_loss_cooldown_active",
                    f"{family} logged {loss_count} recent family losses inside the last {loss_minutes}m cooldown window{symbol_suffix}.",
                )
        rollout_max_risk = self._safe_float(rollout_policy.max_risk_r)
        rollout_min_quality = self._safe_float(rollout_policy.min_quality_score)
        if recommended_risk_r > rollout_max_risk + 1e-9 and rollout_max_risk > 0.0:
            return result(
                ApprovalState.APPROVED_MANUAL,
                "rollout_risk_cap_exceeded",
                f"Recommended risk {recommended_risk_r:.2f}R exceeds the family rollout cap {rollout_max_risk:.2f}R.",
            )
        if setup_score < rollout_min_quality:
            return result(
                ApprovalState.APPROVED_MANUAL,
                "rollout_min_quality_not_met",
                f"Setup score {setup_score:.1f} is below the family rollout minimum {rollout_min_quality:.1f}.",
            )
        if self.settings.auto_trading_require_validation_go:
            if allowed_execution_mode == ExecutionMode.LIVE and metrics_grade != "A":
                return result(
                    ApprovalState.APPROVED_MANUAL,
                    "validation_live_requires_grade_a",
                    "LIVE mode requires validation grade A.",
                )
            if allowed_execution_mode == ExecutionMode.MICRO_LIVE and metrics_grade not in {"A", "B"}:
                return result(
                    ApprovalState.APPROVED_MANUAL,
                    "validation_micro_live_requires_grade_ab",
                    "MICRO_LIVE requires validation grade A or B.",
                )
        if deployment_go_no_go == "MANUAL_REVIEW" or risk_state == "THROTTLED":
            return result(
                ApprovalState.APPROVED_MANUAL,
                "manual_review_required",
                deployment_message or "Manual review is required before submit.",
            )
        if not self._bool(self.settings.auto_trading_enabled):
            return result(
                ApprovalState.APPROVED_SHADOW,
                "auto_trading_disabled",
                "Auto trading is globally disabled, so this plan is shadow-only.",
            )
        if allowed_execution_mode == ExecutionMode.SHADOW:
            return result(
                ApprovalState.APPROVED_SHADOW,
                "rollout_shadow_only",
                "Current rollout stage is shadow-only for this family.",
            )
        if family == "session_impulse_retest" and requested_mode in {ExecutionMode.MICRO_LIVE, ExecutionMode.LIVE}:
            if not self._bool(getattr(self.settings, "session_impulse_retest_enabled", False)):
                return result(
                    ApprovalState.APPROVED_SHADOW,
                    "session_impulse_retest_family_disabled",
                    "session_impulse_retest is currently disabled.",
                )
            if self._bool(getattr(self.settings, "session_impulse_retest_shadow_only", False)):
                return result(
                    ApprovalState.APPROVED_SHADOW,
                    "session_impulse_retest_shadow_only",
                    "session_impulse_retest is currently configured as shadow-only.",
                )
            rollout_readiness = dict(safety.get("session_impulse_retest_rollout_readiness") or {})
            blockers = [str(item or "") for item in list(rollout_readiness.get("blockers") or []) if str(item or "").strip()]
            if rollout_readiness and blockers:
                blocker_text = ", ".join(blockers) if blockers else "not_ready"
                return result(
                    ApprovalState.APPROVED_SHADOW,
                    "session_impulse_retest_rollout_not_ready",
                    f"session_impulse_retest rollout readiness is not live-ready ({blocker_text}).",
                )
            (
                session_impulse_sampling_selected,
                _session_impulse_sampling_fraction,
                session_impulse_sampling_ratio,
            ) = self._session_impulse_retest_sampling_decision(
                plan=plan,
                executable_plan=executable_plan,
            )
            if not session_impulse_sampling_selected:
                return result(
                    ApprovalState.APPROVED_SHADOW,
                    "session_impulse_retest_partial_holdout",
                    (
                        "session_impulse_retest remains in partial activation holdout for this sample."
                        if session_impulse_sampling_ratio > 0.0
                        else "session_impulse_retest is configured for holdout-only execution."
                    ),
                )
        if transition_edge_variant_applied and requested_mode in {ExecutionMode.MICRO_LIVE, ExecutionMode.LIVE}:
            (
                transition_edge_variant_sampling_selected,
                transition_edge_variant_sampling_fraction,
                transition_edge_variant_sampling_ratio,
            ) = self._transition_edge_variant_sampling_decision(
                plan=plan,
                executable_plan=executable_plan,
            )
            if not transition_edge_variant_sampling_selected:
                return result(
                    ApprovalState.APPROVED_SHADOW,
                    "transition_edge_variant_partial_holdout",
                    (
                        "Transition rescue lane remains in partial activation holdout for this thesis-safe sample."
                        if transition_edge_variant_sampling_ratio > 0.0
                        else "Transition rescue lane is configured for holdout-only execution."
                    ),
                )

        rollout_code, rollout_message = self._rollout_reason(allowed_execution_mode)
        extra_reasons: list[dict[str, Any]] = []
        if override_applied:
            extra_reasons.append(
                {
                    "code": "paper_lineage_override_applied",
                    "message": override_reason,
                    "blocking": False,
                }
            )
        extra_reasons.extend(lineage_override_extra_reasons)
        if requested_mode_exceeds_cap and not strict_requested_mode:
            extra_reasons.append(
                {
                    "code": "rollout_mode_capped",
                    "message": f"Requested/global mode was capped to {allowed_execution_mode.value} by family rollout policy.",
                    "blocking": False,
                }
            )
        if (
            paper_lineage_sampling_mode
            and outcome_approval_penalty
            and self._bool(outcome_approval_penalty.get("available"))
            and str(outcome_approval_penalty.get("penalty_tier") or "") == "downgrade_to_manual"
        ):
            extra_reasons.append(
                {
                    "code": "paper_lineage_override_retained_paper_auto_submit",
                    "message": "PAPER lineage sampling kept auto-submit eligibility despite live-entry outcome penalties.",
                    "blocking": False,
                }
            )
        return result(ApprovalState.APPROVED_AUTO, rollout_code, rollout_message, extra_reasons=extra_reasons)
