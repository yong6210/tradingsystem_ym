from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.config import Settings, get_settings
from app.db.models import Plan, ZoneOutcome
from app.db.repositories import OutcomeRepository, PlanRepository
from app.services.common import clamp
from app.services.feature_importance import FEATURE_KEYS
from app.services.plan_generator import PlanGenerator

FEATURE_CALIBRATION_SCHEMA_VERSION = "feature_calibration_v2"
ZONE_TYPES = ("LP", "OB", "FVG", "FLIP")


@dataclass(slots=True)
class MatchedTrade:
    plan_id: str
    zone_id: str
    zone_type: str
    regime: str
    entry_model: str
    realized_r: float
    decay_weight: float
    components: dict[str, float]
    entry_ts: datetime


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value in (None, "", "None"):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _safe_int(value: Any, default: int = 0) -> int:
    return int(_safe_float(value, float(default)))


def _safe_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value) if math.isfinite(float(value)) else bool(default)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off", "none", "null", ""}:
        return False
    return bool(default)


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        tmp_path.write_text(content, encoding="utf-8")
        tmp_path.replace(path)
    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass


class FeatureCalibrationService:
    def __init__(
        self,
        generator: PlanGenerator,
        settings: Settings | None = None,
        *,
        plan_repo: PlanRepository | None = None,
        outcome_repo: OutcomeRepository | None = None,
    ):
        self.generator = generator
        self.settings = settings or get_settings()
        self.plan_repo = plan_repo
        self.outcome_repo = outcome_repo

    def _snapshot_dir(self) -> Path:
        path = Path(self.settings.feature_calibration_snapshot_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _report_dir(self) -> Path:
        path = Path(self.settings.feature_calibration_report_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _latest_snapshot_path(snapshot_dir: Path, *, symbol: str, regime_label: str) -> Path:
        return snapshot_dir / f"{symbol}_{regime_label}_latest.json"

    @staticmethod
    def _timestamped_snapshot_path(snapshot_dir: Path, *, symbol: str, regime_label: str, now: datetime) -> Path:
        return snapshot_dir / f"{symbol}_{regime_label}_{now.strftime('%Y%m%dT%H%M%SZ')}.json"

    def _load_latest(self, *, symbol: str, regime_label: str) -> dict[str, Any] | None:
        path = self._latest_snapshot_path(self._snapshot_dir(), symbol=symbol, regime_label=regime_label)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    @staticmethod
    def _snapshot_generated_at(latest: dict[str, Any]) -> datetime:
        raw = str(latest.get("generated_at") or "").strip()
        if raw:
            try:
                return _utc(datetime.fromisoformat(raw.replace("Z", "+00:00")))
            except ValueError:
                pass
        return datetime.now(timezone.utc)

    @staticmethod
    def _normalize_with_floor(weights: dict[str, float], *, target_total: float, min_weight: float) -> dict[str, float]:
        keys = list(weights.keys())
        if not keys:
            return {}
        if target_total <= min_weight * len(keys):
            even = target_total / len(keys)
            return {key: round(even, 6) for key in keys}

        extras = {key: max(0.0, _safe_float(value) - min_weight) for key, value in weights.items()}
        extras_total = sum(extras.values())
        if extras_total <= 1e-12:
            even = target_total / len(keys)
            return {key: round(even, 6) for key in keys}

        remaining = target_total - min_weight * len(keys)
        normalized = {
            key: min_weight + (extras[key] / extras_total) * remaining
            for key in keys
        }
        return {key: round(float(value), 6) for key, value in normalized.items()}

    def _scores_to_target_weights(
        self,
        *,
        base_weights: dict[str, float],
        ewma_scores: dict[str, float],
    ) -> dict[str, float]:
        if not base_weights:
            return {}

        centered = {}
        score_values = [_safe_float(value) for value in ewma_scores.values()]
        avg_score = sum(score_values) / max(1, len(score_values))
        for key in FEATURE_KEYS:
            centered[key] = _safe_float(ewma_scores.get(key, 0.0)) - avg_score

        max_abs = max((abs(value) for value in centered.values()), default=0.0)
        if max_abs <= 1e-12:
            return {key: round(float(value), 6) for key, value in base_weights.items()}

        adjusted = {}
        max_delta = _safe_float(self.settings.feature_calibration_max_delta, 0.04)
        min_weight = _safe_float(self.settings.feature_calibration_min_weight, 0.05)
        for key in FEATURE_KEYS:
            delta = centered[key] / max_abs * max_delta
            adjusted[key] = max(
                min_weight,
                _safe_float(base_weights[key]) * (1.0 + delta),
            )

        return self._normalize_with_floor(
            adjusted,
            target_total=sum(_safe_float(value) for value in base_weights.values()),
            min_weight=min_weight,
        )

    def _limit_delta(
        self,
        *,
        previous_weights: dict[str, float],
        target_weights: dict[str, float],
    ) -> dict[str, float]:
        bounded = {}
        max_delta = _safe_float(self.settings.feature_calibration_max_delta, 0.04)
        for key in FEATURE_KEYS:
            prev = _safe_float(previous_weights.get(key, 0.0))
            target = _safe_float(target_weights.get(key, prev), prev)
            bounded[key] = prev + clamp(target - prev, -max_delta, max_delta)
        return self._normalize_with_floor(
            bounded,
            target_total=sum(_safe_float(value) for value in previous_weights.values()) or 1.0,
            min_weight=_safe_float(self.settings.feature_calibration_min_weight, 0.05),
        )

    @staticmethod
    def _default_zone_type_multipliers() -> dict[str, dict[str, float]]:
        return {
            zone_type: {
                "baseline_multiplier": 1.0,
                "active_multiplier": 1.0,
                "delta": 0.0,
                "signal": 0.0,
                "weighted_realized_r": 0.0,
                "matched_samples": 0,
            }
            for zone_type in ZONE_TYPES
        }

    @staticmethod
    def _round_map(values: dict[str, float]) -> dict[str, float]:
        return {key: round(float(values.get(key, 0.0)), 6) for key in FEATURE_KEYS}

    def _base_payload(
        self,
        *,
        symbol: str,
        regime_label: str,
        now: datetime,
        available: bool,
        reason: str | None,
        baseline_generated_plans: int,
        matched_samples: int,
        baseline_weights: dict[str, float],
        previous_weights: dict[str, float],
        current_scores: dict[str, float],
        ewma_scores: dict[str, float],
        recommended_weights: dict[str, float],
        feature_rows: dict[str, dict[str, float]],
        zone_type_multipliers: dict[str, dict[str, float]],
        applied_runtime: bool,
        snapshot_path: str | None = None,
        report_path: str | None = None,
    ) -> dict[str, Any]:
        baseline_weights = self._round_map(baseline_weights)
        previous_weights = self._round_map(previous_weights)
        current_scores = self._round_map(current_scores)
        ewma_scores = self._round_map(ewma_scores)
        recommended_weights = self._round_map(recommended_weights)

        weight_deltas = {
            key: round(recommended_weights[key] - baseline_weights[key], 6)
            for key in FEATURE_KEYS
        }
        by_regime = {
            regime_label: {
                "baseline_generated_plans": int(baseline_generated_plans),
                "matched_samples": int(matched_samples),
                "feature_weights_base": baseline_weights,
                "feature_weights_previous": previous_weights,
                "feature_weights_active": recommended_weights,
                "weight_deltas": weight_deltas,
                "current_scores": current_scores,
                "ewma_scores": ewma_scores,
                "feature_rows": feature_rows,
            }
        }

        return {
            "schema_version": FEATURE_CALIBRATION_SCHEMA_VERSION,
            "symbol": symbol,
            "available": available,
            "reason": reason,
            "regime_label": regime_label,
            "baseline_generated_plans": int(baseline_generated_plans),
            "matched_samples": int(matched_samples),
            "alpha": round(clamp(_safe_float(self.settings.feature_calibration_alpha, 0.35), 0.0, 1.0), 6),
            "baseline_weights": baseline_weights,
            "previous_weights": previous_weights,
            "current_scores": current_scores,
            "ewma_scores": ewma_scores,
            "recommended_weights": recommended_weights,
            "by_regime": by_regime,
            "zone_type_multipliers": zone_type_multipliers,
            "applied_runtime": applied_runtime,
            "snapshot_path": snapshot_path,
            "report_path": report_path,
            "generated_at": now.isoformat(),
        }

    def _normalize_snapshot(self, *, latest: dict[str, Any], regime_label: str) -> dict[str, Any]:
        base_weights = self.generator.feature_weights_for_regime(regime_label)
        baseline_weights = {
            key: _safe_float((latest.get("baseline_weights") or {}).get(key, base_weights[key]), base_weights[key])
            for key in FEATURE_KEYS
        }
        previous_weights = {
            key: _safe_float((latest.get("previous_weights") or {}).get(key, baseline_weights[key]), baseline_weights[key])
            for key in FEATURE_KEYS
        }
        recommended_weights = {
            key: _safe_float((latest.get("recommended_weights") or {}).get(key, previous_weights[key]), previous_weights[key])
            for key in FEATURE_KEYS
        }
        current_scores = {
            key: _safe_float((latest.get("current_scores") or {}).get(key, 0.0))
            for key in FEATURE_KEYS
        }
        ewma_scores = {
            key: _safe_float((latest.get("ewma_scores") or {}).get(key, current_scores[key]), current_scores[key])
            for key in FEATURE_KEYS
        }

        row = dict((latest.get("by_regime") or {}).get(regime_label, {}))
        feature_rows = dict(row.get("feature_rows") or {})
        if row:
            baseline_weights = {
                key: _safe_float((row.get("feature_weights_base") or {}).get(key, baseline_weights[key]), baseline_weights[key])
                for key in FEATURE_KEYS
            }
            previous_weights = {
                key: _safe_float(
                    (row.get("feature_weights_previous") or {}).get(key, previous_weights[key]),
                    previous_weights[key],
                )
                for key in FEATURE_KEYS
            }
            recommended_weights = {
                key: _safe_float(
                    (row.get("feature_weights_active") or {}).get(key, recommended_weights[key]),
                    recommended_weights[key],
                )
                for key in FEATURE_KEYS
            }
            current_scores = {
                key: _safe_float((row.get("current_scores") or {}).get(key, current_scores[key]), current_scores[key])
                for key in FEATURE_KEYS
            }
            ewma_scores = {
                key: _safe_float((row.get("ewma_scores") or {}).get(key, ewma_scores[key]), ewma_scores[key])
                for key in FEATURE_KEYS
            }

        zone_type_multipliers = self._default_zone_type_multipliers()
        raw_zone_type_multipliers = latest.get("zone_type_multipliers") or {}
        for zone_type in ZONE_TYPES:
            zone_row = dict(raw_zone_type_multipliers.get(zone_type, {}))
            zone_type_multipliers[zone_type] = {
                "baseline_multiplier": round(_safe_float(zone_row.get("baseline_multiplier", 1.0), 1.0), 6),
                "active_multiplier": round(_safe_float(zone_row.get("active_multiplier", 1.0), 1.0), 6),
                "delta": round(_safe_float(zone_row.get("delta", 0.0)), 6),
                "signal": round(_safe_float(zone_row.get("signal", 0.0)), 6),
                "weighted_realized_r": round(_safe_float(zone_row.get("weighted_realized_r", 0.0)), 6),
                "matched_samples": _safe_int(zone_row.get("matched_samples", 0)),
            }

        normalized = self._base_payload(
            symbol=str(latest.get("symbol", "")),
            regime_label=str(latest.get("regime_label", regime_label) or regime_label),
            now=self._snapshot_generated_at(latest),
            available=_safe_bool(latest.get("available")),
            reason=latest.get("reason"),
            baseline_generated_plans=_safe_int(latest.get("baseline_generated_plans", 0)),
            matched_samples=_safe_int(latest.get("matched_samples", row.get("matched_samples", 0) or 0)),
            baseline_weights=baseline_weights,
            previous_weights=previous_weights,
            current_scores=current_scores,
            ewma_scores=ewma_scores,
            recommended_weights=recommended_weights,
            feature_rows=feature_rows,
            zone_type_multipliers=zone_type_multipliers,
            applied_runtime=_safe_bool(latest.get("applied_runtime")),
            snapshot_path=latest.get("snapshot_path"),
            report_path=latest.get("report_path"),
        )
        normalized["schema_version"] = str(latest.get("schema_version", FEATURE_CALIBRATION_SCHEMA_VERSION))
        return normalized

    @staticmethod
    def _plan_model(plan: Plan) -> str:
        return str(getattr(plan.entry_model, "value", plan.entry_model)).upper()

    @staticmethod
    def _outcome_model(outcome: ZoneOutcome) -> str:
        return str(outcome.entry_model_used).upper()

    @staticmethod
    def _realized_r(outcome: ZoneOutcome) -> float:
        if outcome.hit_3r:
            return 3.0
        if outcome.hit_2r:
            return 2.0
        if outcome.hit_1r:
            return 1.0
        return -1.0

    def _decay_weight(self, *, ts: datetime, now: datetime) -> float:
        half_life_days = max(1e-6, _safe_float(self.settings.feature_calibration_half_life_days, 21.0))
        age_days = max(0.0, (now - _utc(ts)).total_seconds() / 86400.0)
        return float(0.5 ** (age_days / half_life_days))

    def _match_trades(self, *, symbol: str, regime_label: str, now: datetime) -> list[MatchedTrade]:
        if self.plan_repo is None or self.outcome_repo is None:
            return []

        plans = list(
            self.plan_repo.list_recent(
                symbol=symbol,
                timeframe="5m",
                days=_safe_int(self.settings.feature_calibration_lookback_days, 120),
            )
        )
        outcomes = list(self.outcome_repo.list_recent(symbol=symbol, days=_safe_int(self.settings.feature_calibration_lookback_days, 120)))
        by_zone: dict[str, list[ZoneOutcome]] = {}
        for outcome in outcomes:
            by_zone.setdefault(outcome.zone_id, []).append(outcome)
        for rows in by_zone.values():
            rows.sort(key=lambda item: _utc(item.entry_ts))

        out: list[MatchedTrade] = []
        ordered_plans = sorted(plans, key=lambda plan: (_utc(plan.valid_from), plan.plan_id))
        for plan in ordered_plans:
            validity = dict(plan.validity or {})
            if str(validity.get("regime", "range")).lower() != regime_label:
                continue

            components_raw = dict(validity.get("confluence_components") or {})
            if not components_raw:
                continue

            candidates = by_zone.get(plan.zone_id, [])
            if not candidates:
                continue

            window_start = _utc(plan.valid_from) - timedelta(minutes=5)
            window_end = max(_utc(plan.valid_until), _utc(plan.valid_from)) + timedelta(days=1)
            match_index = -1
            for index, outcome in enumerate(candidates):
                if self._outcome_model(outcome) != self._plan_model(plan):
                    continue
                entry_ts = _utc(outcome.entry_ts)
                if window_start <= entry_ts <= window_end:
                    match_index = index
                    break

            if match_index < 0:
                continue

            outcome = candidates.pop(match_index)
            zone_type = str(validity.get("zone_type", "")).upper()
            if zone_type not in ZONE_TYPES:
                zone_type = "OB"

            out.append(
                MatchedTrade(
                    plan_id=plan.plan_id,
                    zone_id=plan.zone_id,
                    zone_type=zone_type,
                    regime=regime_label,
                    entry_model=self._plan_model(plan),
                    realized_r=self._realized_r(outcome),
                    decay_weight=self._decay_weight(ts=outcome.entry_ts, now=now),
                    components={key: _safe_float(components_raw.get(key, 0.0)) for key in FEATURE_KEYS},
                    entry_ts=_utc(outcome.entry_ts),
                )
            )
        return out

    def _feature_rows(self, rows: list[MatchedTrade]) -> tuple[dict[str, dict[str, float]], dict[str, float]]:
        total_weight = sum(item.decay_weight for item in rows)
        if total_weight <= 1e-9:
            feature_rows = {
                key: {
                    "signal": 0.0,
                    "weighted_component": 0.0,
                    "weighted_realized_r": 0.0,
                    "target_multiplier": 1.0,
                }
                for key in FEATURE_KEYS
            }
            return feature_rows, {key: 0.0 for key in FEATURE_KEYS}

        feature_rows: dict[str, dict[str, float]] = {}
        current_scores: dict[str, float] = {}
        for key in FEATURE_KEYS:
            weighted_component = sum(item.decay_weight * (item.components.get(key, 0.0) / 100.0) for item in rows) / total_weight
            weighted_realized_r = sum(item.decay_weight * item.realized_r for item in rows) / total_weight
            signal = sum(
                item.decay_weight * ((item.components.get(key, 0.0) / 100.0) - 0.5) * item.realized_r
                for item in rows
            ) / total_weight
            current_scores[key] = float(signal)
            feature_rows[key] = {
                "signal": round(signal, 6),
                "weighted_component": round(weighted_component, 6),
                "weighted_realized_r": round(weighted_realized_r, 6),
                "target_multiplier": round(
                    1.0 + _safe_float(self.settings.feature_calibration_max_delta, 0.04) * math.tanh(float(signal)),
                    6,
                ),
            }
        return feature_rows, current_scores

    def _zone_type_rows(
        self,
        *,
        rows: list[MatchedTrade],
        previous_snapshot: dict[str, Any] | None,
    ) -> dict[str, dict[str, float]]:
        total_weight = sum(item.decay_weight for item in rows)
        baseline_r = (
            sum(item.decay_weight * item.realized_r for item in rows) / total_weight
            if total_weight > 1e-9
            else 0.0
        )
        previous_rows = dict((previous_snapshot or {}).get("zone_type_multipliers") or {})
        max_zone_delta = _safe_float(self.settings.feature_calibration_max_zone_delta, 0.14)
        out = self._default_zone_type_multipliers()

        for zone_type in ZONE_TYPES:
            zone_rows = [item for item in rows if item.zone_type == zone_type]
            previous_active = _safe_float(dict(previous_rows.get(zone_type, {})).get("active_multiplier", 1.0), 1.0)
            if len(zone_rows) < max(1, _safe_int(self.settings.feature_calibration_min_regime_matches, 4)):
                out[zone_type] = {
                    "baseline_multiplier": 1.0,
                    "active_multiplier": round(previous_active, 6),
                    "delta": round(previous_active - 1.0, 6),
                    "signal": 0.0,
                    "weighted_realized_r": 0.0,
                    "matched_samples": len(zone_rows),
                }
                continue

            zone_weight = sum(item.decay_weight for item in zone_rows)
            weighted_realized_r = (
                sum(item.decay_weight * item.realized_r for item in zone_rows) / zone_weight
                if zone_weight > 1e-9
                else 0.0
            )
            signal = weighted_realized_r - baseline_r
            target_multiplier = 1.0 + max_zone_delta * math.tanh(signal)
            active_multiplier = previous_active + clamp(target_multiplier - previous_active, -max_zone_delta, max_zone_delta)
            active_multiplier = clamp(active_multiplier, 1.0 - max_zone_delta, 1.0 + max_zone_delta)
            out[zone_type] = {
                "baseline_multiplier": 1.0,
                "active_multiplier": round(active_multiplier, 6),
                "delta": round(active_multiplier - 1.0, 6),
                "signal": round(signal, 6),
                "weighted_realized_r": round(weighted_realized_r, 6),
                "matched_samples": len(zone_rows),
            }
        return out

    def _write_snapshot(self, *, payload: dict[str, Any], symbol: str, regime_label: str, now: datetime) -> str:
        snapshot_dir = self._snapshot_dir()
        latest_path = self._latest_snapshot_path(snapshot_dir, symbol=symbol, regime_label=regime_label)
        timestamped_path = self._timestamped_snapshot_path(snapshot_dir, symbol=symbol, regime_label=regime_label, now=now)
        serialized = json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True)
        _atomic_write_text(latest_path, serialized)
        _atomic_write_text(timestamped_path, serialized)
        return str(timestamped_path)

    def runtime_payload(self, *, symbol: str, regime_label: str) -> dict[str, Any] | None:
        if not _safe_bool(self.settings.feature_calibration_enabled) or not _safe_bool(self.settings.feature_calibration_apply_runtime):
            return None
        latest = self._load_latest(symbol=symbol, regime_label=regime_label)
        if not latest or not _safe_bool(latest.get("available")):
            return None
        return self._normalize_snapshot(latest=latest, regime_label=regime_label)

    def runtime_overrides(self, *, symbol: str, regime_label: str) -> dict[str, float] | None:
        latest = self.runtime_payload(symbol=symbol, regime_label=regime_label)
        if not latest:
            return None
        row = dict((latest.get("by_regime") or {}).get(regime_label, {}))
        recommended = row.get("feature_weights_active") or latest.get("recommended_weights")
        if not isinstance(recommended, dict):
            return None
        return {key: _safe_float(recommended[key]) for key in FEATURE_KEYS if key in recommended}

    def _write_report(self, *, payload: dict[str, Any], now: datetime) -> str:
        out_dir = self._report_dir()
        symbol = str(payload["symbol"])
        regime_label = str(payload["regime_label"])
        path = out_dir / f"feature_calibration_{symbol}_{regime_label}_{now.strftime('%Y%m%dT%H%M%SZ')}.md"

        row = dict((payload.get("by_regime") or {}).get(regime_label, {}))
        deltas = dict(row.get("weight_deltas") or {})
        top_adjustments = sorted(deltas.items(), key=lambda item: abs(float(item[1])), reverse=True)

        lines = [
            "# Feature Calibration Report",
            "",
            f"- generated_at_utc: {payload['generated_at']}",
            f"- symbol: {symbol}",
            f"- regime_label: {regime_label}",
            f"- available: {payload['available']}",
            f"- reason: {payload['reason']}",
            f"- matched_samples: {payload['matched_samples']}",
            f"- baseline_generated_plans: {payload['baseline_generated_plans']}",
            f"- alpha: {payload['alpha']}",
            f"- applied_runtime: {payload['applied_runtime']}",
            "",
            "## Current Scores",
        ]
        for key, value in sorted(payload["current_scores"].items()):
            lines.append(f"- {key}: {float(value):.6f}")

        lines.extend(["", "## EWMA Scores"])
        for key, value in sorted(payload["ewma_scores"].items()):
            lines.append(f"- {key}: {float(value):.6f}")

        lines.extend(["", "## Weight Adjustments"])
        for key, delta in top_adjustments:
            base = float(payload["baseline_weights"].get(key, 0.0))
            prev = float(payload["previous_weights"].get(key, 0.0))
            active = float(payload["recommended_weights"].get(key, 0.0))
            lines.append(
                f"- {key}: base={base:.6f}, previous={prev:.6f}, active={active:.6f}, delta={float(delta):+.6f}"
            )

        lines.extend(["", "## Zone Type Multipliers"])
        for zone_type, zone_row in sorted((payload.get("zone_type_multipliers") or {}).items()):
            lines.append(
                f"- {zone_type}: active={float(zone_row.get('active_multiplier', 1.0)):.4f}, "
                f"delta={float(zone_row.get('delta', 0.0)):+.4f}, "
                f"signal={float(zone_row.get('signal', 0.0)):+.4f}, "
                f"samples={int(zone_row.get('matched_samples', 0))}"
            )

        lines.append("")
        _atomic_write_text(path, "\n".join(lines))
        return str(path)

    def generate(
        self,
        *,
        symbol: str,
        regime_label: str,
        feature_importance: dict[str, Any],
        write_report: bool = True,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        base_weights = self.generator.feature_weights_for_regime(regime_label)
        baseline = feature_importance.get("baseline", {}) if isinstance(feature_importance, dict) else {}
        baseline_generated_plans = _safe_int(baseline.get("generated_plans", 0))
        empty_scores = {key: 0.0 for key in FEATURE_KEYS}
        empty_feature_rows = {
            key: {
                "signal": 0.0,
                "weighted_component": 0.0,
                "weighted_realized_r": 0.0,
                "target_multiplier": 1.0,
            }
            for key in FEATURE_KEYS
        }
        fallback_current_scores = {
            key: _safe_float(((feature_importance.get("by_feature") or {}).get(key) or {}).get("importance_score", 0.0))
            for key in FEATURE_KEYS
        }
        fallback_feature_rows = {
            key: {
                "signal": round(fallback_current_scores[key], 6),
                "weighted_component": 0.0,
                "weighted_realized_r": 0.0,
                "target_multiplier": round(
                    1.0
                    + _safe_float(self.settings.feature_calibration_max_delta, 0.04)
                    * math.tanh(fallback_current_scores[key]),
                    6,
                ),
            }
            for key in FEATURE_KEYS
        }

        reason: str | None = None
        available = True
        has_learning_repos = self.plan_repo is not None and self.outcome_repo is not None
        matched = self._match_trades(symbol=symbol, regime_label=regime_label, now=now) if has_learning_repos else []
        matched_samples = len(matched) if has_learning_repos else baseline_generated_plans

        if not _safe_bool(self.settings.feature_calibration_enabled):
            available = False
            reason = "feature_calibration_disabled"
        elif not _safe_bool(feature_importance.get("available")):
            available = False
            reason = str(feature_importance.get("reason", "feature_importance_unavailable"))
        elif baseline_generated_plans < _safe_int(self.settings.feature_calibration_min_generated_plans, 3):
            available = False
            reason = "insufficient_generated_plans"
        elif has_learning_repos and matched_samples < _safe_int(self.settings.feature_calibration_min_matches, 12):
            available = False
            reason = "insufficient_matches"

        previous_snapshot = self.runtime_payload(symbol=symbol, regime_label=regime_label) or self._normalize_snapshot(
            latest=self._load_latest(symbol=symbol, regime_label=regime_label) or {},
            regime_label=regime_label,
        ) if self._load_latest(symbol=symbol, regime_label=regime_label) else None

        previous_weights = (
            dict((previous_snapshot.get("by_regime") or {}).get(regime_label, {}).get("feature_weights_active") or {})
            if previous_snapshot
            else {}
        )
        if not previous_weights:
            previous_weights = base_weights

        previous_ewma_scores = (
            dict((previous_snapshot.get("by_regime") or {}).get(regime_label, {}).get("ewma_scores") or {})
            if previous_snapshot
            else {}
        )
        if not previous_ewma_scores:
            previous_ewma_scores = empty_scores

        if not available:
            payload = self._base_payload(
                symbol=symbol,
                regime_label=regime_label,
                now=now,
                available=False,
                reason=reason,
                baseline_generated_plans=baseline_generated_plans,
                matched_samples=matched_samples,
                baseline_weights=base_weights,
                previous_weights=previous_weights,
                current_scores=empty_scores,
                ewma_scores=previous_ewma_scores,
                recommended_weights=base_weights,
                feature_rows=empty_feature_rows,
                zone_type_multipliers=self._default_zone_type_multipliers(),
                applied_runtime=False,
            )
        else:
            if matched:
                feature_rows, current_scores = self._feature_rows(matched)
                zone_type_multipliers = self._zone_type_rows(
                    rows=matched,
                    previous_snapshot=previous_snapshot,
                )
            else:
                feature_rows = fallback_feature_rows
                current_scores = fallback_current_scores
                zone_type_multipliers = self._default_zone_type_multipliers()
            alpha = clamp(_safe_float(self.settings.feature_calibration_alpha, 0.35), 0.0, 1.0)
            ewma_scores = {
                key: alpha * _safe_float(current_scores.get(key, 0.0))
                + (1.0 - alpha) * _safe_float(previous_ewma_scores.get(key, 0.0))
                for key in FEATURE_KEYS
            }
            target_weights = self._scores_to_target_weights(
                base_weights=base_weights,
                ewma_scores=ewma_scores,
            )
            recommended_weights = self._limit_delta(
                previous_weights={
                    key: _safe_float(previous_weights.get(key, base_weights[key]), base_weights[key])
                    for key in FEATURE_KEYS
                },
                target_weights=target_weights,
            )
            payload = self._base_payload(
                symbol=symbol,
                regime_label=regime_label,
                now=now,
                available=True,
                reason=None,
                baseline_generated_plans=baseline_generated_plans,
                matched_samples=matched_samples,
                baseline_weights=base_weights,
                previous_weights=previous_weights,
                current_scores=current_scores,
                ewma_scores=ewma_scores,
                recommended_weights=recommended_weights,
                feature_rows=feature_rows,
                zone_type_multipliers=zone_type_multipliers,
                applied_runtime=_safe_bool(self.settings.feature_calibration_apply_runtime),
            )

        if write_report:
            snapshot_path = self._write_snapshot(payload=payload, symbol=symbol, regime_label=regime_label, now=now)
            payload["snapshot_path"] = snapshot_path
            report_path = self._write_report(payload=payload, now=now)
            payload["report_path"] = report_path
            latest = self._latest_snapshot_path(self._snapshot_dir(), symbol=symbol, regime_label=regime_label)
            _atomic_write_text(latest, json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))

        return payload
