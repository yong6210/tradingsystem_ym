#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.historical_walk_forward_split_review import HistoricalWalkForwardSplitReviewService


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT_DIR))
    except ValueError:
        return str(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a MICRO_LIVE historical plan blocklist from replay cache.")
    parser.add_argument("--cache-key", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--strategy-time-contract-path", default="")
    parser.add_argument("--max-realized-r", type=float, default=0.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cache_path = (
        ROOT_DIR
        / "reports"
        / "validation"
        / "historical_walk_forward_cache"
        / f"{str(args.cache_key).strip()}.json"
    )
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    service = HistoricalWalkForwardSplitReviewService()
    filtered = service.filter_payload(
        payload=payload,
        blocked_strategy_time_contract_path=str(args.strategy_time_contract_path or "").strip(),
    )
    threshold = float(args.max_realized_r)
    blocked_plan_ids: list[str] = []
    for row in list(filtered.get("trade_rows") or []):
        item = dict(row)
        plan_id = str(item.get("plan_id") or "").strip()
        if not plan_id:
            continue
        realized_r = float(
            item.get("replayed_realized_r")
            if item.get("replayed_realized_r") is not None
            else item.get("final_exit_realized_r") or 0.0
        )
        if realized_r <= threshold:
            blocked_plan_ids.append(plan_id)
    deduped = list(dict.fromkeys(blocked_plan_ids))

    output_path = Path(str(args.output))
    if not output_path.is_absolute():
        output_path = ROOT_DIR / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload_out = {
        "schema_version": "micro_live_plan_blocklist_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_cache_key": str(args.cache_key).strip(),
        "strategy_time_contract_path": str(args.strategy_time_contract_path or "").strip(),
        "max_realized_r": threshold,
        "blocked_plan_ids": deduped,
    }
    output_path.write_text(json.dumps(payload_out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "output_path": _display_path(output_path),
                "blocked_plan_count": len(deduped),
                "max_realized_r": threshold,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
