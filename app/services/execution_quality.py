from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.core.config import Settings, get_settings
from app.core.enums import EntryModel, ExecutionFillStage, ExitReason, PlanState
from app.db.models import ExecutionFill, Plan, ZoneOutcome
from app.db.repositories import CandleRepository, ExecutionFillRepository, OutcomeRepository, PlanRepository
from app.services.exit_engine import FORCED_EXIT_REASONS, TARGET_EXIT_REASONS


@dataclass(slots=True)
class MatchedEntry:
    source: str
    price: float
    fee: float
    qty: float
    first_fill_ts: datetime
    event_count: int


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    index = (len(ordered) - 1) * ratio
    low = int(index)
    high = min(low + 1, len(ordered) - 1)
    weight = index - low
    return float(ordered[low] + (ordered[high] - ordered[low]) * weight)


def _summary(values: list[float]) -> dict[str, float]:
    if not values:
        return {"avg": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0}
    return {
        "avg": float(sum(values) / len(values)),
        "p50": _percentile(values, 0.50),
        "p95": _percentile(values, 0.95),
        "max": float(max(values)),
    }


class ExecutionQualityService:
    def __init__(
        self,
        *,
        plan_repo: PlanRepository,
        outcome_repo: OutcomeRepository,
        candle_repo: CandleRepository,
        fill_repo: ExecutionFillRepository | None = None,
        settings: Settings | None = None,
    ):
        self.plan_repo = plan_repo
        self.outcome_repo = outcome_repo
        self.candle_repo = candle_repo
        self.fill_repo = fill_repo
        self.settings = settings or get_settings()

    @staticmethod
    def _is_matured(plan: Plan, *, now: datetime, has_entry: bool) -> bool:
        terminal_states = {
            PlanState.ARCHIVED.value,
            PlanState.CLOSED.value,
            PlanState.ENTERED.value,
            PlanState.PARTIAL_EXIT.value,
        }
        return has_entry or _utc(plan.valid_until) <= now or plan.state in terminal_states

    @staticmethod
    def _stage_value(stage: Any) -> str:
        if isinstance(stage, ExecutionFillStage):
            return stage.value
        return str(stage)

    @staticmethod
    def _model_value(entry_model: Any) -> str:
        if isinstance(entry_model, EntryModel):
            return entry_model.value
        return str(entry_model).upper()

    def _aggregate_actual_entries(
        self,
        fills: list[ExecutionFill],
    ) -> tuple[dict[str, MatchedEntry], dict[str, int], dict[str, set[str]]]:
        grouped: dict[str, list[ExecutionFill]] = defaultdict(list)
        stage_counts: dict[str, int] = defaultdict(int)
        plan_stage_presence: dict[str, set[str]] = defaultdict(set)
        for fill in fills:
            stage = self._stage_value(fill.stage)
            stage_counts[stage] += 1
            plan_stage_presence[fill.plan_id].add(stage)
            if stage == ExecutionFillStage.ENTRY.value:
                grouped[fill.plan_id].append(fill)

        out: dict[str, MatchedEntry] = {}
        for plan_id, rows in grouped.items():
            qty_total = float(sum(float(row.qty) for row in rows))
            notional = float(sum(float(row.qty) * float(row.price) for row in rows))
            fee_total = float(sum(float(row.fee) for row in rows))
            first_fill_ts = min(_utc(row.fill_ts) for row in rows)
            price = float(notional / qty_total) if qty_total > 0 else float(rows[0].price)
            out[plan_id] = MatchedEntry(
                source="execution_fills",
                price=price,
                fee=fee_total,
                qty=qty_total,
                first_fill_ts=first_fill_ts,
                event_count=len(rows),
            )
        return (
            out,
            {key: int(value) for key, value in stage_counts.items()},
            {key: set(value) for key, value in plan_stage_presence.items()},
        )

    @staticmethod
    def _group_fills_by_plan(fills: list[ExecutionFill]) -> dict[str, list[ExecutionFill]]:
        grouped: dict[str, list[ExecutionFill]] = defaultdict(list)
        for fill in fills:
            grouped[fill.plan_id].append(fill)
        return grouped

    @staticmethod
    def _empty_unfilled_reasons() -> dict[str, int]:
        return {
            "not_reached_entry": 0,
            "touch_no_fill": 0,
            "touch_no_confirmation": 0,
            "missing_market_data": 0,
            "triggered_no_entry": 0,
        }

    @staticmethod
    def _empty_unfilled_reason_details() -> dict[str, int]:
        return {
            "expired_without_touch": 0,
            "expired_after_touch_limit": 0,
            "expired_after_touch_confirmation": 0,
            "timed_out_after_trigger": 0,
            "order_rejected": 0,
            "cancelled_before_entry": 0,
            "missing_market_data": 0,
        }

    @staticmethod
    def _empty_exit_reasons() -> dict[str, int]:
        return {reason.value: 0 for reason in ExitReason}

    def _match_legacy_outcomes(
        self,
        *,
        plans: list[Plan],
        already_matched_plan_ids: set[str],
        outcomes: list[ZoneOutcome],
    ) -> dict[str, MatchedEntry]:
        by_zone: dict[str, list[ZoneOutcome]] = defaultdict(list)
        for outcome in outcomes:
            by_zone[outcome.zone_id].append(outcome)

        for rows in by_zone.values():
            rows.sort(key=lambda row: _utc(row.entry_ts))

        matched: dict[str, MatchedEntry] = {}
        ordered_plans = sorted(plans, key=lambda plan: (_utc(plan.valid_from), plan.plan_id))
        for plan in ordered_plans:
            if plan.plan_id in already_matched_plan_ids:
                continue
            candidates = by_zone.get(plan.zone_id, [])
            if not candidates:
                continue

            model = self._model_value(plan.entry_model)
            window_start = _utc(plan.valid_from) - timedelta(minutes=5)
            window_end = max(_utc(plan.valid_until), _utc(plan.valid_from)) + timedelta(days=1)
            match_index = -1
            for index, outcome in enumerate(candidates):
                if self._model_value(outcome.entry_model_used) != model:
                    continue
                entry_ts = _utc(outcome.entry_ts)
                if window_start <= entry_ts <= window_end:
                    match_index = index
                    break

            if match_index < 0:
                continue

            outcome = candidates.pop(match_index)
            matched[plan.plan_id] = MatchedEntry(
                source="zone_outcomes_fallback",
                price=float(outcome.entry_price),
                fee=0.0,
                qty=0.0,
                first_fill_ts=_utc(outcome.entry_ts),
                event_count=1,
            )
        return matched

    def _slippage_bps(self, *, plan: Plan, entry: MatchedEntry) -> float:
        target = float(plan.entry_price or 0.0)
        if target <= 0.0:
            return 0.0
        direction = str(plan.direction).lower()
        if direction == "short":
            return float((target - entry.price) / target * 10_000.0)
        return float((entry.price - target) / target * 10_000.0)

    def _entry_latency_seconds(self, *, plan: Plan, entry: MatchedEntry) -> float:
        valid_from = _utc(plan.valid_from)
        latency = (entry.first_fill_ts - valid_from).total_seconds()
        return float(max(0.0, latency))

    @staticmethod
    def _execution_hint(plan_fills: list[ExecutionFill]) -> str | None:
        reject_tokens = (
            "reject",
            "rejected",
            "insufficient",
            "post only reject",
            "post_only_reject",
            "would trigger immediately",
            "immediate or cancel",
            "expired_in_match",
        )
        cancel_tokens = (
            "cancel",
            "cancelled",
            "canceled",
            "expired",
            "timeout",
            "timed_out",
        )
        for fill in plan_fills:
            payload = dict(fill.payload or {})
            values: list[str] = [fill.stage, fill.from_state, fill.to_state]
            for key in (
                "status",
                "reason",
                "result",
                "error",
                "error_code",
                "cancel_reason",
                "order_status",
                "execution_type",
                "exec_type",
            ):
                value = payload.get(key)
                if value is not None:
                    values.append(str(value))
            text = " ".join(values).lower()
            if any(token in text for token in reject_tokens):
                return "order_rejected"
            if any(token in text for token in cancel_tokens):
                return "cancelled_before_entry"
        return None

    def _classify_unfilled(
        self,
        *,
        plan: Plan,
        now: datetime,
        plan_fills: list[ExecutionFill],
        stages: set[str],
    ) -> tuple[str, str]:
        hint = self._execution_hint(plan_fills)
        if hint == "order_rejected":
            return "triggered_no_entry", "order_rejected"
        if hint == "cancelled_before_entry":
            return "triggered_no_entry", "cancelled_before_entry"
        if ExecutionFillStage.TRIGGERED.value in stages or plan.state == PlanState.TRIGGERED.value:
            return "triggered_no_entry", "timed_out_after_trigger"

        end_ts = min(_utc(plan.valid_until), now)
        start_ts = _utc(plan.valid_from)
        if end_ts < start_ts:
            end_ts = start_ts
        candles = self.candle_repo.list_range(
            symbol=plan.symbol,
            timeframe=plan.timeframe,
            start_ts=start_ts,
            end_ts=end_ts,
        )
        if not candles:
            return "missing_market_data", "missing_market_data"

        touched = any(float(candle.l) <= float(plan.entry_price) <= float(candle.h) for candle in candles)
        if not touched:
            return "not_reached_entry", "expired_without_touch"

        model = self._model_value(plan.entry_model)
        if model == EntryModel.LIMIT.value:
            return "touch_no_fill", "expired_after_touch_limit"
        return "touch_no_confirmation", "expired_after_touch_confirmation"

    @staticmethod
    def _strategy_family(plan: Plan) -> str:
        validity = dict(plan.validity or {})
        return str(validity.get("strategy_family") or "legacy_zone_plan")

    @staticmethod
    def _final_exit_reason(plan: Plan, plan_fills: list[ExecutionFill]) -> str | None:
        for fill in reversed(plan_fills):
            if str(fill.stage) != ExecutionFillStage.CLOSED.value:
                continue
            payload = dict(fill.payload or {})
            reason = payload.get("exit_reason")
            if reason:
                return str(reason)
        validity = dict(plan.validity or {})
        reason = validity.get("final_exit_reason")
        return str(reason) if reason else None

    @staticmethod
    def _all_exit_reasons(plan: Plan, plan_fills: list[ExecutionFill]) -> list[str]:
        reasons: list[str] = []
        for fill in plan_fills:
            if str(fill.stage) not in {ExecutionFillStage.PARTIAL_EXIT.value, ExecutionFillStage.CLOSED.value}:
                continue
            payload = dict(fill.payload or {})
            reason = payload.get("exit_reason")
            if reason:
                reasons.append(str(reason))
        if reasons:
            return reasons
        final_reason = dict(plan.validity or {}).get("final_exit_reason")
        return [str(final_reason)] if final_reason else []

    def _build_bucket_payload(
        self,
        *,
        plans: list[Plan],
        now: datetime,
        matched_entries: dict[str, MatchedEntry],
        plan_stage_presence: dict[str, set[str]],
        plan_fill_map: dict[str, list[ExecutionFill]],
    ) -> dict[str, Any]:
        slippages: list[float] = []
        entry_latencies: list[float] = []
        entry_fees: list[float] = []
        all_bucket_fills: list[ExecutionFill] = []
        unfilled_reasons = self._empty_unfilled_reasons()
        unfilled_reason_details = self._empty_unfilled_reason_details()
        exit_reasons = self._empty_exit_reasons()
        final_exit_reasons = self._empty_exit_reasons()
        by_strategy_family: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "closed": 0,
                "filled": 0,
                "final_exit_reasons": self._empty_exit_reasons(),
                "target_exit_rate": 0.0,
                "forced_exit_rate": 0.0,
                "information_failure_rate": 0.0,
                "time_failure_rate": 0.0,
            }
        )
        by_entry_model: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "plans": 0,
                "filled": 0,
                "execution_source": 0,
                "partial_exit": 0,
                "closed": 0,
                "slippages": [],
                "latencies": [],
            }
        )
        stage_counts: dict[str, int] = defaultdict(int)
        matured_plans = 0
        filled_plans = 0
        closed_plans = 0
        target_exit_count = 0
        forced_exit_count = 0
        information_failure_count = 0
        time_failure_count = 0
        fill_sources = {
            "execution_fills": 0,
            "zone_outcomes_fallback": 0,
        }

        for plan in plans:
            plan_fills = plan_fill_map.get(plan.plan_id, [])
            all_bucket_fills.extend(plan_fills)
            for fill in plan_fills:
                stage_counts[self._stage_value(fill.stage)] += 1

            entry = matched_entries.get(plan.plan_id)
            is_matured = self._is_matured(plan, now=now, has_entry=entry is not None)
            if not is_matured:
                continue

            matured_plans += 1
            model = self._model_value(plan.entry_model)
            family = self._strategy_family(plan)
            by_entry_model[model]["plans"] += 1

            stages = plan_stage_presence.get(plan.plan_id, set())
            if entry is not None:
                filled_plans += 1
                by_entry_model[model]["filled"] += 1
                by_strategy_family[family]["filled"] += 1
                fill_sources[entry.source] = int(fill_sources.get(entry.source, 0)) + 1
                if entry.source == "execution_fills":
                    by_entry_model[model]["execution_source"] += 1
                if ExecutionFillStage.PARTIAL_EXIT.value in stages:
                    by_entry_model[model]["partial_exit"] += 1
                if ExecutionFillStage.CLOSED.value in stages:
                    by_entry_model[model]["closed"] += 1
                slippage = self._slippage_bps(plan=plan, entry=entry)
                latency = self._entry_latency_seconds(plan=plan, entry=entry)
                slippages.append(slippage)
                entry_latencies.append(latency)
                if entry.source == "execution_fills":
                    entry_fees.append(float(entry.fee))
                by_entry_model[model]["slippages"].append(slippage)
                by_entry_model[model]["latencies"].append(latency)
            else:
                reason_group, reason_detail = self._classify_unfilled(
                    plan=plan,
                    now=now,
                    plan_fills=plan_fills,
                    stages=stages,
                )
                unfilled_reasons[reason_group] = int(unfilled_reasons.get(reason_group, 0)) + 1
                unfilled_reason_details[reason_detail] = int(unfilled_reason_details.get(reason_detail, 0)) + 1

            for reason in self._all_exit_reasons(plan, plan_fills):
                if reason in exit_reasons:
                    exit_reasons[reason] = int(exit_reasons.get(reason, 0)) + 1

            final_exit_reason = self._final_exit_reason(plan, plan_fills)
            if final_exit_reason and final_exit_reason in final_exit_reasons:
                closed_plans += 1
                final_exit_reasons[final_exit_reason] = int(final_exit_reasons.get(final_exit_reason, 0)) + 1
                by_strategy_family[family]["closed"] += 1
                family_reasons = by_strategy_family[family]["final_exit_reasons"]
                family_reasons[final_exit_reason] = int(family_reasons.get(final_exit_reason, 0)) + 1
                if final_exit_reason in TARGET_EXIT_REASONS:
                    target_exit_count += 1
                if final_exit_reason in FORCED_EXIT_REASONS:
                    forced_exit_count += 1
                if final_exit_reason == ExitReason.INFORMATION_FAILURE.value:
                    information_failure_count += 1
                if final_exit_reason == ExitReason.TIME_FAILURE.value:
                    time_failure_count += 1

        by_entry_model_out: dict[str, dict[str, float]] = {}
        for model, stats in sorted(by_entry_model.items()):
            plans_count = int(stats["plans"])
            filled_count = int(stats["filled"])
            execution_source_count = int(stats["execution_source"])
            partial_exit_count = int(stats["partial_exit"])
            closed_count = int(stats["closed"])
            model_slippages = [float(value) for value in stats["slippages"]]
            model_latencies = [float(value) for value in stats["latencies"]]
            by_entry_model_out[model] = {
                "plans": float(plans_count),
                "filled": float(filled_count),
                "fill_rate": float(filled_count / plans_count) if plans_count else 0.0,
                "avg_slippage_bps": float(sum(model_slippages) / len(model_slippages)) if model_slippages else 0.0,
                "avg_entry_latency_seconds": (
                    float(sum(model_latencies) / len(model_latencies)) if model_latencies else 0.0
                ),
                "execution_source_rate": (
                    float(execution_source_count / filled_count) if filled_count else 0.0
                ),
                "partial_exit_rate": float(partial_exit_count / filled_count) if filled_count else 0.0,
                "closed_rate": float(closed_count / filled_count) if filled_count else 0.0,
            }

        by_strategy_family_out: dict[str, dict[str, Any]] = {}
        for family, stats in sorted(by_strategy_family.items()):
            closed_count = int(stats["closed"])
            final_counts = {key: int(value) for key, value in sorted(stats["final_exit_reasons"].items())}
            target = sum(final_counts.get(reason, 0) for reason in TARGET_EXIT_REASONS)
            forced = sum(final_counts.get(reason, 0) for reason in FORCED_EXIT_REASONS)
            info = int(final_counts.get(ExitReason.INFORMATION_FAILURE.value, 0))
            time = int(final_counts.get(ExitReason.TIME_FAILURE.value, 0))
            by_strategy_family_out[family] = {
                "filled": int(stats["filled"]),
                "closed": closed_count,
                "final_exit_reasons": final_counts,
                "target_exit_rate": float(target / closed_count) if closed_count else 0.0,
                "forced_exit_rate": float(forced / closed_count) if closed_count else 0.0,
                "information_failure_rate": float(info / closed_count) if closed_count else 0.0,
                "time_failure_rate": float(time / closed_count) if closed_count else 0.0,
            }

        fill_fee_total = float(sum(float(fill.fee) for fill in all_bucket_fills))
        return {
            "plans_total": len(plans),
            "plans_matured": matured_plans,
            "fills_matched": filled_plans,
            "fill_events_total": len(all_bucket_fills),
            "fill_rate": float(filled_plans / matured_plans) if matured_plans else 0.0,
            "fill_sources": fill_sources,
            "stage_counts": {
                stage: int(stage_counts.get(stage, 0))
                for stage in [
                    ExecutionFillStage.TRIGGERED.value,
                    ExecutionFillStage.ENTRY.value,
                    ExecutionFillStage.PARTIAL_EXIT.value,
                    ExecutionFillStage.CLOSED.value,
                ]
            },
            "slippage_bps": _summary(slippages),
            "entry_latency_seconds": _summary(entry_latencies),
            "fees": {
                "total": fill_fee_total,
                "avg_per_fill": float(fill_fee_total / len(all_bucket_fills)) if all_bucket_fills else 0.0,
                "avg_entry_fee": float(sum(entry_fees) / len(entry_fees)) if entry_fees else 0.0,
            },
            "unfilled_reasons": unfilled_reasons,
            "unfilled_reason_details": unfilled_reason_details,
            "exit_reasons": exit_reasons,
            "final_exit_reasons": final_exit_reasons,
            "target_exit_ratio": float(target_exit_count / closed_plans) if closed_plans else 0.0,
            "forced_exit_ratio": float(forced_exit_count / closed_plans) if closed_plans else 0.0,
            "information_failure_ratio": (
                float(information_failure_count / closed_plans) if closed_plans else 0.0
            ),
            "time_failure_ratio": float(time_failure_count / closed_plans) if closed_plans else 0.0,
            "by_entry_model": by_entry_model_out,
            "by_strategy_family": by_strategy_family_out,
        }

    def _write_report(self, *, payload: dict[str, Any], now: datetime) -> str:
        out_dir = Path(self.settings.execution_quality_report_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        file_path = out_dir / f"quality_{payload['symbol']}_{now.strftime('%Y%m%dT%H%M%SZ')}.md"

        lines = [
            f"# Execution Quality Report: {payload['symbol']}",
            "",
            f"- generated_at_utc: {payload['generated_at']}",
            f"- lookback_days: {payload['days']}",
            "- entry_source_priority: execution_fills -> legacy_outcomes",
            "- unfilled_reason_source: candles",
            f"- comparison_axis: {payload['comparison_axis']}",
            "",
            "## Summary",
            f"- plans_total: {payload['plans_total']}",
            f"- plans_matured: {payload['plans_matured']}",
            f"- fills_matched: {payload['fills_matched']}",
            f"- fill_events_total: {payload['fill_events_total']}",
            f"- fill_rate: {payload['fill_rate']:.4f}",
            f"- versions_compared: {payload['versions_compared']}",
            "",
            "## Fill Sources",
        ]
        for source, count in sorted(payload["fill_sources"].items()):
            lines.append(f"- {source}: {count}")

        lines.extend(
            [
                "",
                "## Fill Stages",
            ]
        )
        for stage, count in sorted(payload["stage_counts"].items()):
            lines.append(f"- {stage}: {count}")

        slippage = payload["slippage_bps"]
        latency = payload["entry_latency_seconds"]
        fees = payload["fees"]
        lines.extend(
            [
                "",
                "## Slippage / Latency / Fees",
                f"- slippage_bps avg/p50/p95/max: {slippage['avg']:.4f}/{slippage['p50']:.4f}/{slippage['p95']:.4f}/{slippage['max']:.4f}",
                f"- entry_latency_seconds avg/p50/p95/max: {latency['avg']:.2f}/{latency['p50']:.2f}/{latency['p95']:.2f}/{latency['max']:.2f}",
                f"- fees total/avg_per_fill/avg_entry_fee: {fees['total']:.6f}/{fees['avg_per_fill']:.6f}/{fees['avg_entry_fee']:.6f}",
                "",
                "## Unfilled Reasons",
            ]
        )
        for reason, count in sorted(payload["unfilled_reasons"].items()):
            lines.append(f"- {reason}: {count}")

        lines.extend(
            [
                "",
                "## Unfilled Reason Details",
            ]
        )
        for reason, count in sorted(payload["unfilled_reason_details"].items()):
            lines.append(f"- {reason}: {count}")

        lines.extend(
            [
                "",
                "## Exit Reasons",
            ]
        )
        for reason, count in sorted(payload["exit_reasons"].items()):
            lines.append(f"- {reason}: {count}")

        lines.extend(
            [
                "",
                "## Final Exit Summary",
                f"- target_exit_ratio: {payload['target_exit_ratio']:.4f}",
                f"- forced_exit_ratio: {payload['forced_exit_ratio']:.4f}",
                f"- information_failure_ratio: {payload['information_failure_ratio']:.4f}",
                f"- time_failure_ratio: {payload['time_failure_ratio']:.4f}",
            ]
        )
        for reason, count in sorted(payload["final_exit_reasons"].items()):
            lines.append(f"- final_{reason}: {count}")

        lines.extend(
            [
                "",
                "## By Entry Model",
            ]
        )
        for model, stats in sorted(payload["by_entry_model"].items()):
            lines.append(
                f"- {model}: plans={int(stats['plans'])}, filled={int(stats['filled'])}, "
                f"fill_rate={stats['fill_rate']:.4f}, avg_slippage_bps={stats['avg_slippage_bps']:.4f}, "
                f"avg_entry_latency_seconds={stats['avg_entry_latency_seconds']:.2f}, "
                f"execution_source_rate={stats['execution_source_rate']:.4f}, "
                f"partial_exit_rate={stats['partial_exit_rate']:.4f}, closed_rate={stats['closed_rate']:.4f}"
            )

        lines.extend(
            [
                "",
                "## By Strategy Family",
            ]
        )
        for family, stats in sorted(payload["by_strategy_family"].items()):
            detail_pairs = ", ".join(
                f"{key}={int(value)}" for key, value in sorted(stats["final_exit_reasons"].items()) if int(value) > 0
            )
            if not detail_pairs:
                detail_pairs = "none"
            lines.append(
                f"- {family}: filled={int(stats['filled'])}, closed={int(stats['closed'])}, "
                f"target_exit_rate={stats['target_exit_rate']:.4f}, "
                f"forced_exit_rate={stats['forced_exit_rate']:.4f}, "
                f"information_failure_rate={stats['information_failure_rate']:.4f}, "
                f"time_failure_rate={stats['time_failure_rate']:.4f}, details={detail_pairs}"
            )

        lines.extend(
            [
                "",
                "## By Strategy Version",
            ]
        )
        for item in payload["version_comparison"]:
            detail_pairs = ", ".join(
                f"{key}={int(value)}"
                for key, value in sorted(item["unfilled_reason_details"].items())
                if int(value) > 0
            )
            if not detail_pairs:
                detail_pairs = "none"
            lines.append(
                f"- {item['version']}: matured={item['plans_matured']}, filled={item['fills_matched']}, "
                f"fill_rate={item['fill_rate']:.4f}, avg_slippage_bps={item['avg_slippage_bps']:.4f}, "
                f"avg_entry_latency_seconds={item['avg_entry_latency_seconds']:.2f}, "
                f"avg_entry_fee={item['avg_entry_fee']:.6f}, target_exit_ratio={item['target_exit_ratio']:.4f}, "
                f"forced_exit_ratio={item['forced_exit_ratio']:.4f}, "
                f"information_failure_ratio={item['information_failure_ratio']:.4f}, "
                f"time_failure_ratio={item['time_failure_ratio']:.4f}, details={detail_pairs}"
            )

        lines.extend(
            [
                "",
                "## Notes",
                "- execution_fills is the primary source for fill-rate, slippage, fee, and latency metrics.",
                "- legacy_outcomes is only used as a fallback for pre-fill-ledger historical coverage.",
                "- candle replay is used only to classify matured plans with no matched entry fill.",
                "- strategy_version comparison uses plan.strategy_version as the primary bucket key.",
                "",
            ]
        )
        file_path.write_text("\n".join(lines), encoding="utf-8")
        return str(file_path)

    def generate(self, *, symbol: str, days: int, write_report: bool = True) -> dict[str, Any]:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        lookback_days = max(1, int(days))
        plans = list(self.plan_repo.list_recent(symbol=symbol, timeframe="5m", days=lookback_days))

        actual_entries: dict[str, MatchedEntry] = {}
        _stage_counts: dict[str, int] = {}
        plan_stage_presence: dict[str, set[str]] = {}
        fills: list[ExecutionFill] = []
        plan_ids = [plan.plan_id for plan in plans]
        if self.fill_repo is not None and plan_ids:
            start_ts = now - timedelta(days=lookback_days)
            fills = self.fill_repo.list_for_plans(
                plan_ids=plan_ids,
                symbol=symbol,
                start_ts=start_ts,
                end_ts=now,
            )
            actual_entries, _stage_counts, plan_stage_presence = self._aggregate_actual_entries(fills)

        legacy_entries = self._match_legacy_outcomes(
            plans=plans,
            already_matched_plan_ids=set(actual_entries.keys()),
            outcomes=self.outcome_repo.list_recent(symbol=symbol, days=lookback_days),
        )
        matched_entries = dict(actual_entries)
        matched_entries.update(legacy_entries)
        plan_fill_map = self._group_fills_by_plan(fills)
        overall = self._build_bucket_payload(
            plans=plans,
            now=now,
            matched_entries=matched_entries,
            plan_stage_presence=plan_stage_presence,
            plan_fill_map=plan_fill_map,
        )

        by_strategy_version: dict[str, dict[str, Any]] = {}
        for version in sorted({str(plan.strategy_version or "unknown") for plan in plans}):
            version_plans = [plan for plan in plans if str(plan.strategy_version or "unknown") == version]
            by_strategy_version[version] = self._build_bucket_payload(
                plans=version_plans,
                now=now,
                matched_entries=matched_entries,
                plan_stage_presence=plan_stage_presence,
                plan_fill_map=plan_fill_map,
            )

        version_comparison = [
            {
                "version": version,
                "plans_matured": bucket["plans_matured"],
                "fills_matched": bucket["fills_matched"],
                "fill_rate": bucket["fill_rate"],
                "avg_slippage_bps": bucket["slippage_bps"]["avg"],
                "avg_entry_latency_seconds": bucket["entry_latency_seconds"]["avg"],
                "avg_entry_fee": bucket["fees"]["avg_entry_fee"],
                "target_exit_ratio": bucket["target_exit_ratio"],
                "forced_exit_ratio": bucket["forced_exit_ratio"],
                "information_failure_ratio": bucket["information_failure_ratio"],
                "time_failure_ratio": bucket["time_failure_ratio"],
                "unfilled_reason_details": dict(bucket["unfilled_reason_details"]),
            }
            for version, bucket in sorted(
                by_strategy_version.items(),
                key=lambda item: (
                    -int(item[1]["plans_matured"]),
                    -float(item[1]["fill_rate"]),
                    str(item[0]),
                ),
            )
        ]

        payload: dict[str, Any] = {
            "symbol": symbol,
            "days": lookback_days,
            "generated_at": now.isoformat(),
            "comparison_axis": "strategy_version",
            "versions_compared": len(by_strategy_version),
            **overall,
            "by_strategy_version": by_strategy_version,
            "version_comparison": version_comparison,
            "report_path": None,
        }
        if write_report:
            payload["report_path"] = self._write_report(payload=payload, now=now)
        return payload
