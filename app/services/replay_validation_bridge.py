from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from math import isfinite
from pathlib import Path
from typing import Any

from app.core.enums import ExecutionMode


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

    _SUPPORTED_FAMILIES = {"session_impulse_retest"}
    _SUPPORTED_MODES = {ExecutionMode.MICRO_LIVE.value, ExecutionMode.LIVE.value}

    def __init__(self, settings: Any):
        self.settings = settings

    def apply_to_metrics(
        self,
        metrics: dict[str, Any],
        *,
        symbol: str,
        family: str,
        requested_mode: str,
    ) -> dict[str, Any]:
        if not self._enabled_for(family=family, requested_mode=requested_mode):
            return metrics

        evidence = self.evaluate(symbol=symbol)
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
                "validation_source": "usdt_proxy_replay_bridge",
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

    def evaluate(self, *, symbol: str) -> ReplayValidationEvidence:
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
            source=source,
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
        return str(family or "").lower() in self._SUPPORTED_FAMILIES and str(requested_mode or "") in self._SUPPORTED_MODES

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
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

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
            "source": "usdt_proxy_replay_bridge",
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
