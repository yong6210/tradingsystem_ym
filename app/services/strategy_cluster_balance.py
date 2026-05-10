from __future__ import annotations

from collections import Counter
from typing import Any


_STATE_CONFIDENCE = {
    "research_only_mix": "low",
    "a_concentrated": "low",
    "guarded_rebalance": "medium",
    "balanced_mix": "high",
}

_ACTIVATION_SEVERITY = {
    "research_only": 0,
    "guarded_probation": 1,
    "blocked": 2,
    "activation_ready": 3,
}


class StrategyClusterBalanceService:
    @staticmethod
    def _safe_bool(value: Any, default: bool = False) -> bool:
        if value is None:
            return bool(default)
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        text = str(value).strip().lower()
        if text in {"1", "true", "yes", "y", "on"}:
            return True
        if text in {"0", "false", "no", "n", "off", "none", "null", ""}:
            return False
        return bool(default)

    @staticmethod
    def _dict(payload: dict[str, Any] | None) -> dict[str, Any]:
        return dict(payload or {})

    @staticmethod
    def _rows(payload: dict[str, Any] | None, key: str) -> list[dict[str, Any]]:
        return [dict(item) for item in list(dict(payload or {}).get(key) or [])]

    @staticmethod
    def _dedupe(values: list[str]) -> list[str]:
        out: list[str] = []
        for value in values:
            if value and value not in out:
                out.append(value)
        return out

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
    def _normalize_mode(value: Any) -> str:
        mode = str(value or "A_ONLY").strip().upper()
        return mode if mode in {"A_ONLY", "A_PLUS_B", "RESEARCH"} else "A_ONLY"

    def _family_mix(
        self,
        *,
        multi_strategy_ab: dict[str, Any],
        rows: list[dict[str, Any]] | None,
        portfolio_budget: dict[str, Any],
    ) -> list[dict[str, Any]]:
        family_mix = [dict(item) for item in list(multi_strategy_ab.get("family_mix") or [])]
        if family_mix:
            return family_mix

        counts: dict[str, Counter[str]] = {}
        source_rows = list(rows or [])
        if not source_rows:
            source_rows = [
                *list(portfolio_budget.get("accepted_candidates") or []),
                *list(portfolio_budget.get("blocked_candidates") or []),
                *list(portfolio_budget.get("alpha_research_candidates") or []),
            ]
        for row in source_rows:
            raw_family = str(row.get("strategy_family") or "").strip().lower()
            cluster = self._cluster(raw_family)
            if not cluster:
                continue
            state = "all"
            if self._safe_bool(row.get("accepted")):
                state = "accepted"
            elif self._safe_bool(row.get("alpha_research_candidate")):
                state = "alpha_research"
            elif row.get("block_reason"):
                state = "blocked"
            bucket = counts.setdefault(raw_family, Counter())
            bucket["all"] += 1
            bucket[state] += 1

        return [
            {
                "raw_family": family,
                "cluster": self._cluster(family),
                "total_candidates": int(bucket.get("all", 0)),
                "accepted_candidates": int(bucket.get("accepted", 0)),
                "blocked_candidates": int(bucket.get("blocked", 0)),
                "alpha_research_candidates": int(bucket.get("alpha_research", 0)),
            }
            for family, bucket in sorted(counts.items())
        ]

    @staticmethod
    def _cluster_bucket(family_mix: list[dict[str, Any]], cluster: str) -> dict[str, Any]:
        for row in family_mix:
            if str(row.get("cluster") or "").strip().lower() == cluster:
                return dict(row)
        return {}

    def _resolve_b_activation(self, *, payload: dict[str, Any], rows: list[dict[str, Any]] | None) -> tuple[str, str]:
        family = str(payload.get("family") or "").strip().lower()
        state = str(payload.get("activation_state") or "").strip().lower()
        bias = str(payload.get("activation_bias") or "").strip().lower()
        if family == "trend_continuation" and state:
            return state, bias or "stay_research"

        selected_state = "research_only"
        selected_bias = "stay_research"
        selected_rank = -1
        for row in list(rows or []):
            activation = dict(row.get("b_continuation_activation") or {})
            state = str(activation.get("activation_state") or "").strip().lower()
            if not state:
                continue
            rank = _ACTIVATION_SEVERITY.get(state, -1)
            if rank >= selected_rank:
                selected_rank = rank
                selected_state = state
                selected_bias = str(activation.get("activation_bias") or selected_bias).strip().lower() or selected_bias
        return selected_state, selected_bias

    @staticmethod
    def _allocator_focus(payload: dict[str, Any], rows: list[dict[str, Any]] | None) -> tuple[str, str]:
        focus = str(payload.get("family_focus") or "").strip().lower()
        state = str(payload.get("allocator_state") or "neutral").strip().lower()
        if focus:
            return focus, state

        best_family = ""
        best_weight = -1.0
        for row in list(rows or []):
            allocator = dict(row.get("capital_allocator") or {})
            family = str(allocator.get("family") or row.get("strategy_family") or "").strip().lower()
            weight = float(allocator.get("allocation_weight", row.get("allocation_weight", 1.0)) or 1.0)
            if family and weight > best_weight:
                best_family = family
                best_weight = weight
                state = str(allocator.get("allocator_state") or state).strip().lower() or state
        return best_family, state or "neutral"

    @staticmethod
    def _cluster_from_row(row: dict[str, Any]) -> str:
        cluster = str(row.get("strategy_cluster") or "").strip().lower()
        if cluster:
            return cluster
        overlay = dict(row.get("multi_strategy_overlay") or {})
        cluster = str(overlay.get("cluster") or "").strip().lower()
        if cluster:
            return cluster
        family = str(row.get("strategy_family") or "").strip().lower()
        if family == "sweep_reversal":
            return "a_reversal"
        if family == "trend_continuation":
            return "b_continuation"
        if family == "range_rotation":
            return "research_only_sidecar"
        return ""

    def generate(
        self,
        *,
        multi_strategy_ab: dict[str, Any] | None,
        b_continuation_activation: dict[str, Any] | None = None,
        capital_allocator: dict[str, Any] | None = None,
        rows: list[dict[str, Any]] | None = None,
        portfolio_budget: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        multi_strategy_payload = self._dict(multi_strategy_ab)
        b_activation_payload = self._dict(b_continuation_activation)
        capital_allocator_payload = self._dict(capital_allocator)
        portfolio_budget_payload = self._dict(portfolio_budget)
        row_list = [dict(row) for row in list(rows or [])]

        if not any([multi_strategy_payload, b_activation_payload, capital_allocator_payload, row_list, portfolio_budget_payload]):
            return {
                "available": False,
                "advisory_only": True,
                "summary": "strategy cluster balance unavailable",
            }

        mode = self._normalize_mode(
            multi_strategy_payload.get("mode") or portfolio_budget_payload.get("strategy_mode") or "A_ONLY"
        )
        family_mix = self._family_mix(
            multi_strategy_ab=multi_strategy_payload,
            rows=row_list,
            portfolio_budget=portfolio_budget_payload,
        )
        a_bucket = self._cluster_bucket(family_mix, "a_reversal")
        b_bucket = self._cluster_bucket(family_mix, "b_continuation")
        b_activation_state, b_activation_bias = self._resolve_b_activation(
            payload=b_activation_payload,
            rows=row_list,
        )
        allocator_focus, allocator_state = self._allocator_focus(capital_allocator_payload, row_list)
        b_cluster_status = str(
            dict(multi_strategy_payload.get("b_cluster") or {}).get("strategy_cluster_status") or ""
        ).strip().lower()

        a_total = int(a_bucket.get("total_candidates", 0) or 0)
        a_accepted = int(a_bucket.get("accepted_candidates", 0) or 0)
        b_total = int(b_bucket.get("total_candidates", 0) or 0)
        b_accepted = int(b_bucket.get("accepted_candidates", 0) or 0)
        b_alpha = int(b_bucket.get("alpha_research_candidates", 0) or 0)

        balance_state = "a_concentrated"
        balance_bias = "preserve_a_anchor"
        headline_cluster = "a_reversal"
        target_mix = "a_anchor_with_b_underweight"

        if mode in {"A_ONLY", "RESEARCH"} or b_activation_state == "research_only" or b_cluster_status in {
            "compare_only",
            "research_only",
        }:
            balance_state = "research_only_mix"
            balance_bias = "stay_a_anchor"
            headline_cluster = "a_reversal"
            target_mix = "a_anchor_only"
            summary = "A remains the live anchor while B continuation stays compare-only under the current mode."
        elif (
            a_accepted > 0
            and b_accepted > 0
            and b_activation_state not in {"blocked", "research_only"}
        ):
            balance_state = "balanced_mix"
            balance_bias = "hold_balanced_mix"
            headline_cluster = "balanced_mix"
            target_mix = "a_anchor_plus_b_secondary"
            summary = "A and B are both represented in the current candidate mix; keep the first-wave cluster balance stable."
        elif b_activation_state in {"guarded_probation", "activation_ready"} and (
            b_total > 0 or allocator_focus == "trend_continuation"
        ):
            balance_state = "guarded_rebalance"
            balance_bias = "build_guarded_b_mix"
            headline_cluster = "b_continuation"
            target_mix = "a_anchor_plus_guarded_b"
            summary = "A still anchors the live mix, but B continuation is the current guarded diversification candidate."
        else:
            summary = "The current mix remains concentrated in A while B continuation is still underweight or blocked."

        confidence = _STATE_CONFIDENCE.get(balance_state, "low")
        if balance_state == "guarded_rebalance" and b_activation_state == "activation_ready":
            confidence = "high"

        reason_codes = self._dedupe(
            [
                f"cluster_balance:{balance_state}",
                f"mode:{mode.lower()}",
                f"headline_cluster:{headline_cluster}",
                f"b_activation:{b_activation_state}",
                f"b_cluster_status:{b_cluster_status or 'unavailable'}",
                f"allocator_focus:{allocator_focus or 'unknown'}",
                f"allocator_state:{allocator_state or 'neutral'}",
                "balance:b_underallocated" if b_accepted < a_accepted else "",
                "balance:b_research_candidate_present" if b_alpha > 0 else "",
            ]
        )

        return {
            "available": True,
            "advisory_only": True,
            "mode": mode,
            "balance_state": balance_state,
            "balance_bias": balance_bias,
            "headline_cluster": headline_cluster,
            "target_mix": target_mix,
            "confidence": confidence,
            "family_mix": family_mix,
            "summary": summary,
            "reason_codes": reason_codes,
            "source_summary": {
                "a_total_candidates": a_total,
                "a_accepted_candidates": a_accepted,
                "b_total_candidates": b_total,
                "b_accepted_candidates": b_accepted,
                "b_alpha_research_candidates": b_alpha,
                "b_activation_state": b_activation_state,
                "b_activation_bias": b_activation_bias,
                "b_cluster_status": b_cluster_status or "unavailable",
                "allocator_focus": allocator_focus or "unknown",
                "allocator_state": allocator_state or "neutral",
            },
        }

    def annotate_rows(
        self,
        rows: list[dict[str, Any]] | None,
        *,
        strategy_cluster_balance_summary: dict[str, Any] | None = None,
        multi_strategy_ab: dict[str, Any] | None = None,
        b_continuation_activation: dict[str, Any] | None = None,
        capital_allocator: dict[str, Any] | None = None,
        portfolio_budget: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        summary_payload = dict(strategy_cluster_balance_summary or {})
        row_list = [dict(row) for row in list(rows or [])]
        if not summary_payload:
            summary_payload = self.generate(
                multi_strategy_ab=multi_strategy_ab,
                b_continuation_activation=b_continuation_activation,
                capital_allocator=capital_allocator,
                rows=row_list,
                portfolio_budget=portfolio_budget,
            )

        balance_state = str(summary_payload.get("balance_state") or "a_concentrated").strip().lower()
        balance_bias = str(summary_payload.get("balance_bias") or "preserve_a_anchor").strip().lower()
        source_summary = dict(summary_payload.get("source_summary") or {})
        b_activation_state = str(source_summary.get("b_activation_state") or "research_only").strip().lower()

        annotated: list[dict[str, Any]] = []
        for row in row_list:
            item = dict(row)
            cluster = self._cluster_from_row(item)
            if not cluster:
                annotated.append(item)
                continue

            if cluster == "b_continuation":
                if balance_state == "balanced_mix":
                    pressure = "balanced_support"
                    summary = "B continuation is represented in the current mix and should stay as a guarded secondary cluster."
                elif balance_state == "guarded_rebalance":
                    pressure = "diversification_candidate"
                    summary = "B continuation is the current guarded diversification candidate while A remains the anchor."
                elif balance_state == "research_only_mix":
                    pressure = "research_only"
                    summary = "B continuation remains compare-only and should stay in research posture under the current mode."
                elif b_activation_state == "blocked":
                    pressure = "guardrail_limited"
                    summary = "B continuation is still guardrail-limited; clear blockers before trying to rebalance the cluster mix."
                else:
                    pressure = "underweight_candidate"
                    summary = "B continuation remains underweight versus the current A anchor."
            elif cluster == "a_reversal":
                pressure = "balanced_anchor" if balance_state == "balanced_mix" else "anchor_preserve"
                summary = "A reversal remains the current anchor cluster in the live mix."
            else:
                pressure = "sidecar_observe"
                summary = "This cluster remains a sidecar and does not drive the current A/B balance posture."

            item["strategy_cluster_balance"] = {
                "available": True,
                "cluster": cluster,
                "balance_state": balance_state,
                "balance_pressure": pressure,
                "balance_bias": balance_bias,
                "headline_cluster": str(summary_payload.get("headline_cluster") or "a_reversal"),
                "summary": summary,
            }
            annotated.append(item)
        return annotated
