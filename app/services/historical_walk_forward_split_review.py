from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from app.core.config import ROOT_DIR, Settings, get_settings
from app.services.strategy_v2_validation import StrategyV2ValidationService


class HistoricalWalkForwardSplitReviewService:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        validation: StrategyV2ValidationService | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.validation = validation or StrategyV2ValidationService(self.settings)

    @staticmethod
    def _parse_ts(value: Any) -> datetime | None:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _realized_r(row: dict[str, Any]) -> float:
        for key in ("replayed_realized_r", "final_exit_realized_r"):
            value = row.get(key)
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        return 0.0

    @staticmethod
    def _percentile(values: list[float], q: float) -> float:
        if not values:
            return 0.0
        ordered = sorted(float(item) for item in values)
        if len(ordered) == 1:
            return float(ordered[0])
        clamped = min(max(float(q), 0.0), 1.0)
        index = int(round(clamped * (len(ordered) - 1)))
        return float(ordered[index])

    @staticmethod
    def _max_drawdown(values: list[float]) -> float:
        peak = 0.0
        equity = 0.0
        worst_drawdown = 0.0
        for item in values:
            equity += float(item)
            peak = max(peak, equity)
            worst_drawdown = max(worst_drawdown, peak - equity)
        return float(worst_drawdown)

    @staticmethod
    def _worst_loss_streak(values: list[float]) -> int:
        current = 0
        worst = 0
        for item in values:
            if float(item) <= 0.0:
                current += 1
                worst = max(worst, current)
            else:
                current = 0
        return int(worst)

    def _session_bucket(self, ts: datetime | None) -> str:
        if ts is None:
            return "unknown"
        return self.validation._session_bucket(ts)

    @staticmethod
    def _csv_items(raw: str) -> tuple[str, ...]:
        return tuple(item.strip() for item in str(raw or "").split(",") if item.strip())

    @staticmethod
    def _blocked_session_direction_hours_contract(
        raw: str,
    ) -> dict[tuple[str, str, str], set[int]]:
        mapping: dict[tuple[str, str, str], set[int]] = {}
        for item in str(raw or "").split(","):
            token = item.strip()
            if not token:
                continue
            parts = [part.strip() for part in token.split(":", 3)]
            if len(parts) != 4:
                continue
            symbol, session_name, direction, raw_hours = parts
            normalized_symbol = str(symbol or "").strip().upper()
            normalized_session = str(session_name or "").strip().lower()
            normalized_direction = str(direction or "").strip().upper()
            if not normalized_symbol or not normalized_session or not normalized_direction:
                continue
            hours: set[int] = set()
            for raw_hour in str(raw_hours or "").replace("/", "|").split("|"):
                text = raw_hour.strip()
                if not text:
                    continue
                try:
                    hour = int(text)
                except ValueError:
                    continue
                if 0 <= hour <= 23:
                    hours.add(hour)
            if hours:
                mapping[(normalized_symbol, normalized_session, normalized_direction)] = hours
        return mapping

    @staticmethod
    def _blocked_symbol_family_entry_direction_hours_contract(
        raw: str,
    ) -> dict[tuple[str, str, str, str], set[int]]:
        mapping: dict[tuple[str, str, str, str], set[int]] = {}
        for item in str(raw or "").split(","):
            token = item.strip()
            if not token:
                continue
            parts = [part.strip() for part in token.split(":", 4)]
            if len(parts) != 5:
                continue
            symbol, family, entry_model, direction, raw_hours = parts
            normalized_symbol = str(symbol or "").strip().upper()
            normalized_family = str(family or "").strip().lower()
            normalized_entry_model = str(entry_model or "").strip().upper()
            normalized_direction = str(direction or "").strip().upper()
            if not normalized_symbol or not normalized_family or not normalized_entry_model or not normalized_direction:
                continue
            hours: set[int] = set()
            for raw_hour in str(raw_hours or "").replace("/", "|").split("|"):
                text = raw_hour.strip()
                if not text:
                    continue
                try:
                    hour = int(text)
                except ValueError:
                    continue
                if 0 <= hour <= 23:
                    hours.add(hour)
            if hours:
                mapping[(normalized_symbol, normalized_family, normalized_entry_model, normalized_direction)] = hours
        return mapping

    @staticmethod
    def _blocked_strategy_time_contract(
        raw_path: str,
    ) -> list[dict[str, Any]]:
        text = str(raw_path or "").strip()
        if not text:
            return []
        path = Path(text)
        if not path.is_absolute():
            path = ROOT_DIR / path
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        rows = HistoricalWalkForwardSplitReviewService._json_list_payload(payload, key="blocked_buckets")
        blocked: list[dict[str, Any]] = []
        for item in rows:
            row = dict(item or {})
            symbol = str(row.get("symbol") or "").strip().upper()
            family = str(row.get("strategy_family") or "").strip().lower()
            entry_model = str(row.get("entry_model") or "").strip().upper()
            direction = str(row.get("direction") or "").strip().upper()
            if not symbol or not family or not entry_model or not direction:
                continue
            normalized: dict[str, Any] = {
                "symbol": symbol,
                "strategy_family": family,
                "entry_model": entry_model,
                "direction": direction,
            }
            valid = True
            for key, lower, upper in (
                ("year_utc", 2000, 3000),
                ("month_utc", 1, 12),
                ("day_utc", 1, 31),
                ("weekday_utc", 0, 6),
                ("hour_utc", 0, 23),
                ("minute_utc", 0, 59),
            ):
                value = row.get(key)
                if value in (None, ""):
                    continue
                try:
                    number = int(value)
                except (TypeError, ValueError):
                    valid = False
                    break
                if not (lower <= number <= upper):
                    valid = False
                    break
                normalized[key] = number
            if valid:
                blocked.append(normalized)
        return blocked

    @staticmethod
    def _matches_strategy_time_bucket(
        generated_ts: datetime,
        *,
        symbol: str,
        family: str,
        entry_model: str,
        direction: str,
        contract_row: dict[str, Any],
    ) -> bool:
        if symbol != str(contract_row.get("symbol") or ""):
            return False
        if family != str(contract_row.get("strategy_family") or ""):
            return False
        if entry_model != str(contract_row.get("entry_model") or ""):
            return False
        if direction != str(contract_row.get("direction") or ""):
            return False
        checks = {
            "year_utc": int(generated_ts.year),
            "month_utc": int(generated_ts.month),
            "day_utc": int(generated_ts.day),
            "weekday_utc": int(generated_ts.weekday()),
            "hour_utc": int(generated_ts.hour),
            "minute_utc": int(generated_ts.minute),
        }
        for key, actual in checks.items():
            expected = contract_row.get(key)
            if expected is None:
                continue
            if int(expected) != actual:
                return False
        return True

    @staticmethod
    def _blocked_plan_ids(raw_path: str) -> set[str]:
        text = str(raw_path or "").strip()
        if not text:
            return set()
        path = Path(text)
        if not path.is_absolute():
            path = ROOT_DIR / path
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return set()
        rows = HistoricalWalkForwardSplitReviewService._json_list_payload(payload, key="blocked_plan_ids")
        return {
            str(item or "").strip()
            for item in rows
            if str(item or "").strip()
        }

    @staticmethod
    def _json_list_payload(payload: Any, *, key: str) -> list[Any]:
        if isinstance(payload, dict):
            raw = payload.get(key) or []
        else:
            raw = payload
        if not isinstance(raw, (list, tuple, set)):
            return []
        return list(raw)

    def filter_payload(
        self,
        *,
        payload: dict[str, Any],
        allowed_sessions: tuple[str, ...] = (),
        blocked_session_direction_hours_utc: str = "",
        blocked_symbol_family_entry_direction_hours_utc: str = "",
        blocked_strategy_time_contract_path: str = "",
        blocked_plan_ids_path: str = "",
    ) -> dict[str, Any]:
        allowed_session_set = {item.strip().lower() for item in allowed_sessions if item.strip()}
        blocked_contract = self._blocked_session_direction_hours_contract(blocked_session_direction_hours_utc)
        blocked_strategy_contract = self._blocked_symbol_family_entry_direction_hours_contract(
            blocked_symbol_family_entry_direction_hours_utc
        )
        blocked_time_contract = self._blocked_strategy_time_contract(blocked_strategy_time_contract_path)
        blocked_plan_ids = self._blocked_plan_ids(blocked_plan_ids_path)
        rows = [dict(row) for row in list(payload.get("trade_rows") or [])]
        filtered_rows: list[dict[str, Any]] = []
        for row in rows:
            generated_ts = self._parse_ts(row.get("generated_ts")) or self._parse_ts(row.get("closed_ts"))
            session_name = self._session_bucket(generated_ts)
            hour_utc = int(generated_ts.hour) if generated_ts is not None else None
            symbol = str(row.get("symbol") or "").strip().upper()
            family = str(row.get("strategy_family") or "").strip().lower()
            entry_model = str(row.get("entry_model") or "").strip().upper()
            direction = str(row.get("direction") or "").strip().upper()
            plan_id = str(row.get("plan_id") or "").strip()
            if allowed_session_set and session_name not in allowed_session_set:
                continue
            blocked_hours = set(blocked_contract.get((symbol, session_name, direction)) or set())
            if hour_utc is not None and blocked_hours and hour_utc in blocked_hours:
                continue
            blocked_strategy_hours = set(blocked_strategy_contract.get((symbol, family, entry_model, direction)) or set())
            if hour_utc is not None and blocked_strategy_hours and hour_utc in blocked_strategy_hours:
                continue
            if generated_ts is not None and any(
                self._matches_strategy_time_bucket(
                    generated_ts,
                    symbol=symbol,
                    family=family,
                    entry_model=entry_model,
                    direction=direction,
                    contract_row=contract_row,
                )
                for contract_row in blocked_time_contract
            ):
                continue
            if blocked_plan_ids and plan_id and plan_id in blocked_plan_ids:
                continue
            next_row = dict(row)
            next_row["generated_session"] = session_name
            if hour_utc is not None:
                next_row["generated_hour_utc"] = hour_utc
            filtered_rows.append(next_row)

        symbol_counts: dict[str, int] = defaultdict(int)
        for row in filtered_rows:
            symbol_key = str(row.get("symbol") or "").strip().upper()
            if symbol_key:
                symbol_counts[symbol_key] += 1
        existing_summaries = {
            str(summary.get("symbol") or "").strip().upper(): dict(summary)
            for summary in list(payload.get("symbol_summaries") or [])
            if str(summary.get("symbol") or "").strip()
        }
        symbol_summaries: list[dict[str, Any]] = []
        for symbol_key in sorted(symbol_counts):
            summary = dict(existing_summaries.get(symbol_key) or {"symbol": symbol_key})
            summary["symbol"] = symbol_key
            summary["closed_trade_count"] = int(symbol_counts[symbol_key])
            symbol_summaries.append(summary)

        filtered_payload = dict(payload)
        filtered_payload["trade_rows"] = filtered_rows
        filtered_payload["symbol_summaries"] = symbol_summaries
        filtered_payload["applied_filters"] = {
            "allowed_sessions": sorted(allowed_session_set),
            "blocked_session_direction_hours_utc": str(blocked_session_direction_hours_utc or ""),
            "blocked_symbol_family_entry_direction_hours_utc": str(blocked_symbol_family_entry_direction_hours_utc or ""),
            "blocked_strategy_time_contract_path": str(blocked_strategy_time_contract_path or ""),
            "blocked_plan_ids_path": str(blocked_plan_ids_path or ""),
        }
        return filtered_payload

    def _metrics(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        values = [self._realized_r(row) for row in rows]
        trade_count = len(values)
        if trade_count <= 0:
            return {
                "trades": 0,
                "win_rate": 0.0,
                "ev_r": 0.0,
                "total_r": 0.0,
                "profit_factor": None,
                "avg_win_r": 0.0,
                "avg_loss_r": 0.0,
                "p5_r": 0.0,
                "p50_r": 0.0,
                "max_drawdown_r": 0.0,
                "avg_hold_bars": 0.0,
                "stop_loss_share": 0.0,
                "target_tp3_share": 0.0,
                "session_end_flatten_share": 0.0,
                "worst_loss_streak": 0,
            }

        wins = [value for value in values if value > 0.0]
        losses = [value for value in values if value <= 0.0]
        gross_profit = sum(wins)
        gross_loss = abs(sum(value for value in losses if value < 0.0))
        hold_bars = [
            int(row.get("final_exit_held_bars", 0) or 0)
            for row in rows
            if row.get("final_exit_held_bars") is not None
        ]
        stop_loss_count = sum(1 for row in rows if str(row.get("final_exit_reason") or "") == "stop_loss")
        tp3_count = sum(1 for row in rows if str(row.get("final_exit_reason") or "") == "target_tp3")
        flatten_count = sum(1 for row in rows if str(row.get("final_exit_reason") or "") == "session_end_flatten")
        return {
            "trades": int(trade_count),
            "win_rate": round(len(wins) / trade_count, 4),
            "ev_r": round(sum(values) / trade_count, 4),
            "total_r": round(sum(values), 4),
            "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss > 1e-9 else None,
            "avg_win_r": round(sum(wins) / len(wins), 4) if wins else 0.0,
            "avg_loss_r": round(sum(losses) / len(losses), 4) if losses else 0.0,
            "p5_r": round(self._percentile(values, 0.05), 4),
            "p50_r": round(self._percentile(values, 0.50), 4),
            "max_drawdown_r": round(self._max_drawdown(values), 4),
            "avg_hold_bars": round(sum(hold_bars) / len(hold_bars), 4) if hold_bars else 0.0,
            "stop_loss_share": round(stop_loss_count / trade_count, 4),
            "target_tp3_share": round(tp3_count / trade_count, 4),
            "session_end_flatten_share": round(flatten_count / trade_count, 4),
            "worst_loss_streak": self._worst_loss_streak(values),
        }

    def _group_rows(
        self,
        rows: list[dict[str, Any]],
        *,
        key_func: Callable[[dict[str, Any]], str],
        chronological: bool = False,
    ) -> list[dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            key = str(key_func(row) or "unknown")
            grouped[key].append(row)

        out: list[dict[str, Any]] = []
        for key, bucket in grouped.items():
            summary = {"key": key}
            summary.update(self._metrics(bucket))
            out.append(summary)

        if chronological:
            out.sort(key=lambda row: str(row["key"]))
        else:
            out.sort(key=lambda row: (-int(row["trades"]), str(row["key"])))
        return out

    @staticmethod
    def _find_extreme(
        rows: list[dict[str, Any]],
        *,
        metric: str,
        min_trades: int = 50,
        highest: bool = True,
    ) -> dict[str, Any] | None:
        eligible = [dict(row) for row in rows if int(row.get("trades", 0) or 0) >= min_trades]
        if not eligible:
            return None
        eligible.sort(
            key=lambda row: (float(row.get(metric, 0.0) or 0.0), int(row.get("trades", 0) or 0), str(row.get("key") or "")),
            reverse=highest,
        )
        return eligible[0]

    @staticmethod
    def _format_metric(value: Any, *, percent: bool = False) -> str:
        if value is None:
            return "n/a"
        if percent:
            return f"{float(value) * 100.0:.2f}%"
        return f"{float(value):+.4f}" if isinstance(value, (int, float)) else str(value)

    def _markdown_table(self, rows: list[dict[str, Any]], *, limit: int = 12) -> list[str]:
        selected = rows[:limit]
        lines = [
            "| key | trades | win_rate | ev_r | total_r | pf | stop_loss | max_dd |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        for row in selected:
            pf = row.get("profit_factor")
            lines.append(
                "| "
                + " | ".join(
                    [
                        str(row.get("key") or ""),
                        str(int(row.get("trades", 0) or 0)),
                        f"{float(row.get('win_rate', 0.0) or 0.0) * 100.0:.2f}%",
                        f"{float(row.get('ev_r', 0.0) or 0.0):+.4f}",
                        f"{float(row.get('total_r', 0.0) or 0.0):+.4f}",
                        f"{float(pf):.4f}" if pf is not None else "n/a",
                        f"{float(row.get('stop_loss_share', 0.0) or 0.0) * 100.0:.2f}%",
                        f"{float(row.get('max_drawdown_r', 0.0) or 0.0):.4f}",
                    ]
                )
                + " |"
            )
        return lines

    def _write_report(self, *, payload: dict[str, Any]) -> str:
        out_dir = Path(self.settings.validation_report_dir) / "historical_walk_forward_split_reviews"
        out_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc).replace(microsecond=0)
        review_name = str(payload.get("review_name") or "review")
        file_path = out_dir / f"historical_walk_forward_split_review_{review_name}_{now.strftime('%Y%m%dT%H%M%SZ')}.md"

        overall = dict(payload.get("overall") or {})
        breakdowns = dict(payload.get("breakdowns") or {})
        headline = dict(payload.get("headline") or {})
        profit_factor = overall.get("profit_factor")
        profit_factor_text = f"{float(profit_factor):.4f}" if profit_factor is not None else "n/a"

        lines = [
            f"# Historical Walk-Forward Split Review: {review_name}",
            "",
            f"- generated_at: {payload.get('generated_at')}",
            f"- contract_scope: {payload.get('contract_scope')}",
            f"- source_mode: {payload.get('source_mode')}",
            f"- symbols: {payload.get('eligible_symbols')}",
            f"- families: {payload.get('eligible_families')}",
            f"- entry_models: {payload.get('eligible_entry_models')}",
            f"- simulation_start_ts: {payload.get('simulation_start_ts')}",
            f"- simulation_end_ts: {payload.get('simulation_end_ts')}",
            f"- applied_filters: {payload.get('applied_filters')}",
            "",
            "## Headline",
            "",
            f"- trades: {int(overall.get('trades', 0) or 0)}",
            f"- win_rate: {float(overall.get('win_rate', 0.0) or 0.0) * 100.0:.2f}%",
            f"- ev_r: {float(overall.get('ev_r', 0.0) or 0.0):+.4f}",
            f"- total_r: {float(overall.get('total_r', 0.0) or 0.0):+.4f}",
            f"- profit_factor: {profit_factor_text}",
            f"- stop_loss_share: {float(overall.get('stop_loss_share', 0.0) or 0.0) * 100.0:.2f}%",
            f"- max_drawdown_r: {float(overall.get('max_drawdown_r', 0.0) or 0.0):.4f}",
            f"- p5_r: {float(overall.get('p5_r', 0.0) or 0.0):+.4f}",
            "",
            "## Extremes",
            "",
            f"- strongest_symbol_ev: {headline.get('strongest_symbol_ev')}",
            f"- weakest_symbol_ev: {headline.get('weakest_symbol_ev')}",
            f"- strongest_family_ev: {headline.get('strongest_family_ev')}",
            f"- weakest_family_ev: {headline.get('weakest_family_ev')}",
            f"- strongest_direction_ev: {headline.get('strongest_direction_ev')}",
            f"- weakest_direction_ev: {headline.get('weakest_direction_ev')}",
            f"- strongest_entry_ev: {headline.get('strongest_entry_ev')}",
            f"- weakest_entry_ev: {headline.get('weakest_entry_ev')}",
            f"- strongest_recent_month_ev: {headline.get('strongest_recent_month_ev')}",
            f"- weakest_recent_month_ev: {headline.get('weakest_recent_month_ev')}",
            "",
            "## Symbol Breakdown",
            "",
        ]
        lines.extend(self._markdown_table(list(breakdowns.get("symbol") or []), limit=8))
        lines.extend(
            [
                "",
                "## Family Breakdown",
                "",
            ]
        )
        lines.extend(self._markdown_table(list(breakdowns.get("family") or []), limit=8))
        lines.extend(
            [
                "",
            "## Direction Breakdown",
            "",
            ]
        )
        lines.extend(self._markdown_table(list(breakdowns.get("direction") or []), limit=8))
        lines.extend(
            [
                "",
                "## Entry Model Breakdown",
                "",
            ]
        )
        lines.extend(self._markdown_table(list(breakdowns.get("entry_model") or [])))
        lines.extend(
            [
                "",
                "## Exit Reason Breakdown",
                "",
            ]
        )
        lines.extend(self._markdown_table(list(breakdowns.get("exit_reason") or []), limit=8))
        lines.extend(
            [
                "",
                "## Generated Session Breakdown",
                "",
            ]
        )
        lines.extend(self._markdown_table(list(breakdowns.get("generated_session") or []), limit=8))
        lines.extend(
            [
                "",
                "## Recent Months",
                "",
            ]
        )
        lines.extend(self._markdown_table(list(breakdowns.get("generated_month_recent") or []), limit=12))

        file_path.write_text("\n".join(lines), encoding="utf-8")
        return str(file_path)

    def summarize_payload(
        self,
        *,
        payload: dict[str, Any],
        review_name: str,
        write_report: bool = True,
    ) -> dict[str, Any]:
        rows = [dict(row) for row in list(payload.get("trade_rows") or [])]
        direction_rows = self._group_rows(rows, key_func=lambda row: str(row.get("direction") or "unknown").upper())
        entry_rows = self._group_rows(rows, key_func=lambda row: str(row.get("entry_model") or "unknown").upper())
        exit_rows = self._group_rows(rows, key_func=lambda row: str(row.get("final_exit_reason") or "unknown"))
        family_rows = self._group_rows(rows, key_func=lambda row: str(row.get("strategy_family") or "unknown"))
        symbol_rows = self._group_rows(rows, key_func=lambda row: str(row.get("symbol") or "unknown").upper())
        session_rows = self._group_rows(
            rows,
            key_func=lambda row: self._session_bucket(self._parse_ts(row.get("generated_ts"))),
        )
        month_rows = self._group_rows(
            rows,
            key_func=lambda row: (
                self._parse_ts(row.get("generated_ts")) or self._parse_ts(row.get("closed_ts")) or datetime.min.replace(tzinfo=timezone.utc)
            ).strftime("%Y-%m"),
            chronological=True,
        )

        review: dict[str, Any] = {
            "schema_version": "historical_walk_forward_split_review_v1",
            "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "review_name": review_name,
            "contract_scope": str(payload.get("contract_scope") or ""),
            "source_mode": str(payload.get("source_mode") or ""),
            "eligible_symbols": list(payload.get("eligible_symbols") or []),
            "eligible_families": list(payload.get("eligible_families") or []),
            "eligible_entry_models": list(payload.get("eligible_entry_models") or []),
            "simulation_start_ts": str(payload.get("simulation_start_ts") or ""),
            "simulation_end_ts": str(payload.get("simulation_end_ts") or ""),
            "symbol_summaries": list(payload.get("symbol_summaries") or []),
            "applied_filters": dict(payload.get("applied_filters") or {}),
            "overall": self._metrics(rows),
            "breakdowns": {
                "symbol": symbol_rows,
                "family": family_rows,
                "direction": direction_rows,
                "entry_model": entry_rows,
                "exit_reason": exit_rows,
                "generated_session": session_rows,
                "generated_month": month_rows,
                "generated_month_recent": month_rows[-12:],
            },
            "headline": {
                "strongest_symbol_ev": self._find_extreme(symbol_rows, metric="ev_r", min_trades=100, highest=True),
                "weakest_symbol_ev": self._find_extreme(symbol_rows, metric="ev_r", min_trades=100, highest=False),
                "strongest_family_ev": self._find_extreme(family_rows, metric="ev_r", min_trades=100, highest=True),
                "weakest_family_ev": self._find_extreme(family_rows, metric="ev_r", min_trades=100, highest=False),
                "strongest_direction_ev": self._find_extreme(direction_rows, metric="ev_r", min_trades=100, highest=True),
                "weakest_direction_ev": self._find_extreme(direction_rows, metric="ev_r", min_trades=100, highest=False),
                "strongest_entry_ev": self._find_extreme(entry_rows, metric="ev_r", min_trades=100, highest=True),
                "weakest_entry_ev": self._find_extreme(entry_rows, metric="ev_r", min_trades=100, highest=False),
                "strongest_recent_month_ev": self._find_extreme(month_rows[-12:], metric="ev_r", min_trades=30, highest=True),
                "weakest_recent_month_ev": self._find_extreme(month_rows[-12:], metric="ev_r", min_trades=30, highest=False),
            },
            "report_path": None,
        }
        if write_report:
            review["report_path"] = self._write_report(payload=review)
        return review
