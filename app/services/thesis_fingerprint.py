from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Any

from app.core.config import Settings, get_settings
from app.db.models import Plan

_EQUIVALENT_NARRATIVES = {
    "pdh_sweep": "session_high_sweep",
    "pdl_sweep": "session_low_sweep",
    "session_high_sweep": "session_high_sweep",
    "session_low_sweep": "session_low_sweep",
    "equal_highs_sweep": "session_high_sweep",
    "equal_lows_sweep": "session_low_sweep",
    "trend_pullback_to_discount": "trend_pullback_to_discount",
    "trend_pullback_to_premium": "trend_pullback_to_premium",
    "range_upper_reject": "range_upper_reject",
    "range_lower_reject": "range_lower_reject",
}

_VALID_FAMILIES = {"sweep_reversal", "trend_continuation", "range_rotation", "session_impulse_retest"}
_VALID_REGIMES = {"trend", "range", "shock", "transition"}
_VALID_EVENTS = {
    "rejection_confirmed",
    "rejection_tentative",
    "acceptance_confirmed",
    "acceptance_tentative",
    "mixed",
}
_MAJOR_BASES = {
    "BNB",
    "SOL",
    "XRP",
    "ADA",
    "DOGE",
    "AVAX",
    "DOT",
    "LINK",
    "LTC",
    "BCH",
    "TRX",
    "ATOM",
}


class ThesisFingerprintService:
    """Shared thesis identity contract across plan generation, scanner, and execution."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    @staticmethod
    def _safe_int(value: Any, default: int = 0) -> int:
        if value in (None, "", "None"):
            return default
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return default
        return int(parsed) if isfinite(parsed) else default

    @staticmethod
    def _safe_bool(value: Any, default: bool = False) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "y", "on"}:
                return True
            if normalized in {"0", "false", "no", "n", "off", "none", "null", ""}:
                return False
        return True if value else False

    def build(
        self,
        *,
        symbol: str,
        direction: str,
        regime: str,
        strategy_family: str,
        reaction_classification: str | None,
        zone_type: str | None,
        near_lp: bool,
        at: datetime | None = None,
    ) -> dict[str, str]:
        normalized_at = self._normalize_dt(at)
        family = self._normalize_family(strategy_family)
        event_classification = self._normalize_event_classification(
            reaction_classification=reaction_classification,
            strategy_family=family,
        )
        fingerprint = {
            "direction": self._normalize_direction(direction),
            "regime": self._normalize_regime(regime),
            "strategy_family": family,
            "liquidity_narrative": self._infer_liquidity_narrative(
                direction=direction,
                regime=regime,
                strategy_family=family,
                reaction_classification=event_classification,
                zone_type=zone_type,
                near_lp=near_lp,
            ),
            "event_classification": event_classification,
            "time_bucket": self._time_bucket_label(normalized_at),
            "correlation_cluster": self._infer_correlation_cluster(symbol),
        }
        return fingerprint

    def build_from_plan(self, plan: Plan) -> dict[str, str]:
        validity = dict(plan.validity or {})
        stored = validity.get("thesis_fingerprint")
        if isinstance(stored, dict):
            return self.normalize(
                stored,
                symbol=plan.symbol,
                direction=plan.direction,
                regime=validity.get("regime"),
                strategy_family=validity.get("strategy_family"),
                at=plan.valid_from,
            )

        return self.build(
            symbol=plan.symbol,
            direction=plan.direction,
            regime=str(validity.get("regime", "range")),
            strategy_family=str(validity.get("strategy_family", "legacy_zone_plan")),
            reaction_classification=str(validity.get("reaction_classification", "mixed")),
            zone_type=str(validity.get("zone_type", "")),
            near_lp=self._safe_bool(validity.get("near_lp", False)),
            at=plan.valid_from,
        )

    def build_from_candidate(self, row: dict[str, Any], *, at: datetime | None = None) -> dict[str, str] | None:
        stored = row.get("thesis_fingerprint")
        if isinstance(stored, dict):
            return self.normalize(
                stored,
                symbol=row.get("symbol"),
                direction=row.get("direction"),
                regime=row.get("regime"),
                strategy_family=row.get("strategy_family"),
                at=at or row.get("valid_from"),
            )

        validity = dict(row.get("validity") or {})
        has_contract = bool(validity) or row.get("strategy_family") is not None
        if not has_contract:
            return None
        return self.build(
            symbol=str(row.get("symbol", "")),
            direction=str(row.get("direction", "")),
            regime=str(row.get("regime") or validity.get("regime", "range")),
            strategy_family=str(row.get("strategy_family") or validity.get("strategy_family", "legacy_zone_plan")),
            reaction_classification=str(validity.get("reaction_classification", "mixed")),
            zone_type=str(validity.get("zone_type", row.get("zone_type", ""))),
            near_lp=self._safe_bool(validity.get("near_lp", False)),
            at=at or row.get("valid_from"),
        )

    def normalize(
        self,
        fingerprint: dict[str, Any] | None,
        *,
        symbol: str | None = None,
        direction: str | None = None,
        regime: str | None = None,
        strategy_family: str | None = None,
        at: datetime | None = None,
    ) -> dict[str, str]:
        data = dict(fingerprint or {})
        normalized_at = self._normalize_dt(at)
        family = self._normalize_family(str(data.get("strategy_family") or strategy_family or "legacy_zone_plan"))
        return {
            "direction": self._normalize_direction(str(data.get("direction") or direction or "long")),
            "regime": self._normalize_regime(str(data.get("regime") or regime or "range")),
            "strategy_family": family,
            "liquidity_narrative": self._normalize_liquidity_narrative(str(data.get("liquidity_narrative") or "")),
            "event_classification": self._normalize_event_classification(
                reaction_classification=str(data.get("event_classification") or "mixed"),
                strategy_family=family,
            ),
            "time_bucket": self._normalize_time_bucket(str(data.get("time_bucket") or ""), fallback=normalized_at),
            "correlation_cluster": str(data.get("correlation_cluster") or self._infer_correlation_cluster(symbol or "")),
        }

    def thesis_cluster_id(self, fingerprint: dict[str, Any]) -> str:
        normalized = self.normalize(fingerprint)
        return ":".join(
            [
                normalized["direction"],
                normalized["regime"],
                normalized["strategy_family"],
                self._canonical_narrative(normalized["liquidity_narrative"]),
                self._event_group(normalized["event_classification"]),
                normalized["time_bucket"],
                normalized["correlation_cluster"],
            ]
        )

    def same_thesis(self, left: dict[str, Any] | None, right: dict[str, Any] | None) -> bool:
        if not left or not right:
            return False
        lhs = self.normalize(left)
        rhs = self.normalize(right)
        return (
            lhs["direction"] == rhs["direction"]
            and lhs["regime"] == rhs["regime"]
            and lhs["strategy_family"] == rhs["strategy_family"]
            and self._canonical_narrative(lhs["liquidity_narrative"]) == self._canonical_narrative(rhs["liquidity_narrative"])
            and self._event_group(lhs["event_classification"]) == self._event_group(rhs["event_classification"])
            and lhs["correlation_cluster"] == rhs["correlation_cluster"]
            and self._same_or_adjacent_bucket(lhs["time_bucket"], rhs["time_bucket"])
        )

    def event_group(self, classification: str) -> str:
        return self._event_group(classification)

    def correlation_cluster(self, symbol: str) -> str:
        return self._infer_correlation_cluster(symbol)

    def liquidity_equivalence(self, narrative: str) -> str:
        return self._canonical_narrative(narrative)

    @staticmethod
    def _normalize_dt(value: datetime | None) -> datetime:
        current = value or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        return current.astimezone(timezone.utc)

    @staticmethod
    def _normalize_direction(direction: str) -> str:
        return "short" if str(direction).lower() == "short" else "long"

    def _normalize_regime(self, regime: str) -> str:
        candidate = str(regime).lower()
        if candidate in _VALID_REGIMES:
            return candidate
        return "range"

    def _normalize_family(self, strategy_family: str) -> str:
        family = str(strategy_family).lower()
        if family in _VALID_FAMILIES:
            return family
        return "legacy_zone_plan"

    def _normalize_event_classification(self, *, reaction_classification: str | None, strategy_family: str) -> str:
        classification = str(reaction_classification or "").lower()
        if classification in _VALID_EVENTS:
            return classification
        if strategy_family == "trend_continuation":
            return "acceptance_tentative"
        if strategy_family == "session_impulse_retest":
            return "acceptance_confirmed"
        if strategy_family in {"sweep_reversal", "range_rotation"}:
            return "rejection_tentative"
        return "mixed"

    def _normalize_liquidity_narrative(self, narrative: str) -> str:
        value = str(narrative or "").lower()
        if value in _EQUIVALENT_NARRATIVES:
            return value
        return "trend_pullback_to_discount" if "discount" in value else "trend_pullback_to_premium" if "premium" in value else "session_low_sweep"

    def _infer_liquidity_narrative(
        self,
        *,
        direction: str,
        regime: str,
        strategy_family: str,
        reaction_classification: str,
        zone_type: str | None,
        near_lp: bool,
    ) -> str:
        side = self._normalize_direction(direction)
        family = self._normalize_family(strategy_family)
        zone_type_normalized = str(zone_type or "").upper()
        regime_name = self._normalize_regime(regime)
        event_group = self._event_group(reaction_classification)

        if family == "trend_continuation":
            return "trend_pullback_to_discount" if side == "long" else "trend_pullback_to_premium"
        if family == "range_rotation" or regime_name == "range":
            return "range_lower_reject" if side == "long" else "range_upper_reject"
        if event_group == "rejection":
            if zone_type_normalized == "LP":
                return "equal_lows_sweep" if side == "long" else "equal_highs_sweep"
            if near_lp:
                return "session_low_sweep" if side == "long" else "session_high_sweep"
            return "pdl_sweep" if side == "long" else "pdh_sweep"
        if zone_type_normalized == "LP":
            return "equal_lows_sweep" if side == "long" else "equal_highs_sweep"
        return "trend_pullback_to_discount" if side == "long" else "trend_pullback_to_premium"

    def _infer_correlation_cluster(self, symbol: str) -> str:
        base = str(symbol or "").upper()
        for suffix in ("USDC", "USDT", "BUSD", "USD", "PERP"):
            if base.endswith(suffix):
                base = base[: -len(suffix)]
                break
        if base.startswith("BTC"):
            return "btc_beta"
        if base.startswith("ETH"):
            return "eth_beta"
        if base in _MAJOR_BASES:
            return "majors"
        return "others"

    def _time_bucket_label(self, dt: datetime) -> str:
        bucket_minutes = max(1, self._safe_int(self.settings.thesis_time_bucket_minutes, default=30))
        minute = (dt.minute // bucket_minutes) * bucket_minutes
        bucket = dt.replace(minute=minute, second=0, microsecond=0)
        return f"{bucket.strftime('%Y-%m-%dT%H:%MZ')}_{bucket_minutes}m"

    def _normalize_time_bucket(self, value: str, *, fallback: datetime) -> str:
        bucket_minutes = max(1, self._safe_int(self.settings.thesis_time_bucket_minutes, default=30))
        if value.endswith(f"_{bucket_minutes}m") and self._bucket_dt(value) is not None:
            return value
        return self._time_bucket_label(fallback)

    def _bucket_dt(self, value: str) -> datetime | None:
        stem = value.rsplit("_", maxsplit=1)[0]
        try:
            parsed = datetime.fromisoformat(stem.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _same_or_adjacent_bucket(self, left: str, right: str) -> bool:
        if left == right:
            return True
        left_dt = self._bucket_dt(left)
        right_dt = self._bucket_dt(right)
        if left_dt is None or right_dt is None:
            return False
        return abs(left_dt - right_dt) <= timedelta(
            minutes=max(1, self._safe_int(self.settings.thesis_time_bucket_minutes, default=30))
        )

    def _canonical_narrative(self, narrative: str) -> str:
        return _EQUIVALENT_NARRATIVES.get(str(narrative).lower(), self._normalize_liquidity_narrative(narrative))

    def _event_group(self, classification: str) -> str:
        normalized = str(classification).lower()
        if normalized.startswith("rejection_"):
            return "rejection"
        if normalized.startswith("acceptance_"):
            return "acceptance"
        return "mixed"
