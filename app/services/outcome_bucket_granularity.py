from __future__ import annotations

from typing import Any


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


_CONDITION_AXES = (
    "volatility_condition",
    "cost_condition",
    "liquidity_condition",
)


class OutcomeBucketGranularityService:
    @staticmethod
    def _dict(payload: dict[str, Any] | None) -> dict[str, Any]:
        return dict(payload or {})

    @staticmethod
    def _rows(payload: dict[str, Any] | None, key: str) -> list[dict[str, Any]]:
        return [dict(item) for item in list(dict(payload or {}).get(key) or [])]

    @staticmethod
    def _compact_bucket(row: dict[str, Any] | None) -> dict[str, Any] | None:
        normalized = dict(row or {})
        if not normalized:
            return None
        return {
            "key": str(normalized.get("key") or "unknown"),
            "runtime_candidates": int(normalized.get("runtime_candidates", 0) or 0),
            "submitted": int(normalized.get("submitted", 0) or 0),
            "closed": int(normalized.get("closed", 0) or 0),
            "baseline_cost_profitable_rate_from_closed": float(
                normalized.get("baseline_cost_profitable_rate_from_closed", 0.0) or 0.0
            ),
        }

    @classmethod
    def _family_focus(cls, rows: list[dict[str, Any]]) -> dict[str, Any] | None:
        normalized_rows = [dict(row) for row in rows if dict(row)]
        if not normalized_rows:
            return None
        selected = min(
            normalized_rows,
            key=lambda item: (
                -int(item.get("closed", 0) or 0),
                float(item.get("baseline_cost_profitable_rate_from_closed", 0.0) or 0.0),
                str(item.get("key") or ""),
            ),
        )
        return cls._compact_bucket(selected)

    @staticmethod
    def _usable_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in rows
            if str(row.get("key") or "unknown") != "unknown" and int(row.get("closed", 0) or 0) >= 4
        ]

    @staticmethod
    def _mature_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in rows
            if str(row.get("key") or "unknown") != "unknown" and int(row.get("closed", 0) or 0) >= 8
        ]

    @classmethod
    def _axis_summary(cls, *, axis: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
        normalized_rows = [dict(row) for row in rows if dict(row)]
        usable_rows = cls._usable_rows(normalized_rows)
        mature_rows = cls._mature_rows(normalized_rows)

        if usable_rows:
            best_row = max(
                usable_rows,
                key=lambda item: (
                    float(item.get("baseline_cost_profitable_rate_from_closed", 0.0) or 0.0),
                    int(item.get("closed", 0) or 0),
                    str(item.get("key") or ""),
                ),
            )
            worst_row = min(
                usable_rows,
                key=lambda item: (
                    float(item.get("baseline_cost_profitable_rate_from_closed", 0.0) or 0.0),
                    -int(item.get("closed", 0) or 0),
                    str(item.get("key") or ""),
                ),
            )
            divergence = round(
                float(best_row.get("baseline_cost_profitable_rate_from_closed", 0.0) or 0.0)
                - float(worst_row.get("baseline_cost_profitable_rate_from_closed", 0.0) or 0.0),
                4,
            )
        else:
            best_row = {}
            worst_row = {}
            divergence = 0.0

        if len(mature_rows) >= 2:
            coverage_state = "mature_condition_split"
        elif len(usable_rows) >= 2:
            coverage_state = "usable_condition_split"
        elif normalized_rows:
            coverage_state = "thin_condition_coverage"
        else:
            coverage_state = "no_condition_data"

        return {
            "axis": axis,
            "available": _safe_bool(normalized_rows),
            "usable_bucket_count": len(usable_rows),
            "mature_bucket_count": len(mature_rows),
            "divergence": divergence,
            "coverage_state": coverage_state,
            "best_bucket": cls._compact_bucket(best_row),
            "worst_bucket": cls._compact_bucket(worst_row),
            "proxy_note": "liquidity_proxy" if axis == "liquidity_condition" else None,
        }

    @staticmethod
    def _confidence(*, top_axis: dict[str, Any] | None) -> str:
        axis_payload = dict(top_axis or {})
        divergence = float(axis_payload.get("divergence", 0.0) or 0.0)
        mature_bucket_count = int(axis_payload.get("mature_bucket_count", 0) or 0)
        if axis_payload and mature_bucket_count >= 2 and divergence >= 0.2:
            return "high"
        if axis_payload and divergence >= 0.15:
            return "medium"
        return "low"

    @staticmethod
    def _summary(
        *,
        family_focus: dict[str, Any] | None,
        top_axis: dict[str, Any] | None,
        top_bucket: dict[str, Any] | None,
    ) -> str:
        family = str(dict(family_focus or {}).get("key") or "unknown")
        axis_name = str(dict(top_axis or {}).get("axis") or "")
        bucket_name = str(dict(top_bucket or {}).get("key") or "")
        if not axis_name or not bucket_name:
            return (
                f"family={family} remains family-first; condition coverage is still thin or the current condition split "
                "is not yet strong enough to treat as a supporting modifier."
            )
        if axis_name == "volatility_condition":
            return (
                f"family={family} shows its largest condition split in volatility, with drag concentrated in "
                f"{bucket_name}; treat this as a supporting modifier, not a standalone signal."
            )
        if axis_name == "cost_condition":
            return (
                f"family={family} shows the largest post-cost split in {bucket_name}; review cost-sensitive buckets "
                "before changing thresholds."
            )
        if axis_name == "liquidity_condition":
            return (
                f"family={family} shows the largest liquidity-proxy split in {bucket_name}; treat shallow-liquidity "
                "drag as an informational condition modifier, not a root-cause certainty."
            )
        return (
            f"family={family} shows the largest condition split in {axis_name}:{bucket_name}; use it as a supporting "
            "comparison layer only."
        )

    @staticmethod
    def _dedupe(values: list[str]) -> list[str]:
        out: list[str] = []
        for value in values:
            if value and value not in out:
                out.append(value)
        return out

    @classmethod
    def generate(cls, *, score_to_outcome_funnel: dict[str, Any] | None) -> dict[str, Any] | None:
        payload = cls._dict(score_to_outcome_funnel)
        if not payload:
            return None

        decomposition = cls._dict(payload.get("decomposition"))
        family_focus = cls._family_focus(cls._rows(decomposition, "family"))
        axis_summaries = [
            cls._axis_summary(axis=axis, rows=cls._rows(decomposition, axis))
            for axis in _CONDITION_AXES
        ]

        top_axis = max(
            axis_summaries,
            key=lambda item: (
                float(item.get("divergence", 0.0) or 0.0),
                int(item.get("usable_bucket_count", 0) or 0),
                int(item.get("mature_bucket_count", 0) or 0),
                str(item.get("axis") or ""),
            ),
            default=None,
        )
        if not top_axis or float(top_axis.get("divergence", 0.0) or 0.0) < 0.15:
            top_axis = None

        top_bucket = dict(top_axis.get("worst_bucket") or {}) if top_axis else None
        confidence = cls._confidence(top_axis=top_axis)
        coverage_reason = (
            str(top_axis.get("coverage_state") or "thin_condition_coverage")
            if top_axis
            else "thin_condition_coverage"
        )

        return {
            "available": _safe_bool(payload.get("available", False)),
            "advisory_only": True,
            "report_window_days": int(payload.get("report_window_days", 0) or 0),
            "family_focus": family_focus,
            "top_condition_axis": str(top_axis.get("axis") or "") if top_axis else "",
            "top_condition_bucket": top_bucket or None,
            "confidence": confidence,
            "summary": cls._summary(
                family_focus=family_focus,
                top_axis=top_axis,
                top_bucket=top_bucket,
            ),
            "reason_codes": cls._dedupe(
                [
                    f"family_focus:{str(dict(family_focus or {}).get('key') or 'unknown')}",
                    f"top_axis:{str(top_axis.get('axis') or 'none')}" if top_axis else "top_axis:none",
                    (
                        f"top_bucket:{str(dict(top_bucket or {}).get('key') or 'none')}"
                        if top_bucket
                        else "top_bucket:none"
                    ),
                    f"coverage:{coverage_reason}",
                ]
            ),
            "condition_axes": axis_summaries,
        }
