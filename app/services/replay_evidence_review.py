from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import Settings, get_settings
from app.db.repositories import CandleRepository, ExecutionFillRepository, PlanRepository
from app.services.strategy_family_edge_review import StrategyFamilyEdgeReviewService
from app.services.strategy_v2_stress_replay_assessment import StrategyV2StressReplayAssessmentService
from app.services.strategy_v2_stress_replay_lineage import StrategyV2StressReplayLineageService
from app.services.strategy_v2_stress_validation import StrategyV2StressValidationService


class ReplayEvidenceReviewService:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        plan_repo: PlanRepository | None = None,
        fill_repo: ExecutionFillRepository | None = None,
        candle_repo: CandleRepository | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.plan_repo = plan_repo
        self.fill_repo = fill_repo
        self.candle_repo = candle_repo
        self.family_review = StrategyFamilyEdgeReviewService(
            settings=self.settings,
            plan_repo=self.plan_repo,
            fill_repo=self.fill_repo,
        )
        self.stress_validation = StrategyV2StressValidationService(
            self.settings,
            fill_repo=self.fill_repo,
            candle_repo=self.candle_repo,
        )
        self.replay_lineage = StrategyV2StressReplayLineageService(
            self.settings,
            plan_repo=self.plan_repo,
            fill_repo=self.fill_repo,
            candle_repo=self.candle_repo,
        )
        self.replay_assessment = StrategyV2StressReplayAssessmentService(self.settings)

    @staticmethod
    def _confidence_state(
        *,
        a_review: dict[str, Any],
        b_review: dict[str, Any],
        replay_lineage: dict[str, Any],
        replay_assessment: dict[str, Any],
    ) -> tuple[str, str, str]:
        lineage_ready = bool(replay_lineage.get("available", False)) and bool(replay_lineage.get("runtime_inputs_ready", False))
        eligible_closed = int(dict(replay_assessment.get("sample_counts") or {}).get("eligible_closed_trades", 0) or 0)
        a_state = str(a_review.get("edge_state") or "insufficient_sample")
        b_state = str(b_review.get("edge_state") or "insufficient_sample")
        decision = str(dict(replay_assessment.get("deployment_recommendation") or {}).get("decision") or "keep_approximation")

        if not lineage_ready:
            return (
                "insufficient_replay_lineage",
                "gather_more_replay_evidence",
                "Replay lineage is still incomplete, so historical evidence should stay descriptive only.",
            )
        if eligible_closed < 4 or (a_state == "insufficient_sample" and b_state == "insufficient_sample"):
            return (
                "insufficient_replay_evidence",
                "gather_more_replay_evidence",
                "Replay-style evidence is still too thin to influence live confidence.",
            )
        if decision in {"prepare_full_replay", "recommend_full_replay"} or a_state == "insufficient_edge":
            return (
                "fragile_replay_evidence",
                "use_as_context_only",
                "Replay evidence is informative, but lineage or edge fragility is still too high for strong confidence.",
            )
        if a_state in {"validated_edge", "fragile_edge"}:
            return (
                "validated_replay_evidence",
                "combine_with_live_evidence",
                "Replay evidence is directionally supportive, but it must still be combined with live evidence.",
            )
        return (
            "fragile_replay_evidence",
            "use_as_context_only",
            "Replay evidence is usable as context, but not stable enough to stand on its own.",
        )

    @staticmethod
    def _next_actions(
        *,
        a_review: dict[str, Any],
        b_review: dict[str, Any],
        replay_lineage: dict[str, Any],
        replay_assessment: dict[str, Any],
    ) -> list[str]:
        actions = [
            "Treat replay evidence as historical context only; do not merge it into live sample counts.",
            "Keep A/B live confidence decisions anchored to closed live evidence first.",
        ]
        actions.extend(list(a_review.get("next_actions") or [])[:2])
        actions.extend(list(b_review.get("next_actions") or [])[:1])
        actions.extend(list(replay_lineage.get("next_steps") or [])[:1])
        actions.extend(list(replay_assessment.get("next_steps") or [])[:1])
        out: list[str] = []
        seen: set[str] = set()
        for step in actions:
            if step in seen:
                continue
            seen.add(step)
            out.append(step)
        return out[:6]

    def summarize(
        self,
        *,
        symbol: str,
        version: str,
        days: int,
        a_review: dict[str, Any],
        b_review: dict[str, Any],
        replay_lineage: dict[str, Any],
        replay_assessment: dict[str, Any],
        write_report: bool = True,
    ) -> dict[str, Any]:
        confidence_state, evidence_bias, summary = self._confidence_state(
            a_review=a_review,
            b_review=b_review,
            replay_lineage=replay_lineage,
            replay_assessment=replay_assessment,
        )
        payload: dict[str, Any] = {
            "schema_version": "replay_evidence_review_v1",
            "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "symbol": symbol,
            "version": version,
            "days": int(days),
            "evidence_basis": "historical_closed_plans_plus_stress_replay_lineage_proxy",
            "do_not_treat_as_live_confidence": True,
            "confidence_state": confidence_state,
            "evidence_bias": evidence_bias,
            "summary": summary,
            "a_review": a_review,
            "b_review": b_review,
            "replay_lineage": {
                "available": bool(replay_lineage.get("available", False)),
                "runtime_inputs_ready": bool(replay_lineage.get("runtime_inputs_ready", False)),
                "reason": replay_lineage.get("reason"),
                "coverage": dict(replay_lineage.get("coverage") or {}),
                "blocked_by": list(replay_lineage.get("blocked_by") or []),
                "next_steps": list(replay_lineage.get("next_steps") or []),
            },
            "replay_assessment": {
                "available": bool(replay_assessment.get("available", False)),
                "full_replay_ready": bool(replay_assessment.get("full_replay_ready", False)),
                "replacement_recommended": bool(replay_assessment.get("replacement_recommended", False)),
                "reason": replay_assessment.get("reason"),
                "sample_counts": dict(replay_assessment.get("sample_counts") or {}),
                "coverage": dict(replay_assessment.get("coverage") or {}),
                "deployment_recommendation": dict(replay_assessment.get("deployment_recommendation") or {}),
                "next_steps": list(replay_assessment.get("next_steps") or []),
            },
            "next_actions": self._next_actions(
                a_review=a_review,
                b_review=b_review,
                replay_lineage=replay_lineage,
                replay_assessment=replay_assessment,
            ),
            "report_path": None,
        }
        if write_report:
            payload["report_path"] = self._write_report(payload=payload)
        return payload

    def _write_report(self, *, payload: dict[str, Any]) -> str:
        out_dir = Path(self.settings.replay_evidence_review_report_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc).replace(microsecond=0)
        file_path = out_dir / f"replay_evidence_review_{payload['symbol']}_{now.strftime('%Y%m%dT%H%M%SZ')}.md"
        lineage = dict(payload.get("replay_lineage") or {})
        assessment = dict(payload.get("replay_assessment") or {})
        a_review = dict(payload.get("a_review") or {})
        b_review = dict(payload.get("b_review") or {})
        lines = [
            f"# Replay Evidence Review: {payload['symbol']}",
            "",
            f"- generated_at: {payload['generated_at']}",
            f"- symbol: {payload['symbol']}",
            f"- version: {payload['version']}",
            f"- days: {payload['days']}",
            f"- evidence_basis: {payload['evidence_basis']}",
            f"- do_not_treat_as_live_confidence: {payload['do_not_treat_as_live_confidence']}",
            "",
            "## Headline",
            "",
            f"- confidence_state: {payload['confidence_state']}",
            f"- evidence_bias: {payload['evidence_bias']}",
            f"- summary: {payload['summary']}",
            "",
            "## A / B Family Replay Context",
            "",
            f"- A edge_state: {a_review.get('edge_state')} | bias: {a_review.get('analysis_bias')} | trades: {dict(a_review.get('target_metrics') or {}).get('trades', 0)}",
            f"- B edge_state: {b_review.get('edge_state')} | bias: {b_review.get('analysis_bias')} | trades: {dict(b_review.get('target_metrics') or {}).get('trades', 0)}",
            "",
            "## Replay Lineage",
            "",
            f"- available: {lineage.get('available')}",
            f"- runtime_inputs_ready: {lineage.get('runtime_inputs_ready')}",
            f"- reason: {lineage.get('reason')}",
            f"- coverage: {lineage.get('coverage')}",
            f"- blocked_by: {lineage.get('blocked_by')}",
            "",
            "## Replay Assessment",
            "",
            f"- available: {assessment.get('available')}",
            f"- full_replay_ready: {assessment.get('full_replay_ready')}",
            f"- replacement_recommended: {assessment.get('replacement_recommended')}",
            f"- reason: {assessment.get('reason')}",
            f"- deployment_recommendation: {assessment.get('deployment_recommendation')}",
            "",
            "## Next Actions",
        ]
        for step in payload.get("next_actions") or []:
            lines.append(f"- {step}")
        file_path.write_text("\n".join(lines), encoding="utf-8")
        return str(file_path)

    def generate(
        self,
        *,
        symbol: str,
        days: int = 180,
        version: str | None = None,
        write_report: bool = True,
        limit: int = 10000,
    ) -> dict[str, Any]:
        if self.plan_repo is None:
            raise RuntimeError("plan_repo_not_configured")
        active_version = str(version or self.settings.strategy_version)
        a_review = self.family_review.generate(
            family="sweep_reversal",
            peer_family="trend_continuation",
            days=days,
            symbol=symbol,
            version=active_version,
            write_report=False,
            limit=limit,
        )
        b_review = self.family_review.generate(
            family="trend_continuation",
            peer_family="sweep_reversal",
            days=days,
            symbol=symbol,
            version=active_version,
            write_report=False,
            limit=limit,
        )
        plans = self.plan_repo.list_recent(symbol=symbol, days=days)
        stress_validation = self.stress_validation.generate(
            symbol=symbol,
            version=active_version,
            plans=plans,
            write_report=False,
        )
        replay_lineage = self.replay_lineage.generate(
            symbol=symbol,
            version=active_version,
            write_report=False,
        )
        replay_assessment = self.replay_assessment.generate(
            symbol=symbol,
            version=active_version,
            stress_validation=stress_validation,
            stress_replay_lineage=replay_lineage,
            write_report=False,
        )
        return self.summarize(
            symbol=symbol,
            version=active_version,
            days=days,
            a_review=a_review,
            b_review=b_review,
            replay_lineage=replay_lineage,
            replay_assessment=replay_assessment,
            write_report=write_report,
        )
