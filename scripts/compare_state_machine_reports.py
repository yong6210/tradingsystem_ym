#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.report_io import atomic_write_text


IGNORED_KEY_FIELDS = {
    "avg_close_equity_return_pct",
    "close_actions",
    "close_win_rate",
    "final_equity",
    "liquidated",
    "max_drawdown_pct",
    "median_close_equity_return_pct",
    "model_id",
    "months",
    "months_doubled",
    "open_actions",
    "score",
    "signals",
    "stats",
    "total_return_pct",
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare state-machine backtest reports across intervals.")
    parser.add_argument("--reports", nargs="+", required=True, help="State-machine report JSON paths.")
    parser.add_argument("--report-dir", required=True, help="Output directory for comparison report.")
    parser.add_argument("--top", type=int, default=30)
    return parser.parse_args()


def _interval_minutes(interval: str) -> int:
    if interval.endswith("m"):
        return max(int(interval[:-1]), 1)
    if interval.endswith("h"):
        return max(int(interval[:-1]) * 60, 1)
    raise ValueError(f"unsupported_interval: {interval}")


def _normalized_value(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 8)
    return value


def _strategy_key(result: dict[str, Any], interval_minutes: int) -> tuple[tuple[str, Any], ...]:
    parts: list[tuple[str, Any]] = []
    for key, value in sorted(result.items()):
        if key in IGNORED_KEY_FIELDS or key == "reaction_wait_bars":
            continue
        if isinstance(value, dict):
            continue
        parts.append((key, _normalized_value(value)))
    parts.append(("reaction_wait_minutes", int(result["reaction_wait_bars"]) * interval_minutes))
    return tuple(parts)


def _best_by_strategy(report: dict[str, Any]) -> dict[tuple[tuple[str, Any], ...], dict[str, Any]]:
    interval = str(report["market_data"]["interval"])
    interval_minutes = _interval_minutes(interval)
    by_key: dict[tuple[tuple[str, Any], ...], dict[str, Any]] = {}
    for result in report["all_results"]:
        key = _strategy_key(result, interval_minutes)
        previous = by_key.get(key)
        if previous is None or (result["score"], result["total_return_pct"]) > (previous["score"], previous["total_return_pct"]):
            by_key[key] = dict(result)
    return by_key


def _key_to_params(key: tuple[tuple[str, Any], ...]) -> dict[str, Any]:
    return {field: value for field, value in key}


def _comparison_rows(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keyed_reports = [_best_by_strategy(report) for report in reports]
    labels = [str(report["market_data"]["interval"]) for report in reports]
    common_keys = set(keyed_reports[0])
    for keyed in keyed_reports[1:]:
        common_keys &= set(keyed)

    rows: list[dict[str, Any]] = []
    for key in common_keys:
        interval_results: dict[str, dict[str, Any]] = {}
        returns: list[float] = []
        drawdowns: list[float] = []
        scores: list[float] = []
        for label, keyed in zip(labels, keyed_reports, strict=True):
            result = keyed[key]
            interval_results[label] = {
                "model_id": result["model_id"],
                "total_return_pct": result["total_return_pct"],
                "max_drawdown_pct": result["max_drawdown_pct"],
                "score": result["score"],
                "open_actions": result["open_actions"],
                "close_actions": result["close_actions"],
                "close_win_rate": result["close_win_rate"],
                "months_doubled": result["months_doubled"],
            }
            returns.append(float(result["total_return_pct"]))
            drawdowns.append(float(result["max_drawdown_pct"]))
            scores.append(float(result["score"]))
        min_return = min(returns)
        avg_return = sum(returns) / len(returns)
        max_drawdown = max(drawdowns)
        min_score = min(scores)
        robust_score = min_return - 1.25 * max_drawdown
        rows.append(
            {
                "params": _key_to_params(key),
                "intervals": interval_results,
                "min_return_pct": round(min_return, 6),
                "avg_return_pct": round(avg_return, 6),
                "max_drawdown_pct": round(max_drawdown, 6),
                "min_score": round(min_score, 6),
                "robust_score": round(robust_score, 6),
            }
        )
    rows.sort(key=lambda item: (item["robust_score"], item["min_return_pct"], -item["max_drawdown_pct"]), reverse=True)
    return rows


def _write_summary_md(path: Path, report: dict[str, Any]) -> None:
    rows = report["top_robust"]
    lines = [
        "# 상태 머신 교차 검증 비교",
        "",
        f"- 생성 시각: {report['created_at']}",
        f"- 비교 리포트 수: {len(report['source_reports'])}개",
        f"- 공통 전략 조합: {report['common_strategies']}개",
        "",
        "## Robust Top",
        "",
        "| 순위 | 최소수익 | 평균수익 | 최대MDD | 점수 | 핵심 파라미터 |",
        "|---:|---:|---:|---:|---:|---|",
    ]
    for idx, row in enumerate(rows[:20], start=1):
        params = row["params"]
        param_text = (
            f"src={params.get('entry_source_kinds')}, infer={params.get('infer_neutral_entry_side')}, "
            f"ptp={params.get('partial_tp_pct')}, stp={params.get('secondary_tp_pct')}, "
            f"ftp={params.get('full_tp_pct')}, "
            f"sl={params.get('stop_pct')}, ppstop={params.get('post_partial_stop_pct')}, "
            f"red={params.get('reduce_fraction')}, sigred={params.get('signal_reduce_fraction')}, "
            f"flred={params.get('flip_reduce_fraction')}, sfred={params.get('stop_flip_reduce_fraction')}, "
            f"sred={params.get('secondary_reduce_fraction')}, "
            f"hold={params.get('max_hold_hours')}h, shold={params.get('signal_max_hold_hours')}h, "
            f"fhold={params.get('flip_max_hold_hours')}h, sfhold={params.get('stop_flip_max_hold_hours')}h, "
            f"pststop={params.get('post_stop_cooldown_hours')}h, "
            f"sfconfirm={params.get('stop_flip_confirm_minutes')}m, "
            f"ddthr={params.get('drawdown_throttle_pct')}, ddmul={params.get('drawdown_throttle_multiplier')}, "
            f"done={params.get('include_done')}"
        )
        lines.append(
            f"| {idx} | {row['min_return_pct']} | {row['avg_return_pct']} | "
            f"{row['max_drawdown_pct']} | {row['robust_score']} | `{param_text}` |"
        )

    if rows:
        best = rows[0]
        lines.extend(["", "## 1위 상세", ""])
        for interval, result in best["intervals"].items():
            lines.append(
                f"- {interval}: 수익 {result['total_return_pct']}%, MDD {result['max_drawdown_pct']}%, "
                f"승률 {result['close_win_rate']}, 모델 `{result['model_id']}`"
            )
    atomic_write_text(path, "\n".join(lines) + "\n")


def main() -> None:
    args = _parse_args()
    reports = [json.loads(Path(path).read_text(encoding="utf-8")) for path in args.reports]
    rows = _comparison_rows(reports)
    report = {
        "created_at": datetime.now(UTC).isoformat(),
        "source_reports": [str(path) for path in args.reports],
        "common_strategies": len(rows),
        "top_robust": rows[: int(args.top)],
        "top_min_return": sorted(rows, key=lambda item: (item["min_return_pct"], -item["max_drawdown_pct"]), reverse=True)[: int(args.top)],
    }
    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / "state_machine_report_comparison.json"
    md_path = report_dir / "state_machine_report_comparison_summary.md"
    atomic_write_text(json_path, json.dumps(report, ensure_ascii=False, indent=2))
    _write_summary_md(md_path, report)
    print(json.dumps({"json": str(json_path), "md": str(md_path), "top_robust": report["top_robust"][:5]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
