from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from math import isfinite
from pathlib import Path
from typing import Any

from app.core.enums import ExecutionMode
from app.services.family_rollout import RolloutPolicyBootstrap


@dataclass(frozen=True, slots=True)
class ReplayValidationEvidence:
    approval_usable: bool
    reason_code: str
    message: str
    metrics: dict[str, Any]
    source: dict[str, Any]
    reason_codes: tuple[str, ...]
    failures: tuple[dict[str, Any], ...]


class UsdtProxyReplayValidationBridge:
    """Promotes recent execution-faithful replay proof into live approval metrics."""

    _SESSION_IMPULSE_RETEST_FAMILY = "session_impulse_retest"
    _SWEEP_REVERSAL_FAMILY = "sweep_reversal"
    _SUPPORTED_FAMILIES = {_SESSION_IMPULSE_RETEST_FAMILY, _SWEEP_REVERSAL_FAMILY}
    _SUPPORTED_MODES = {ExecutionMode.MICRO_LIVE.value, ExecutionMode.LIVE.value}

    def __init__(self, settings: Any):
        self.settings = settings
        self._json_cache: dict[Path, tuple[int, int, dict[str, Any]]] = {}

    def apply_to_metrics(
        self,
        metrics: dict[str, Any],
        *,
        symbol: str,
        family: str,
        requested_mode: str,
        entry_model: str = "",
    ) -> dict[str, Any]:
        if not self._enabled_for(family=family, requested_mode=requested_mode):
            return metrics

        evidence = self.evaluate(symbol=symbol, family=family, entry_model=entry_model)
        if not evidence.approval_usable:
            enriched = dict(metrics)
            enriched["validation_bridge"] = self._evidence_payload(evidence, applied=False)
            return enriched

        recommendation = str(metrics.get("recommendation") or "do-not-deploy")
        sample_size = max(
            self._safe_int(metrics.get("sample_size")),
            self._safe_int(metrics.get("trade_count")),
            self._safe_int(metrics.get("closed_trades")),
        )
        min_live_sample = self._safe_int(getattr(self.settings, "min_zone_sample_for_full_confidence", 30), default=30)
        if recommendation != "do-not-deploy":
            enriched = dict(metrics)
            enriched["validation_bridge"] = self._evidence_payload(
                evidence,
                applied=False,
                reason="runtime_metrics_already_usable",
            )
            return enriched
        if sample_size >= max(1, min_live_sample):
            enriched = dict(metrics)
            enriched["validation_bridge"] = self._evidence_payload(
                evidence,
                applied=False,
                reason="runtime_validation_sample_available",
            )
            return enriched

        bridge_metrics = dict(evidence.metrics)
        enriched = dict(metrics)
        enriched.update(
            {
                "win_rate": bridge_metrics.get("win_rate", metrics.get("win_rate")),
                "ev": bridge_metrics.get("ev_r", metrics.get("ev")),
                "ev_r": bridge_metrics.get("ev_r", metrics.get("ev_r")),
                "expectancy_r": bridge_metrics.get("ev_r", metrics.get("expectancy_r")),
                "total_r": bridge_metrics.get("total_r", metrics.get("total_r")),
                "sample_size": bridge_metrics.get("closed_trades", metrics.get("sample_size")),
                "trade_count": bridge_metrics.get("closed_trades", metrics.get("trade_count")),
                "closed_trades": bridge_metrics.get("closed_trades", metrics.get("closed_trades")),
                "total_score": bridge_metrics.get("total_score", metrics.get("total_score")),
                "grade": bridge_metrics.get("grade", metrics.get("grade")),
                "recommendation": bridge_metrics.get("recommendation", metrics.get("recommendation")),
                "max_drawdown_pct": bridge_metrics.get("max_portfolio_drawdown_pct", metrics.get("max_drawdown_pct")),
                "validation_source": str(evidence.source.get("bridge_source") or "usdt_proxy_replay_bridge"),
                "validation_bridge": self._evidence_payload(evidence, applied=True),
            }
        )
        reason_codes = [
            str(item)
            for item in list(metrics.get("reason_codes") or metrics.get("reasons") or [])
            if str(item).strip()
        ]
        for code in evidence.reason_codes:
            if code not in reason_codes:
                reason_codes.append(code)
        enriched["reason_codes"] = reason_codes
        return enriched

    def evaluate(
        self,
        *,
        symbol: str,
        family: str = _SESSION_IMPULSE_RETEST_FAMILY,
        entry_model: str = "",
    ) -> ReplayValidationEvidence:
        if str(family or "").strip().lower() == self._SWEEP_REVERSAL_FAMILY:
            return self._evaluate_historical_walk_forward_sweep_reversal(symbol=symbol, entry_model=entry_model)
        return self._evaluate_usdt_proxy(symbol=symbol)

    def _evaluate_usdt_proxy(self, *, symbol: str) -> ReplayValidationEvidence:
        normalized_symbol = self._normalize_symbol(symbol)
        failures: list[dict[str, Any]] = []

        backtest = self._latest_backtest_entry(normalized_symbol)
        if backtest is None:
            return ReplayValidationEvidence(
                approval_usable=False,
                reason_code="replay_validation_backtest_missing",
                message="No recent USDT proxy replay backtest entry exists for this symbol.",
                metrics={},
                source={},
                reason_codes=("replay_validation_backtest_missing",),
                failures=(),
            )
        backtest_path, backtest_payload, entry = backtest
        summary = dict(entry.get("summary") or {})
        closed = self._safe_int(summary.get("closed") or summary.get("closed_trades") or summary.get("trade_count"))
        ev_r = self._safe_float(summary.get("ev_r") or summary.get("expectancy_r"))
        win_rate = self._safe_float(summary.get("win_rate"))
        total_r = self._safe_float(summary.get("total_r"))
        days = self._safe_int(backtest_payload.get("days"))
        decision = str(summary.get("decision") or "").upper()

        min_days = self._safe_int(getattr(self.settings, "auto_trading_replay_validation_bridge_min_days", 1000), default=1000)
        min_trades = self._safe_int(getattr(self.settings, "auto_trading_replay_validation_bridge_min_trades", 80), default=80)
        min_ev_r = self._safe_float(getattr(self.settings, "auto_trading_replay_validation_bridge_min_ev_r", 0.10), default=0.10)
        min_win_rate = self._safe_float(getattr(self.settings, "auto_trading_replay_validation_bridge_min_win_rate", 0.40), default=0.40)
        min_score = self._safe_float(getattr(self.settings, "auto_trading_replay_validation_bridge_min_score", 70.0), default=70.0)

        if decision != "PASS":
            failures.append({"code": "replay_validation_decision_not_pass", "value": decision or "missing", "required": "PASS"})
        if days < min_days:
            failures.append({"code": "replay_validation_days_below_floor", "value": days, "required": min_days})
        if closed < min_trades:
            failures.append({"code": "replay_validation_trades_below_floor", "value": closed, "required": min_trades})
        if ev_r < min_ev_r:
            failures.append({"code": "replay_validation_ev_below_floor", "value": ev_r, "required": min_ev_r})
        if win_rate < min_win_rate:
            failures.append({"code": "replay_validation_win_rate_below_floor", "value": win_rate, "required": min_win_rate})

        portfolio = self._latest_portfolio_evidence(normalized_symbol)
        if portfolio is None:
            failures.append({"code": "replay_validation_portfolio_replay_missing"})
            portfolio_metrics: dict[str, Any] = {}
            portfolio_source: dict[str, Any] = {}
        else:
            portfolio_metrics, portfolio_source, portfolio_failures = portfolio
            failures.extend(portfolio_failures)

        total_score = self._score(closed=closed, ev_r=ev_r, win_rate=win_rate)
        if total_score < min_score:
            failures.append({"code": "replay_validation_score_below_floor", "value": total_score, "required": min_score})

        base_metrics = {
            "closed_trades": closed,
            "ev_r": round(ev_r, 4),
            "win_rate": round(win_rate, 4),
            "total_r": round(total_r, 4),
            "days": days,
            "total_score": total_score,
            **portfolio_metrics,
        }
        source = {
            "backtest_report": str(backtest_path),
            "generated_at": str(backtest_payload.get("generated_at") or ""),
            "proxy_symbol": str(entry.get("proxy_symbol") or ""),
            "canonical_symbol": str(entry.get("canonical_symbol") or normalized_symbol),
            **portfolio_source,
        }

        if failures:
            return ReplayValidationEvidence(
                approval_usable=False,
                reason_code=str(failures[0].get("code") or "replay_validation_not_usable"),
                message="USDT proxy replay evidence exists but does not clear the live validation bridge floors.",
                metrics=base_metrics,
                source=source,
                reason_codes=tuple(str(item.get("code") or "") for item in failures if str(item.get("code") or "").strip()),
                failures=tuple(failures),
            )

        grade, recommendation = self._label(total_score)
        return ReplayValidationEvidence(
            approval_usable=True,
            reason_code="replay_validation_bridge_approval_usable",
            message="Recent 3-year USDT proxy replay clears the live validation bridge floors.",
            metrics={**base_metrics, "grade": grade, "recommendation": recommendation},
            source={**source, "bridge_source": "usdt_proxy_replay_bridge"},
            reason_codes=(
                "replay_validation_bridge_approval_usable",
                "usdt_proxy_3y_strategy_pass",
                "usdt_proxy_portfolio_replay_pass",
            ),
            failures=(),
        )

    def _enabled_for(self, *, family: str, requested_mode: str) -> bool:
        if not bool(getattr(self.settings, "auto_trading_replay_validation_bridge_enabled", True)):
            return False
        normalized_family = str(family or "").strip().lower()
        if normalized_family == self._SWEEP_REVERSAL_FAMILY and not bool(
            getattr(self.settings, "auto_trading_replay_validation_bridge_sweep_reversal_enabled", True)
        ):
            return False
        return normalized_family in self._SUPPORTED_FAMILIES and str(requested_mode or "") in self._SUPPORTED_MODES

    def _evaluate_historical_walk_forward_sweep_reversal(
        self,
        *,
        symbol: str,
        entry_model: str = "",
    ) -> ReplayValidationEvidence:
        normalized_symbol = self._normalize_symbol(symbol)
        normalized_entry_model = str(entry_model or "").strip().upper()
        allowed_entry_models = self._csv_set(
            getattr(self.settings, "auto_trading_replay_validation_bridge_sweep_reversal_entry_models", "LIMIT"),
            upper=True,
        ) or {"LIMIT"}
        if not normalized_entry_model or normalized_entry_model not in allowed_entry_models:
            return ReplayValidationEvidence(
                approval_usable=False,
                reason_code="replay_validation_entry_model_not_bridgeable",
                message="sweep_reversal replay bridge only applies to explicitly allowed active-contract entry models.",
                metrics={},
                source={
                    "bridge_source": "historical_walk_forward_sweep_reversal_bridge",
                    "entry_model": normalized_entry_model,
                    "allowed_entry_models": sorted(allowed_entry_models),
                },
                reason_codes=("replay_validation_entry_model_not_bridgeable",),
                failures=(
                    {
                        "code": "replay_validation_entry_model_not_bridgeable",
                        "value": normalized_entry_model,
                        "allowed": sorted(allowed_entry_models),
                    },
                ),
            )

        cache_path = self._historical_walk_forward_cache_path()
        payload = self._load_json(cache_path)
        if not payload or self._is_stale(payload, cache_path):
            return ReplayValidationEvidence(
                approval_usable=False,
                reason_code="historical_walk_forward_cache_missing_or_stale",
                message="No fresh historical walk-forward active-contract cache exists for sweep_reversal.",
                metrics={},
                source={
                    "bridge_source": "historical_walk_forward_sweep_reversal_bridge",
                    "cache_file": str(cache_path),
                },
                reason_codes=("historical_walk_forward_cache_missing_or_stale",),
                failures=({"code": "historical_walk_forward_cache_missing_or_stale", "cache_file": str(cache_path)},),
            )

        simulation_start = self._parse_ts(payload.get("simulation_start_ts"))
        simulation_end = self._parse_ts(payload.get("simulation_end_ts"))
        days = 0
        if simulation_start is not None and simulation_end is not None:
            days = max(0, int((simulation_end - simulation_start).total_seconds() // 86400))

        allowed_sessions = self._historical_walk_forward_allowed_sessions()
        directions = self._direction_contract_for_symbol(normalized_symbol)
        rows: list[dict[str, Any]] = []
        for raw_row in list(payload.get("trade_rows") or []):
            if not isinstance(raw_row, dict):
                continue
            row = dict(raw_row)
            family = str(row.get("strategy_family") or "").strip().lower()
            generated_ts = self._parse_ts(row.get("generated_ts")) or self._parse_ts(row.get("closed_ts"))
            generated_session = self._session_bucket(generated_ts)
            if str(row.get("symbol") or "").strip().upper() != normalized_symbol:
                continue
            if family != self._SWEEP_REVERSAL_FAMILY:
                continue
            if str(row.get("entry_model") or "").strip().upper() not in allowed_entry_models:
                continue
            if directions and str(row.get("direction") or "").strip().upper() not in directions:
                continue
            if allowed_sessions and generated_session not in allowed_sessions:
                continue
            rows.append(row)

        structure_failure_stress_r = self._safe_float(
            getattr(
                self.settings,
                "auto_trading_replay_validation_bridge_sweep_reversal_structure_failure_stress_r",
                -1.0,
            ),
            default=-1.0,
        )
        metrics = self._historical_walk_forward_metrics(
            rows,
            structure_failure_stress_r=structure_failure_stress_r,
        )
        closed = self._safe_int(metrics.get("closed_trades"))
        ev_r = self._safe_float(metrics.get("ev_r"))
        win_rate = self._safe_float(metrics.get("win_rate"))
        total_score = self._score(closed=closed, ev_r=ev_r, win_rate=win_rate)

        min_days = self._safe_int(
            getattr(self.settings, "auto_trading_replay_validation_bridge_sweep_reversal_min_days", 700),
            default=700,
        )
        min_trades = self._safe_int(
            getattr(self.settings, "auto_trading_replay_validation_bridge_sweep_reversal_min_trades", 120),
            default=120,
        )
        min_ev_r = self._safe_float(
            getattr(self.settings, "auto_trading_replay_validation_bridge_sweep_reversal_min_ev_r", 0.20),
            default=0.20,
        )
        min_ev_lower_r = self._safe_float(
            getattr(self.settings, "auto_trading_replay_validation_bridge_sweep_reversal_min_ev_lower_r", 0.0),
            default=0.0,
        )
        min_win_rate = self._safe_float(
            getattr(self.settings, "auto_trading_replay_validation_bridge_sweep_reversal_min_win_rate", 0.48),
            default=0.48,
        )
        max_stop_loss_share = self._safe_float(
            getattr(self.settings, "auto_trading_replay_validation_bridge_sweep_reversal_max_stop_loss_share", 0.45),
            default=0.45,
        )
        max_drawdown_r = self._safe_float(
            getattr(self.settings, "auto_trading_replay_validation_bridge_sweep_reversal_max_drawdown_r", 4.5),
            default=4.5,
        )
        min_score = self._safe_float(getattr(self.settings, "auto_trading_replay_validation_bridge_min_score", 70.0), default=70.0)

        failures: list[dict[str, Any]] = []
        if days < min_days:
            failures.append({"code": "historical_walk_forward_days_below_floor", "value": days, "required": min_days})
        if closed < min_trades:
            failures.append({"code": "historical_walk_forward_trades_below_floor", "value": closed, "required": min_trades})
        if ev_r < min_ev_r:
            failures.append({"code": "historical_walk_forward_ev_below_floor", "value": ev_r, "required": min_ev_r})
        if self._safe_float(metrics.get("ev_r_lower_95")) < min_ev_lower_r:
            failures.append(
                {
                    "code": "historical_walk_forward_ev_lower_95_below_floor",
                    "value": self._safe_float(metrics.get("ev_r_lower_95")),
                    "required": min_ev_lower_r,
                }
            )
        if win_rate < min_win_rate:
            failures.append({"code": "historical_walk_forward_win_rate_below_floor", "value": win_rate, "required": min_win_rate})
        if self._safe_float(metrics.get("stop_loss_share")) > max_stop_loss_share:
            failures.append(
                {
                    "code": "historical_walk_forward_stop_loss_share_above_cap",
                    "value": self._safe_float(metrics.get("stop_loss_share")),
                    "required": max_stop_loss_share,
                }
            )
        if self._safe_float(metrics.get("max_drawdown_r")) > max_drawdown_r:
            failures.append(
                {
                    "code": "historical_walk_forward_drawdown_above_cap",
                    "value": self._safe_float(metrics.get("max_drawdown_r")),
                    "required": max_drawdown_r,
                }
            )
        if total_score < min_score:
            failures.append({"code": "historical_walk_forward_score_below_floor", "value": total_score, "required": min_score})

        base_metrics = {
            **metrics,
            "days": days,
            "total_score": total_score,
        }
        source = {
            "bridge_source": "historical_walk_forward_sweep_reversal_bridge",
            "cache_file": str(cache_path),
            "generated_at": str(payload.get("generated_at") or ""),
            "simulation_start_ts": str(payload.get("simulation_start_ts") or ""),
            "simulation_end_ts": str(payload.get("simulation_end_ts") or ""),
            "symbol": normalized_symbol,
            "family": self._SWEEP_REVERSAL_FAMILY,
            "entry_models": sorted(allowed_entry_models),
            "sessions": sorted(allowed_sessions),
            "directions": sorted(directions),
            "structure_failure_stress_r": structure_failure_stress_r,
        }
        if failures:
            return ReplayValidationEvidence(
                approval_usable=False,
                reason_code=str(failures[0].get("code") or "historical_walk_forward_replay_not_usable"),
                message="Historical walk-forward replay exists but does not clear the sweep_reversal live bridge floors.",
                metrics=base_metrics,
                source=source,
                reason_codes=tuple(str(item.get("code") or "") for item in failures if str(item.get("code") or "").strip()),
                failures=tuple(failures),
            )

        grade, recommendation = self._label(total_score)
        return ReplayValidationEvidence(
            approval_usable=True,
            reason_code="historical_walk_forward_sweep_reversal_bridge_approval_usable",
            message="Historical walk-forward active-contract replay clears the sweep_reversal live validation bridge floors.",
            metrics={**base_metrics, "grade": grade, "recommendation": recommendation},
            source=source,
            reason_codes=(
                "historical_walk_forward_sweep_reversal_bridge_approval_usable",
                "sweep_reversal_limit_active_contract_replay_pass",
            ),
            failures=(),
        )

    def _latest_backtest_entry(self, symbol: str) -> tuple[Path, dict[str, Any], dict[str, Any]] | None:
        directory = Path(str(getattr(self.settings, "auto_trading_replay_validation_bridge_backtest_dir", ""))).expanduser()
        for path in self._recent_json_files(directory, "micro_main_usdt_proxy_backtest_*.json"):
            payload = self._load_json(path)
            if not payload or self._is_stale(payload, path):
                continue
            results = payload.get("results")
            if isinstance(results, dict):
                iterable = results.items()
            elif isinstance(results, list):
                iterable = ((None, item) for item in results)
            else:
                continue
            for key, raw_entry in iterable:
                if not isinstance(raw_entry, dict):
                    continue
                canonical = self._normalize_symbol(
                    raw_entry.get("canonical_symbol") or self._proxy_to_canonical(raw_entry.get("proxy_symbol") or key)
                )
                if canonical == symbol:
                    return path, payload, raw_entry
        return None

    def _historical_walk_forward_cache_path(self) -> Path:
        raw_path = str(
            getattr(
                self.settings,
                "auto_trading_replay_validation_bridge_sweep_reversal_cache_file",
                "reports/validation/historical_walk_forward_cache/strategy_proof_contract_live_subset.json",
            )
            or ""
        ).strip()
        if raw_path:
            path = Path(raw_path).expanduser()
            return path if path.is_absolute() else Path.cwd() / path
        return (
            Path(str(getattr(self.settings, "validation_report_dir", "reports/validation")))
            / "historical_walk_forward_cache"
            / "strategy_proof_contract_live_subset.json"
        )

    def _historical_walk_forward_allowed_sessions(self) -> set[str]:
        configured = self._csv_set(getattr(self.settings, "auto_trading_micro_live_allowed_sessions", ""), lower=True)
        if configured:
            return configured
        policy = RolloutPolicyBootstrap().get(self._SWEEP_REVERSAL_FAMILY)
        return {str(item or "").strip().lower() for item in list(policy.allowed_sessions or []) if str(item).strip()}

    def _direction_contract_for_symbol(self, symbol: str) -> set[str]:
        normalized_symbol = self._normalize_symbol(symbol)
        directions: set[str] = set()
        for item in str(getattr(self.settings, "auto_trading_micro_live_direction_contract", "") or "").split(","):
            if ":" not in item:
                continue
            raw_symbol, raw_directions = item.split(":", 1)
            if self._normalize_symbol(raw_symbol) != normalized_symbol:
                continue
            for direction in raw_directions.replace("/", "|").split("|"):
                normalized_direction = str(direction or "").strip().upper()
                if normalized_direction:
                    directions.add(normalized_direction)
        return directions

    def _session_bucket(self, ts: datetime | None) -> str:
        if ts is None:
            return "unknown"
        current = ts.astimezone(timezone.utc)
        day_start = current.replace(hour=0, minute=0, second=0, microsecond=0)
        london_start = day_start.replace(hour=self._safe_int(getattr(self.settings, "trading_session_london_start_hour_utc", 7), 7))
        london_end = day_start.replace(hour=self._safe_int(getattr(self.settings, "trading_session_london_end_hour_utc", 12), 12))
        new_york_start = day_start.replace(
            hour=self._safe_int(getattr(self.settings, "trading_session_new_york_start_hour_utc", 13), 13)
        )
        new_york_end = day_start.replace(
            hour=self._safe_int(getattr(self.settings, "trading_session_new_york_end_hour_utc", 18), 18)
        )
        london_active = london_start <= current < london_end
        new_york_active = new_york_start <= current < new_york_end
        if london_active and new_york_active:
            return "overlap"
        if london_active:
            return "london"
        if new_york_active:
            return "new_york"
        return "dead_session"

    def _historical_walk_forward_metrics(
        self,
        rows: list[dict[str, Any]],
        *,
        structure_failure_stress_r: float | None = None,
    ) -> dict[str, Any]:
        values = [
            self._historical_realized_r(row, structure_failure_stress_r=structure_failure_stress_r)
            for row in rows
        ]
        closed = len(values)
        if closed <= 0:
            return {
                "closed_trades": 0,
                "ev_r": 0.0,
                "ev_r_lower_95": 0.0,
                "win_rate": 0.0,
                "total_r": 0.0,
                "stop_loss_share": 0.0,
                "structure_failure_share": 0.0,
                "structure_failure_count": 0,
                "max_drawdown_r": 0.0,
            }
        wins = [value for value in values if value > 0.0]
        structure_failures = [
            row
            for row in rows
            if str(row.get("final_exit_reason") or "").strip().lower() == "structure_failure"
        ]
        stop_losses = [
            row
            for row, value in zip(rows, values, strict=False)
            if str(row.get("final_exit_reason") or "").strip().lower() == "stop_loss" or value <= -1.0
        ]
        return {
            "closed_trades": closed,
            "ev_r": round(sum(values) / closed, 4),
            "ev_r_lower_95": self._ev_lower_95(values),
            "win_rate": round(len(wins) / closed, 4),
            "total_r": round(sum(values), 4),
            "stop_loss_share": round(len(stop_losses) / closed, 4),
            "structure_failure_share": round(len(structure_failures) / closed, 4),
            "structure_failure_count": len(structure_failures),
            "structure_failure_stress_r": structure_failure_stress_r,
            "max_drawdown_r": self._max_drawdown_r(values),
        }

    def _historical_realized_r(
        self,
        row: dict[str, Any],
        *,
        structure_failure_stress_r: float | None = None,
    ) -> float:
        for key in ("final_exit_realized_r", "replayed_realized_r"):
            value = row.get(key)
            if value not in {None, ""}:
                realized_r = self._safe_float(value)
                if structure_failure_stress_r is not None and self._is_stressed_structure_failure(row, realized_r):
                    return float(structure_failure_stress_r)
                return realized_r
        return 0.0

    @staticmethod
    def _is_stressed_structure_failure(row: dict[str, Any], realized_r: float) -> bool:
        reason = str(row.get("final_exit_reason") or "").strip().lower()
        if reason != "structure_failure":
            return False
        if realized_r > 0.0:
            return False
        trigger_detail = row.get("final_exit_trigger_detail")
        if isinstance(trigger_detail, dict):
            policy = str(trigger_detail.get("policy") or "").strip().lower()
            if policy == "btc_sweep_reversal_limit_initial_guard_stop":
                return True
        return True

    def _ev_lower_95(self, values: list[float]) -> float:
        count = len(values)
        if count <= 0:
            return 0.0
        mean = sum(values) / count
        if count == 1:
            return round(mean, 4)
        variance = sum((value - mean) ** 2 for value in values) / (count - 1)
        return round(mean - 1.96 * ((variance / count) ** 0.5), 4)

    def _max_drawdown_r(self, values: list[float]) -> float:
        peak = 0.0
        equity = 0.0
        worst = 0.0
        for value in values:
            equity += float(value)
            peak = max(peak, equity)
            worst = max(worst, peak - equity)
        return round(worst, 4)

    def _latest_portfolio_evidence(self, symbol: str) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]] | None:
        directory = Path(str(getattr(self.settings, "auto_trading_replay_validation_bridge_portfolio_dir", ""))).expanduser()
        risk_pct = self._safe_float(getattr(self.settings, "auto_trading_live_risk_per_trade_pct", 0.01), default=0.01)
        risk_key = f"{risk_pct * 100.0:.1f}%"
        min_years = self._safe_int(getattr(self.settings, "auto_trading_replay_validation_bridge_min_years", 3), default=3)
        max_mdd = self._safe_float(
            getattr(self.settings, "auto_trading_replay_validation_bridge_max_portfolio_mdd_pct", 25.0),
            default=25.0,
        )

        for path in self._recent_json_files(directory, "micro_main_usdt_proxy_yearly_portfolio_replay_*.json"):
            payload = self._load_json(path)
            if not payload or self._is_stale(payload, path):
                continue
            symbol_rows = payload.get("symbols")
            if not isinstance(symbol_rows, dict) or symbol not in symbol_rows:
                continue
            horizons = payload.get("horizons")
            if not isinstance(horizons, dict):
                continue
            years: list[dict[str, Any]] = []
            failures: list[dict[str, Any]] = []
            for year_name, raw_horizon in sorted(horizons.items()):
                if not isinstance(raw_horizon, dict):
                    continue
                row = raw_horizon.get(risk_key)
                if not isinstance(row, dict):
                    row = self._first_risk_row(raw_horizon)
                if not row:
                    continue
                accepted = self._safe_int(row.get("accepted_trades"))
                return_pct = self._safe_float(row.get("return_pct"))
                max_drawdown_pct = self._safe_float(row.get("max_drawdown_pct"))
                year = {
                    "year": str(year_name),
                    "accepted_trades": accepted,
                    "return_pct": round(return_pct, 4),
                    "max_drawdown_pct": round(max_drawdown_pct, 4),
                }
                years.append(year)
                if accepted <= 0:
                    failures.append({"code": "portfolio_replay_year_no_accepted_trades", **year})
                if return_pct <= 0.0:
                    failures.append({"code": "portfolio_replay_year_non_positive_return", **year})
                if max_drawdown_pct > max_mdd:
                    failures.append({"code": "portfolio_replay_mdd_above_floor", "required": max_mdd, **year})
            if len(years) < min_years:
                failures.append({"code": "portfolio_replay_years_below_floor", "value": len(years), "required": min_years})
            return (
                {
                    "portfolio_years": len(years),
                    "max_portfolio_drawdown_pct": max((self._safe_float(item.get("max_drawdown_pct")) for item in years), default=0.0),
                    "min_portfolio_return_pct": min((self._safe_float(item.get("return_pct")) for item in years), default=0.0),
                },
                {
                    "portfolio_report": str(path),
                    "portfolio_generated_at": str(payload.get("generated_at") or ""),
                    "portfolio_risk_key": risk_key,
                },
                failures,
            )
        return None

    def _recent_json_files(self, directory: Path, pattern: str) -> list[Path]:
        if not directory.exists():
            return []
        return sorted((path for path in directory.glob(pattern) if path.is_file()), key=lambda item: item.stat().st_mtime, reverse=True)

    def _load_json(self, path: Path) -> dict[str, Any] | None:
        try:
            stat = path.stat()
        except OSError:
            return None
        cache_key = path.resolve()
        cached = self._json_cache.get(cache_key)
        if cached is not None:
            cached_mtime_ns, cached_size, cached_payload = cached
            if cached_mtime_ns == stat.st_mtime_ns and cached_size == stat.st_size:
                return cached_payload
        try:
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        self._json_cache[cache_key] = (stat.st_mtime_ns, stat.st_size, payload)
        return payload

    def _is_stale(self, payload: dict[str, Any], path: Path) -> bool:
        max_age_days = self._safe_float(getattr(self.settings, "auto_trading_replay_validation_bridge_max_age_days", 14.0), default=14.0)
        if max_age_days <= 0:
            return False
        generated_at = self._parse_ts(payload.get("generated_at"))
        if generated_at is None:
            generated_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        return (datetime.now(timezone.utc) - generated_at).total_seconds() > max_age_days * 86400.0

    def _first_risk_row(self, horizon: dict[str, Any]) -> dict[str, Any] | None:
        for key, value in horizon.items():
            if key == "window" or not isinstance(value, dict):
                continue
            return value
        return None

    def _evidence_payload(self, evidence: ReplayValidationEvidence, *, applied: bool, reason: str = "") -> dict[str, Any]:
        return {
            "source": str(evidence.source.get("bridge_source") or "usdt_proxy_replay_bridge"),
            "applied": applied,
            "approval_usable": evidence.approval_usable,
            "reason_code": reason or evidence.reason_code,
            "message": evidence.message,
            "metrics": evidence.metrics,
            "source_reports": evidence.source,
            "reason_codes": list(evidence.reason_codes),
            "failures": list(evidence.failures),
        }

    def _score(self, *, closed: int, ev_r: float, win_rate: float) -> float:
        edge_score = self._clip((ev_r + 0.3) / 0.9 * 100.0)
        consistency_score = self._clip((win_rate - 0.35) / 0.35 * 100.0)
        robustness_score = self._clip((closed / 250.0) * 100.0)
        execution_score = 75.0
        total = edge_score * 0.40 + consistency_score * 0.20 + robustness_score * 0.25 + execution_score * 0.15
        return round(self._clip(total), 2)

    def _label(self, total_score: float) -> tuple[str, str]:
        if total_score >= 80.0:
            return "A", "deploy-small-capital"
        if total_score >= 70.0:
            return "B", "paper-and-limited-live"
        if total_score >= 60.0:
            return "C", "improve-before-live"
        if total_score >= 45.0:
            return "D", "research-only"
        return "F", "do-not-deploy"

    def _proxy_to_canonical(self, symbol: Any) -> str:
        normalized = self._normalize_symbol(symbol)
        if normalized.endswith("USDT"):
            return f"{normalized[:-4]}USDC"
        return normalized

    def _normalize_symbol(self, symbol: Any) -> str:
        return str(symbol or "").strip().upper()

    def _parse_ts(self, value: Any) -> datetime | None:
        raw = str(value or "").strip()
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _csv_set(self, value: Any, *, lower: bool = False, upper: bool = False) -> set[str]:
        out: set[str] = set()
        for item in str(value or "").split(","):
            normalized = str(item or "").strip()
            if not normalized:
                continue
            if lower:
                normalized = normalized.lower()
            elif upper:
                normalized = normalized.upper()
            out.add(normalized)
        return out

    def _safe_int(self, value: Any, default: int = 0) -> int:
        try:
            return int(float(str(value)))
        except (TypeError, ValueError):
            return default

    def _safe_float(self, value: Any, default: float = 0.0) -> float:
        try:
            parsed = float(str(value))
        except (TypeError, ValueError):
            return default
        return parsed if isfinite(parsed) else default

    def _clip(self, value: float, low: float = 0.0, high: float = 100.0) -> float:
        return max(low, min(high, value))
