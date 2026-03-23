from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.core.config import Settings, get_settings
from app.core.enums import ExecutionFillStage
from app.services.strategy_v2_validation import ClosedTradeRecord, StrategyV2ValidationService


@dataclass(slots=True)
class _LineageTrade:
    plan: Any
    record: ClosedTradeRecord
    entry_anchor_ts: datetime
    exit_anchor_ts: datetime
    entry_bar_ts: datetime
    latency_bar_ts: datetime
    exit_bar_ts: datetime
    has_entry_fill: bool
    has_close_fill: bool
    has_partial_exit_fill: bool
    entry_anchor_source: str
    exit_anchor_source: str
    entry_bar_exists: bool
    latency_bar_exists: bool
    exit_bar_exists: bool
    path_coverage_ratio: float
    full_fill_path: bool
    complete_candle_path: bool


class StrategyV2StressReplayLineageService:
    _LATENCY_BARS = 1
    _CANDLE_TIMEFRAME = "5m"

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        plan_repo: Any | None = None,
        fill_repo: Any | None = None,
        candle_repo: Any | None = None,
    ):
        self.settings = settings or get_settings()
        self.plan_repo = plan_repo
        self.fill_repo = fill_repo
        self.candle_repo = candle_repo
        self._base = StrategyV2ValidationService(self.settings)

    @staticmethod
    def _normalize_ts(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _parse_ts(value: Any) -> datetime | None:
        if value in {None, ""}:
            return None
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @classmethod
    def _bar_start_5m(cls, ts: datetime) -> datetime:
        normalized = cls._normalize_ts(ts)
        assert normalized is not None
        minute = (normalized.minute // 5) * 5
        return normalized.replace(minute=minute, second=0, microsecond=0)

    @staticmethod
    def _ratio(numerator: int, denominator: int) -> float:
        if denominator <= 0:
            return 0.0
        return round(float(numerator) / float(denominator), 4)

    def _plans(self, *, symbol: str, version: str) -> list[Any]:
        if self.plan_repo is None:
            return []
        return self.plan_repo.list_recent(symbol=symbol, days=180)

    def _closed_trades(self, *, symbol: str, version: str) -> list[tuple[Any, ClosedTradeRecord]]:
        plans = self._plans(symbol=symbol, version=version)
        rows: list[tuple[Any, ClosedTradeRecord]] = []
        for plan in plans:
            record = self._base._closed_trade(plan, symbol=symbol, version=version)
            if record is None:
                continue
            rows.append((plan, record))
        rows.sort(key=lambda item: item[1].closed_ts)
        return rows

    def _fill_map(self, plans: list[Any]) -> dict[str, list[Any]]:
        if self.fill_repo is None:
            return {}
        plan_ids = [str(getattr(plan, "plan_id", "") or "") for plan in plans if getattr(plan, "plan_id", None)]
        if not plan_ids:
            return {}
        fills = self.fill_repo.list_for_plans(plan_ids=plan_ids)
        out: dict[str, list[Any]] = {}
        for fill in fills:
            out.setdefault(str(getattr(fill, "plan_id", "") or ""), []).append(fill)
        return out

    @staticmethod
    def _first_stage_fill(fills: list[Any], stage: ExecutionFillStage) -> Any | None:
        matched = [fill for fill in fills if str(getattr(fill, "stage", "")) == stage.value]
        if not matched:
            return None
        matched.sort(key=lambda fill: getattr(fill, "fill_ts"))
        return matched[0]

    def _entry_anchor(self, *, plan: Any, record: ClosedTradeRecord, fills: list[Any]) -> tuple[datetime, str]:
        entry_fill = self._first_stage_fill(fills, ExecutionFillStage.ENTRY)
        if entry_fill is not None:
            fill_ts = self._normalize_ts(getattr(entry_fill, "fill_ts", None))
            if fill_ts is not None:
                return fill_ts, "execution_entry_fill"
        valid_from = self._normalize_ts(getattr(plan, "valid_from", None))
        if valid_from is not None:
            return valid_from, "plan_valid_from"
        return record.closed_ts, "trade_closed_ts_fallback"

    def _exit_anchor(self, *, record: ClosedTradeRecord, fills: list[Any]) -> tuple[datetime, str]:
        close_fill = self._first_stage_fill(fills, ExecutionFillStage.CLOSED)
        if close_fill is not None:
            fill_ts = self._normalize_ts(getattr(close_fill, "fill_ts", None))
            if fill_ts is not None:
                return fill_ts, "execution_closed_fill"
        return record.closed_ts, "plan_final_exit_ts"

    def _candle_timestamps(self, *, symbol: str, start_ts: datetime, end_ts: datetime) -> set[datetime]:
        if self.candle_repo is None:
            return set()
        candles = self.candle_repo.list_range(
            symbol=symbol,
            timeframe=self._CANDLE_TIMEFRAME,
            start_ts=start_ts,
            end_ts=end_ts,
        )
        out: set[datetime] = set()
        for candle in candles:
            ts = self._normalize_ts(getattr(candle, "ts", None))
            if ts is not None:
                out.add(ts)
        return out

    @staticmethod
    def _expected_bar_count(start_ts: datetime, end_ts: datetime) -> int:
        if end_ts < start_ts:
            return 0
        delta_minutes = int((end_ts - start_ts).total_seconds() // 60)
        return int(delta_minutes // 5) + 1

    def _trade_lineage(self, *, plan: Any, record: ClosedTradeRecord, fills: list[Any]) -> _LineageTrade:
        entry_fill = self._first_stage_fill(fills, ExecutionFillStage.ENTRY)
        close_fill = self._first_stage_fill(fills, ExecutionFillStage.CLOSED)
        partial_exit_fill = self._first_stage_fill(fills, ExecutionFillStage.PARTIAL_EXIT)
        entry_anchor_ts, entry_anchor_source = self._entry_anchor(plan=plan, record=record, fills=fills)
        exit_anchor_ts, exit_anchor_source = self._exit_anchor(record=record, fills=fills)
        entry_bar = self._bar_start_5m(entry_anchor_ts)
        latency_bar = entry_bar + timedelta(minutes=5 * self._LATENCY_BARS)
        exit_bar = self._bar_start_5m(exit_anchor_ts)
        candle_start = min(entry_bar, exit_bar)
        candle_end = max(entry_bar, exit_bar)
        timestamps = self._candle_timestamps(symbol=str(plan.symbol), start_ts=candle_start, end_ts=candle_end)
        expected_bars = self._expected_bar_count(candle_start, candle_end)
        actual_bars = len(timestamps)
        path_coverage_ratio = 0.0 if expected_bars <= 0 else round(min(1.0, float(actual_bars) / float(expected_bars)), 4)
        complete_candle_path = (
            expected_bars > 0
            and path_coverage_ratio >= float(self.settings.stress_replay_lineage_min_candle_path_coverage)
            and entry_bar in timestamps
            and latency_bar in timestamps
            and exit_bar in timestamps
        )
        return _LineageTrade(
            plan=plan,
            record=record,
            entry_anchor_ts=entry_anchor_ts,
            exit_anchor_ts=exit_anchor_ts,
            entry_bar_ts=entry_bar,
            latency_bar_ts=latency_bar,
            exit_bar_ts=exit_bar,
            has_entry_fill=entry_fill is not None,
            has_close_fill=close_fill is not None,
            has_partial_exit_fill=partial_exit_fill is not None,
            entry_anchor_source=entry_anchor_source,
            exit_anchor_source=exit_anchor_source,
            entry_bar_exists=entry_bar in timestamps,
            latency_bar_exists=latency_bar in timestamps,
            exit_bar_exists=exit_bar in timestamps,
            path_coverage_ratio=path_coverage_ratio,
            full_fill_path=entry_fill is not None and close_fill is not None,
            complete_candle_path=complete_candle_path,
        )

    def trade_rows(self, *, symbol: str, version: str) -> list[dict[str, Any]]:
        rows = self._closed_trades(symbol=symbol, version=version)
        plans = [plan for plan, _ in rows]
        fills_map = self._fill_map(plans)
        trades = [
            self._trade_lineage(plan=plan, record=record, fills=fills_map.get(plan.plan_id, []))
            for plan, record in rows
        ]
        payloads: list[dict[str, Any]] = []
        for trade in trades:
            validity = dict(getattr(trade.plan, "validity", {}) or {})
            payloads.append(
                {
                    "plan_id": str(getattr(trade.plan, "plan_id", "") or ""),
                    "zone_id": str(getattr(trade.plan, "zone_id", "") or ""),
                    "symbol": str(getattr(trade.plan, "symbol", "") or ""),
                    "direction": str(getattr(trade.plan, "direction", "") or ""),
                    "strategy_family": str(validity.get("strategy_family") or trade.record.strategy_family or ""),
                    "strategy_grade": str(validity.get("strategy_grade") or trade.record.strategy_grade or ""),
                    "regime": str(validity.get("regime", "range") or "range").lower(),
                    "closed_ts": trade.record.closed_ts.isoformat(),
                    "entry_anchor_ts": trade.entry_anchor_ts.isoformat(),
                    "exit_anchor_ts": trade.exit_anchor_ts.isoformat(),
                    "entry_bar_ts": trade.entry_bar_ts.isoformat(),
                    "latency_bar_ts": trade.latency_bar_ts.isoformat(),
                    "exit_bar_ts": trade.exit_bar_ts.isoformat(),
                    "entry_anchor_source": trade.entry_anchor_source,
                    "exit_anchor_source": trade.exit_anchor_source,
                    "has_entry_fill": trade.has_entry_fill,
                    "has_close_fill": trade.has_close_fill,
                    "has_partial_exit_fill": trade.has_partial_exit_fill,
                    "entry_bar_exists": trade.entry_bar_exists,
                    "latency_bar_exists": trade.latency_bar_exists,
                    "exit_bar_exists": trade.exit_bar_exists,
                    "path_coverage_ratio": float(trade.path_coverage_ratio),
                    "full_fill_path": trade.full_fill_path,
                    "complete_candle_path": trade.complete_candle_path,
                    "final_exit_realized_r": float(trade.record.realized_r),
                    "final_exit_reason": trade.record.exit_reason,
                    "final_exit_held_bars": int(trade.record.held_bars),
                    "strategy_version": trade.record.strategy_version,
                }
            )
        return payloads

    @staticmethod
    def _avg(values: list[float]) -> float:
        if not values:
            return 0.0
        return round(sum(float(v) for v in values) / len(values), 4)

    def _write_report(self, *, payload: dict[str, Any], now: datetime) -> str:
        out_dir = Path(self.settings.validation_report_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        file_path = out_dir / (
            f"strategy_v2_stress_replay_lineage_{payload['symbol']}_{payload['version']}_{now.strftime('%Y%m%dT%H%M%SZ')}.md"
        )
        fill_path = dict(payload.get("fill_path") or {})
        candle_path = dict(payload.get("candle_path") or {})
        coverage = dict(payload.get("coverage") or {})
        lines = [
            f"# Strategy v2 Stress Replay Lineage: {payload['symbol']}",
            "",
            f"- generated_at_utc: {payload['generated_at']}",
            f"- strategy_version: {payload['version']}",
            f"- available: {payload['available']}",
            f"- runtime_inputs_ready: {payload['runtime_inputs_ready']}",
            f"- reason: {payload['reason']}",
            f"- evaluation_basis: {payload.get('evaluation_basis', 'closed_v2_plans + execution_fills + 5m_candles')}",
            "",
            "## Coverage",
            f"- execution_fill_coverage: {float(coverage.get('execution_fill_coverage', 0.0)):.4f}",
            f"- latency_candle_coverage: {float(coverage.get('latency_candle_coverage', 0.0)):.4f}",
            f"- candle_path_coverage: {float(coverage.get('candle_path_coverage', 0.0)):.4f}",
            f"- estimate_only_share: {float(coverage.get('estimate_only_share', 0.0)):.4f}",
            "",
            "## Fill Path",
            f"- entry_fill_coverage: {float(fill_path.get('entry_fill_coverage', 0.0)):.4f}",
            f"- close_fill_coverage: {float(fill_path.get('close_fill_coverage', 0.0)):.4f}",
            f"- partial_exit_fill_coverage: {float(fill_path.get('partial_exit_fill_coverage', 0.0)):.4f}",
            f"- full_fill_path_coverage: {float(fill_path.get('full_fill_path_coverage', 0.0)):.4f}",
            f"- entry_anchor_sources: {fill_path.get('entry_anchor_sources', {})}",
            f"- exit_anchor_sources: {fill_path.get('exit_anchor_sources', {})}",
            "",
            "## Candle Path",
            f"- entry_bar_coverage: {float(candle_path.get('entry_bar_coverage', 0.0)):.4f}",
            f"- latency_bar_coverage: {float(candle_path.get('latency_bar_coverage', 0.0)):.4f}",
            f"- exit_bar_coverage: {float(candle_path.get('exit_bar_coverage', 0.0)):.4f}",
            f"- avg_path_coverage_ratio: {float(candle_path.get('avg_path_coverage_ratio', 0.0)):.4f}",
            f"- min_path_coverage_ratio: {float(candle_path.get('min_path_coverage_ratio', 0.0)):.4f}",
            "",
            "## Gap Counts",
            f"- gaps: {payload.get('gap_counts', {})}",
            "",
            "## Contract",
            f"- lineage_contract: {payload.get('lineage_contract', {})}",
            "",
            "## Blockers",
        ]
        for item in payload.get("blocked_by", []):
            lines.append(f"- {item}")
        lines.extend(["", "## Next Steps"])
        for item in payload.get("next_steps", []):
            lines.append(f"- {item}")
        lines.extend(
            [
                "",
                "## Notes",
                "- This artifact defines the runtime lineage inputs required before full replay should replace the current approximation.",
                "- It does not execute replay; it only verifies input completeness and anchor quality.",
                "",
            ]
        )
        file_path.write_text("\n".join(lines), encoding="utf-8")
        return str(file_path)

    def generate(
        self,
        *,
        symbol: str,
        version: str,
        write_report: bool = True,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        rows = self._closed_trades(symbol=symbol, version=version)
        plans = [plan for plan, _ in rows]
        fills_map = self._fill_map(plans)
        trades = [
            self._trade_lineage(plan=plan, record=record, fills=fills_map.get(plan.plan_id, []))
            for plan, record in rows
        ]
        eligible_closed_trades = len(trades)

        if eligible_closed_trades <= 0:
            payload = {
                "schema_version": "strategy_v2_stress_replay_lineage_v1",
                "symbol": symbol,
                "version": version,
                "generated_at": now.isoformat(),
                "available": False,
                "runtime_inputs_ready": False,
                "reason": "no_closed_v2_trades",
                "evaluation_basis": "closed_v2_plans + execution_fills + 5m_candles",
                "sample_counts": {"eligible_closed_trades": 0},
                "coverage": {
                    "execution_fill_coverage": 0.0,
                    "latency_candle_coverage": 0.0,
                    "candle_path_coverage": 0.0,
                    "estimate_only_share": 0.0,
                },
                "fill_path": {},
                "candle_path": {},
                "gap_counts": {},
                "lineage_contract": {
                    "required_fill_stages": [ExecutionFillStage.ENTRY.value, ExecutionFillStage.CLOSED.value],
                    "optional_fill_stages": [ExecutionFillStage.PARTIAL_EXIT.value],
                    "required_plan_validity_fields": ["final_exit_ts", "final_exit_realized_r", "final_exit_reason"],
                    "candle_timeframe": self._CANDLE_TIMEFRAME,
                    "required_candle_nodes": ["entry_bar", "latency_plus_1_bar", "exit_bar"],
                    "min_execution_fill_coverage": float(self.settings.stress_replay_lineage_min_execution_fill_coverage),
                    "min_latency_candle_coverage": float(self.settings.stress_replay_lineage_min_latency_candle_coverage),
                    "min_candle_path_coverage": float(self.settings.stress_replay_lineage_min_candle_path_coverage),
                },
                "blocked_by": ["no_closed_v2_trades"],
                "next_steps": ["accumulate closed v2 trades before evaluating replay lineage"],
                "report_path": None,
            }
            if write_report:
                payload["report_path"] = self._write_report(payload=payload, now=now)
            return payload

        entry_fill_trades = sum(1 for trade in trades if trade.has_entry_fill)
        close_fill_trades = sum(1 for trade in trades if trade.has_close_fill)
        partial_exit_trades = sum(1 for trade in trades if trade.has_partial_exit_fill)
        full_fill_path_trades = sum(1 for trade in trades if trade.full_fill_path)
        entry_bar_trades = sum(1 for trade in trades if trade.entry_bar_exists)
        latency_bar_trades = sum(1 for trade in trades if trade.latency_bar_exists)
        exit_bar_trades = sum(1 for trade in trades if trade.exit_bar_exists)
        complete_candle_path_trades = sum(1 for trade in trades if trade.complete_candle_path)
        estimate_only_trades = eligible_closed_trades - full_fill_path_trades
        path_ratios = [float(trade.path_coverage_ratio) for trade in trades]

        entry_anchor_sources: dict[str, int] = {}
        exit_anchor_sources: dict[str, int] = {}
        for trade in trades:
            entry_anchor_sources[trade.entry_anchor_source] = int(entry_anchor_sources.get(trade.entry_anchor_source, 0)) + 1
            exit_anchor_sources[trade.exit_anchor_source] = int(exit_anchor_sources.get(trade.exit_anchor_source, 0)) + 1

        coverage = {
            "execution_fill_coverage": self._ratio(full_fill_path_trades, eligible_closed_trades),
            "latency_candle_coverage": self._ratio(latency_bar_trades, eligible_closed_trades),
            "candle_path_coverage": self._ratio(complete_candle_path_trades, eligible_closed_trades),
            "estimate_only_share": self._ratio(estimate_only_trades, eligible_closed_trades),
        }
        fill_path = {
            "entry_fill_coverage": self._ratio(entry_fill_trades, eligible_closed_trades),
            "close_fill_coverage": self._ratio(close_fill_trades, eligible_closed_trades),
            "partial_exit_fill_coverage": self._ratio(partial_exit_trades, eligible_closed_trades),
            "full_fill_path_coverage": self._ratio(full_fill_path_trades, eligible_closed_trades),
            "entry_anchor_sources": dict(sorted(entry_anchor_sources.items())),
            "exit_anchor_sources": dict(sorted(exit_anchor_sources.items())),
        }
        candle_path = {
            "entry_bar_coverage": self._ratio(entry_bar_trades, eligible_closed_trades),
            "latency_bar_coverage": self._ratio(latency_bar_trades, eligible_closed_trades),
            "exit_bar_coverage": self._ratio(exit_bar_trades, eligible_closed_trades),
            "avg_path_coverage_ratio": self._avg(path_ratios),
            "min_path_coverage_ratio": round(min(path_ratios), 4) if path_ratios else 0.0,
        }
        gap_counts = {
            "missing_entry_fill": eligible_closed_trades - entry_fill_trades,
            "missing_close_fill": eligible_closed_trades - close_fill_trades,
            "missing_latency_bar": eligible_closed_trades - latency_bar_trades,
            "missing_exit_bar": eligible_closed_trades - exit_bar_trades,
            "candle_path_below_threshold": eligible_closed_trades - complete_candle_path_trades,
        }
        blocked_by: list[str] = []
        if coverage["execution_fill_coverage"] < float(self.settings.stress_replay_lineage_min_execution_fill_coverage):
            blocked_by.append("execution_fill_coverage_below_threshold")
        if coverage["latency_candle_coverage"] < float(self.settings.stress_replay_lineage_min_latency_candle_coverage):
            blocked_by.append("latency_candle_coverage_below_threshold")
        if coverage["candle_path_coverage"] < float(self.settings.stress_replay_lineage_min_candle_path_coverage):
            blocked_by.append("candle_path_coverage_below_threshold")

        next_steps: list[str] = []
        if gap_counts["missing_entry_fill"] > 0 or gap_counts["missing_close_fill"] > 0:
            next_steps.append("backfill execution fill writers so entry/closed stages exist for more closed v2 trades")
        if gap_counts["missing_latency_bar"] > 0 or gap_counts["missing_exit_bar"] > 0:
            next_steps.append("improve 5m candle retention around entry/exit anchors for replay candidates")
        if gap_counts["candle_path_below_threshold"] > 0:
            next_steps.append("add contiguous candle-path validation before marking replay lineage as ready")
        if not next_steps:
            next_steps.append("runtime lineage is ready enough to prototype replay runner inputs")

        runtime_inputs_ready = not blocked_by
        payload = {
            "schema_version": "strategy_v2_stress_replay_lineage_v1",
            "symbol": symbol,
            "version": version,
            "generated_at": now.isoformat(),
            "available": True,
            "runtime_inputs_ready": runtime_inputs_ready,
            "reason": "runtime_lineage_ready" if runtime_inputs_ready else "runtime_lineage_incomplete",
            "evaluation_basis": "closed_v2_plans + execution_fills + 5m_candles",
            "sample_counts": {
                "eligible_closed_trades": eligible_closed_trades,
                "entry_fill_trades": entry_fill_trades,
                "close_fill_trades": close_fill_trades,
                "partial_exit_trades": partial_exit_trades,
                "full_fill_path_trades": full_fill_path_trades,
                "entry_bar_trades": entry_bar_trades,
                "latency_bar_trades": latency_bar_trades,
                "exit_bar_trades": exit_bar_trades,
                "complete_candle_path_trades": complete_candle_path_trades,
                "estimate_only_trades": estimate_only_trades,
            },
            "coverage": coverage,
            "fill_path": fill_path,
            "candle_path": candle_path,
            "gap_counts": gap_counts,
            "lineage_contract": {
                "required_fill_stages": [ExecutionFillStage.ENTRY.value, ExecutionFillStage.CLOSED.value],
                "optional_fill_stages": [ExecutionFillStage.PARTIAL_EXIT.value],
                "required_plan_validity_fields": ["final_exit_ts", "final_exit_realized_r", "final_exit_reason"],
                "candle_timeframe": self._CANDLE_TIMEFRAME,
                "required_candle_nodes": ["entry_bar", "latency_plus_1_bar", "exit_bar"],
                "min_execution_fill_coverage": float(self.settings.stress_replay_lineage_min_execution_fill_coverage),
                "min_latency_candle_coverage": float(self.settings.stress_replay_lineage_min_latency_candle_coverage),
                "min_candle_path_coverage": float(self.settings.stress_replay_lineage_min_candle_path_coverage),
            },
            "blocked_by": blocked_by,
            "next_steps": next_steps,
            "report_path": None,
        }
        if write_report:
            payload["report_path"] = self._write_report(payload=payload, now=now)
        return payload
