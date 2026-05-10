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

from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import AlertSubscription
from app.db.session import SessionLocal, init_db
from app.services.strategy_engine import StrategyEngine


def _safe_bool(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off", "none", "null", ""}:
            return False
    return True if value else False


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ensure Discord subscriptions for micro-main prop-style alerts.")
    parser.add_argument("--channel", default="discord")
    parser.add_argument("--types", default="confirm,entry,tp,sl")
    parser.add_argument("--symbols", default="")
    return parser.parse_args()


def _parse_csv(raw: str) -> list[str]:
    return [item.strip().upper() for item in str(raw or "").split(",") if item.strip()]


def main() -> int:
    args = _parse_args()
    init_db()
    settings = get_settings()
    symbols = _parse_csv(args.symbols) or _parse_csv(settings.auto_trading_micro_live_allowed_symbols)
    alert_types = [item.strip().lower() for item in str(args.types or "").split(",") if item.strip()]

    added: list[dict[str, str]] = []
    existing: list[dict[str, str]] = []

    with SessionLocal() as db:
        engine = StrategyEngine(db)
        for symbol in symbols:
            for alert_type in alert_types:
                rows = list(
                    db.scalars(
                        select(AlertSubscription).where(
                            AlertSubscription.symbol == symbol,
                            AlertSubscription.channel == args.channel,
                            AlertSubscription.type == alert_type,
                            AlertSubscription.plan_id.is_(None),
                        )
                    )
                )
                active = any(_safe_bool((row.payload or {}).get("subscription_active")) for row in rows)
                if active:
                    existing.append({"symbol": symbol, "type": alert_type})
                    continue
                engine.subscribe_alert(
                    symbol=symbol,
                    channel=args.channel,
                    alert_type=alert_type,
                    plan_id=None,
                    payload={
                        "subscription_scope": "micro_main_prop_manual",
                        "notes": "manual_prop_follow_signal",
                    },
                )
                added.append({"symbol": symbol, "type": alert_type})

    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "channel": args.channel,
        "symbols": symbols,
        "types": alert_types,
        "added": added,
        "existing": existing,
        "added_count": len(added),
        "existing_count": len(existing),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
