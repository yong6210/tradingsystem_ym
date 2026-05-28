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
from scripts.run_market_state_rotation_v6_walk_forward_validation import _aggregate_folds, _write_markdown


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Merge chunked market-state rotation v6 walk-forward reports.")
    parser.add_argument("--reports", nargs="+", required=True, help="Chunk JSON reports to merge.")
    parser.add_argument("--report-dir", required=True, help="Output directory for the merged report.")
    parser.add_argument("--name-suffix", default="merged", help="Filename suffix before .json.")
    return parser.parse_args()


def _fold_key(fold: dict[str, Any]) -> tuple[str, str, int]:
    return (
        str(fold.get("train_start") or ""),
        str(fold.get("test_start") or ""),
        int(fold.get("fold") or 0),
    )


def _infer_source_top_n(report: dict[str, Any]) -> int | None:
    candidate_count = report.get("candidate_count")
    try:
        candidate_count_int = int(candidate_count)
    except (TypeError, ValueError):
        return None
    overrides = report.get("config_overrides") or {}
    if bool(overrides.get("include_no_impulse_candidates")) and candidate_count_int % 2 == 0:
        return candidate_count_int // 2
    return candidate_count_int


def main() -> None:
    args = _parse_args()
    chunks = [json.loads(Path(path).read_text()) for path in args.reports]
    if not chunks:
        raise SystemExit("no reports provided")

    base = dict(chunks[0])
    folds_by_key: dict[tuple[str, str, int], dict[str, Any]] = {}
    for chunk in chunks:
        for fold in chunk.get("folds") or []:
            if not isinstance(fold, dict):
                continue
            folds_by_key[_fold_key(fold)] = dict(fold)

    folds = [fold for _, fold in sorted(folds_by_key.items(), key=lambda item: item[0])]
    for idx, fold in enumerate(folds, start=1):
        original_fold = fold.get("fold")
        fold["fold"] = idx
        fold["merged_original_fold"] = original_fold

    report = {
        **base,
        "created_at": datetime.now(UTC).isoformat(),
        "merged_from": [str(path) for path in args.reports],
        "source_top_n": base.get("source_top_n") or _infer_source_top_n(base),
        "fold_offset": 0,
        "fold_limit": 0,
        "aggregate": _aggregate_folds(folds),
        "folds": folds,
    }

    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    symbol = str(report.get("symbol") or "BTCUSDT")
    exec_interval = str(report.get("exec_interval") or "5m")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    json_path = report_dir / f"market_state_rotation_v6_walk_forward_{symbol}_{exec_interval}_{args.name_suffix}_{stamp}.json"
    latest_json = report_dir / f"market_state_rotation_v6_walk_forward_{symbol}_{exec_interval}_latest.json"
    summary_md = report_dir / "walk_forward_v6.md"
    text = json.dumps(report, ensure_ascii=False, indent=2)
    atomic_write_text(json_path, text)
    atomic_write_text(latest_json, text)
    _write_markdown(report, summary_md)
    print(json.dumps({"aggregate": report["aggregate"], "json": str(json_path), "summary": str(summary_md)}, indent=2))


if __name__ == "__main__":
    main()
