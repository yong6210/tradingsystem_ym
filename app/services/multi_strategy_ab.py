from __future__ import annotations

from collections import Counter
from typing import Any


_LIVE_MODES = {"A_ONLY", "A_PLUS_B"}


class MultiStrategyABExpansionService:
    @staticmethod
    def _dict(payload: dict[str, Any] | None) -> dict[str, Any]:
        return dict(payload or {})

    @staticmethod
    def _rows(payload: dict[str, Any] | None, key: str) -> list[dict[str, Any]]:
        return [dict(item) for item in list(dict(payload or {}).get(key) or [])]

    @staticmethod
    def _normalize_mode(value: Any) -> str:
        text = str(value or "A_ONLY").strip().upper()
        return text if text in {"A_ONLY", "A_PLUS_B", "RESEARCH"} else "A_ONLY"

    @staticmethod
    def _cluster(raw_family: Any) -> str:
        family = str(raw_family or "").strip().lower()
        if family == "sweep_reversal":
            return "a_reversal"
        if family == "trend_continuation":
            return "b_continuation"
        if family == "range_rotation":
            return "research_only_sidecar"
        return ""

    @staticmethod
    def _dedupe(values: list[str]) -> list[str]:
        out: list[str] = []
        for value in values:
            if value and value not in out:
                out.append(value)
        return out

    def _family_outcome_row(self, *, score_to_outcome_funnel: dict[str, Any], family: str) -> dict[str, Any]:
        rows = {
            str(row.get("key") or "unknown").strip().lower(): dict(row)
            for row in self._rows(dict(score_to_outcome_funnel.get("decomposition") or {}), "family")
        }
        return dict(rows.get(family) or {})

    def _family_execution_row(
        self,
        *,
        family_execution_degradation_advisory: dict[str, Any],
        family: str,
    ) -> dict[str, Any]:
        rows = {
            str(row.get("family") or "unknown").strip().lower(): dict(row)
            for row in self._rows(family_execution_degradation_advisory, "families")
        }
        return dict(rows.get(family) or {})

    @staticmethod
    def _rollout_row(*, rollout_recommendation: dict[str, Any], family: str) -> dict[str, Any]:
        if str(rollout_recommendation.get("family") or "").strip().lower() == family:
            return dict(rollout_recommendation)
        return {}

    @staticmethod
    def _lifecycle_row(*, strategy_lifecycle: dict[str, Any], family: str) -> dict[str, Any]:
        if str(strategy_lifecycle.get("family") or "").strip().lower() == family:
            return dict(strategy_lifecycle)
        return {}

    def _family_guardrails(
        self,
        *,
        family: str,
        score_to_outcome_funnel: dict[str, Any] | None,
        family_execution_degradation_advisory: dict[str, Any] | None,
        rollout_recommendation: dict[str, Any] | None,
        strategy_lifecycle: dict[str, Any] | None,
    ) -> dict[str, Any]:
        outcome_row = self._family_outcome_row(
            score_to_outcome_funnel=self._dict(score_to_outcome_funnel),
            family=family,
        )
        execution_row = self._family_execution_row(
            family_execution_degradation_advisory=self._dict(family_execution_degradation_advisory),
            family=family,
        )
        rollout_row = self._rollout_row(rollout_recommendation=self._dict(rollout_recommendation), family=family)
        lifecycle_row = self._lifecycle_row(strategy_lifecycle=self._dict(strategy_lifecycle), family=family)

        closed = int(outcome_row.get("closed", 0) or 0)
        execution_status = str(execution_row.get("status") or "unavailable").strip().lower()
        rollout_state = str(rollout_row.get("recommendation") or "").strip().lower()
        lifecycle_state = str(lifecycle_row.get("state") or "").strip().lower()

        reason_codes: list[str] = []
        if family == "trend_continuation":
            if closed < 4:
                reason_codes.append("b_guardrail:thin_sample")
            if execution_status == "manual_review":
                reason_codes.append("b_guardrail:family_execution_manual_review")
            if rollout_state in {"reduce", "research_only"}:
                reason_codes.append(f"b_guardrail:rollout_{rollout_state}")
            if lifecycle_state == "research":
                reason_codes.append("b_guardrail:lifecycle_research")

        return {
            "closed": closed,
            "execution_status": execution_status or "unavailable",
            "rollout_recommendation": rollout_state or "unavailable",
            "lifecycle_state": lifecycle_state or "unavailable",
            "guardrail_reasons": self._dedupe(reason_codes),
        }

    def overlay_for_row(
        self,
        row: dict[str, Any],
        *,
        score_to_outcome_funnel: dict[str, Any] | None = None,
        family_execution_degradation_advisory: dict[str, Any] | None = None,
        rollout_recommendation: dict[str, Any] | None = None,
        strategy_lifecycle: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        item = dict(row or {})
        raw_family = str(item.get("strategy_family") or dict(item.get("validity") or {}).get("strategy_family") or "").strip().lower()
        cluster = self._cluster(raw_family)
        if not cluster:
            return None

        mode = self._normalize_mode(item.get("strategy_mode") or dict(item.get("validity") or {}).get("strategy_mode"))
        mode_shadow_only = bool(item.get("mode_shadow_only", False))
        alpha_research_candidate = bool(item.get("alpha_research_candidate", False))
        family_guardrails = self._family_guardrails(
            family=raw_family,
            score_to_outcome_funnel=score_to_outcome_funnel,
            family_execution_degradation_advisory=family_execution_degradation_advisory,
            rollout_recommendation=rollout_recommendation,
            strategy_lifecycle=strategy_lifecycle,
        )
        reason_codes = [f"cluster:{cluster}", f"mode:{mode.lower()}"]
        live_eligible = False
        guarded = False
        cluster_status = "overlay_unavailable"
        summary = ""

        if cluster == "a_reversal":
            if mode == "RESEARCH":
                guarded = True
                cluster_status = "research_only_anchor"
                reason_codes.append("a_anchor:research_only_mode")
                summary = "A reversal remains the current anchor but is research-only under the active mode."
            else:
                live_eligible = not mode_shadow_only and not alpha_research_candidate
                guarded = not live_eligible
                cluster_status = "current_anchor" if live_eligible else "guarded_anchor"
                if mode_shadow_only:
                    reason_codes.append("a_anchor:mode_shadow_only")
                if alpha_research_candidate:
                    reason_codes.append("a_anchor:alpha_research_candidate")
                summary = "A reversal remains the current production anchor in the first-wave A/B contract."
        elif cluster == "b_continuation":
            guarded = True
            if mode == "RESEARCH":
                cluster_status = "research_only"
                reason_codes.append("b_guardrail:mode_research_only")
                summary = "B continuation is visible as research-only while the mode remains compare-only."
            elif mode == "A_ONLY":
                cluster_status = "compare_only"
                reason_codes.append("b_guardrail:mode_a_only")
                summary = "B continuation is visible but remains outside live eligibility while the mode stays A_ONLY."
            else:
                guardrail_reasons = list(family_guardrails.get("guardrail_reasons") or [])
                if not guardrail_reasons:
                    live_eligible = not mode_shadow_only and not alpha_research_candidate
                    if mode_shadow_only:
                        guardrail_reasons.append("b_guardrail:mode_shadow_only")
                    if alpha_research_candidate:
                        guardrail_reasons.append("b_guardrail:alpha_research_candidate")
                if guardrail_reasons:
                    cluster_status = "available_but_guarded"
                    reason_codes.extend(guardrail_reasons)
                    summary = "B continuation is available under A_PLUS_B but remains guarded until first-wave guardrails clear."
                else:
                    cluster_status = "probation_ready"
                    summary = "B continuation is available as a guarded first-wave secondary family under A_PLUS_B."
            if not live_eligible:
                guarded = True
        else:
            cluster_status = "research_only_sidecar"
            guarded = True
            reason_codes.append("sidecar:range_rotation")
            summary = "Range rotation remains a research-only sidecar in the first-wave A/B contract."

        return {
            "available": True,
            "cluster": cluster,
            "raw_family": raw_family,
            "mode": mode,
            "live_eligible": bool(live_eligible),
            "guarded": bool(guarded),
            "guardrail_reasons": self._dedupe(reason_codes[2:] if len(reason_codes) > 2 else []),
            "summary": summary,
            "strategy_cluster_status": cluster_status,
            "reason_codes": self._dedupe(reason_codes),
        }

    def annotate_rows(
        self,
        rows: list[dict[str, Any]] | None,
        *,
        score_to_outcome_funnel: dict[str, Any] | None = None,
        family_execution_degradation_advisory: dict[str, Any] | None = None,
        rollout_recommendation: dict[str, Any] | None = None,
        strategy_lifecycle: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        annotated: list[dict[str, Any]] = []
        for row in list(rows or []):
            item = dict(row)
            overlay = self.overlay_for_row(
                item,
                score_to_outcome_funnel=score_to_outcome_funnel,
                family_execution_degradation_advisory=family_execution_degradation_advisory,
                rollout_recommendation=rollout_recommendation,
                strategy_lifecycle=strategy_lifecycle,
            )
            if overlay:
                item["strategy_cluster"] = overlay.get("cluster")
                item["strategy_cluster_status"] = overlay.get("strategy_cluster_status")
                item["multi_strategy_overlay"] = overlay
            annotated.append(item)
        return annotated

    def _family_mix(
        self,
        *,
        portfolio_budget: dict[str, Any] | None = None,
        scanner_rows: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        counts: dict[str, Counter[str]] = {}
        rows = list(scanner_rows or [])
        if not rows and portfolio_budget:
            rows = [
                *list(dict(portfolio_budget).get("accepted_candidates") or []),
                *list(dict(portfolio_budget).get("blocked_candidates") or []),
                *list(dict(portfolio_budget).get("alpha_research_candidates") or []),
            ]
        for row in rows:
            raw_family = str(row.get("strategy_family") or "").strip().lower()
            cluster = self._cluster(raw_family)
            if not cluster:
                continue
            state = "all"
            if bool(row.get("accepted")):
                state = "accepted"
            elif bool(row.get("alpha_research_candidate")):
                state = "alpha_research"
            elif row.get("block_reason"):
                state = "blocked"
            bucket = counts.setdefault(raw_family, Counter())
            bucket["all"] += 1
            bucket[state] += 1
            bucket[f"cluster:{cluster}"] += 1

        family_mix: list[dict[str, Any]] = []
        for raw_family, bucket in sorted(counts.items()):
            cluster = self._cluster(raw_family)
            family_mix.append(
                {
                    "raw_family": raw_family,
                    "cluster": cluster,
                    "total_candidates": int(bucket.get("all", 0)),
                    "accepted_candidates": int(bucket.get("accepted", 0)),
                    "blocked_candidates": int(bucket.get("blocked", 0)),
                    "alpha_research_candidates": int(bucket.get("alpha_research", 0)),
                }
            )
        return family_mix

    def generate(
        self,
        *,
        portfolio_budget: dict[str, Any] | None = None,
        scanner_rows: list[dict[str, Any]] | None = None,
        score_to_outcome_funnel: dict[str, Any] | None = None,
        family_execution_degradation_advisory: dict[str, Any] | None = None,
        rollout_recommendation: dict[str, Any] | None = None,
        strategy_lifecycle: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        budget_payload = self._dict(portfolio_budget)
        family_mix = self._family_mix(portfolio_budget=budget_payload, scanner_rows=scanner_rows)
        mode = self._normalize_mode(
            budget_payload.get("strategy_mode")
            or ((list(scanner_rows or [])[:1] or [{}])[0]).get("strategy_mode")
        )
        if not family_mix and not mode:
            return {"available": False, "advisory_only": True, "summary": "multi-strategy A/B summary unavailable"}

        a_overlay = self.overlay_for_row(
            {"strategy_family": "sweep_reversal", "strategy_mode": mode},
            score_to_outcome_funnel=score_to_outcome_funnel,
            family_execution_degradation_advisory=family_execution_degradation_advisory,
            rollout_recommendation=rollout_recommendation,
            strategy_lifecycle=strategy_lifecycle,
        ) or {}
        b_overlay = self.overlay_for_row(
            {"strategy_family": "trend_continuation", "strategy_mode": mode},
            score_to_outcome_funnel=score_to_outcome_funnel,
            family_execution_degradation_advisory=family_execution_degradation_advisory,
            rollout_recommendation=rollout_recommendation,
            strategy_lifecycle=strategy_lifecycle,
        ) or {}
        sidecar_overlay = self.overlay_for_row(
            {"strategy_family": "range_rotation", "strategy_mode": mode},
            score_to_outcome_funnel=score_to_outcome_funnel,
            family_execution_degradation_advisory=family_execution_degradation_advisory,
            rollout_recommendation=rollout_recommendation,
            strategy_lifecycle=strategy_lifecycle,
        ) or {}

        family_mix_by_raw = {str(row.get("raw_family") or ""): dict(row) for row in family_mix}
        a_cluster = {
            **a_overlay,
            **dict(family_mix_by_raw.get("sweep_reversal") or {}),
        }
        b_cluster = {
            **b_overlay,
            **dict(family_mix_by_raw.get("trend_continuation") or {}),
        }
        research_sidecar = {
            **sidecar_overlay,
            **dict(family_mix_by_raw.get("range_rotation") or {}),
        }

        reason_codes = self._dedupe(
            [
                f"mode:{mode.lower()}",
                *list(a_cluster.get("reason_codes") or []),
                *list(b_cluster.get("reason_codes") or []),
                *list(research_sidecar.get("reason_codes") or []),
            ]
        )

        if mode == "RESEARCH":
            summary = (
                "A and B remain compare-only research flows while range rotation stays a research-only sidecar."
            )
        elif mode == "A_ONLY":
            summary = (
                "A reversal remains the current production anchor; B continuation is visible as compare-only guarded flow "
                "while range rotation stays research-only sidecar."
            )
        elif bool(b_cluster.get("live_eligible", False)):
            summary = (
                "A reversal remains the current production anchor and B continuation is available as a guarded first-wave "
                "secondary family; range rotation remains research-only sidecar."
            )
        else:
            summary = (
                "A reversal remains the current production anchor while B continuation stays available but guarded under "
                "first-wave activation rules; range rotation remains research-only sidecar."
            )

        return {
            "available": True,
            "advisory_only": True,
            "mode": mode,
            "raw_family_anchor": "sweep_reversal",
            "a_cluster": a_cluster,
            "b_cluster": b_cluster,
            "research_sidecar": research_sidecar,
            "family_mix": family_mix,
            "summary": summary,
            "reason_codes": reason_codes,
        }
