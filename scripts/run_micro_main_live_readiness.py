from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from math import isfinite
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.db.session import SessionLocal, init_db
from app.services.micro_main_live_readiness import evaluate_micro_main_live_readiness, micro_main_live_readiness_to_dict
from app.services.micro_main_universe_policy import build_micro_main_universe_policy_snapshot
from app.services.report_io import atomic_write_text
from app.services.strategy_engine import StrategyEngine


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value in (None, "", "None"):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if isfinite(parsed) else default


def _safe_int(value: Any, default: int = 0) -> int:
    return int(_safe_float(value, float(default)))


def _safe_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off", "none", "null", ""}:
        return False
    return bool(default)


def main() -> None:
    init_db()
    settings = get_settings()
    generated_at = datetime.now(UTC).replace(microsecond=0)

    symbols = [
        item.strip().upper()
        for item in str(settings.session_impulse_retest_allowed_symbols or "").split(",")
        if item.strip()
    ]
    policy = build_micro_main_universe_policy_snapshot()
    results: list[dict[str, object]] = []
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        for symbol in symbols:
            shadow_summary = engine._session_impulse_retest_shadow_summary(symbol=symbol)
            readiness = evaluate_micro_main_live_readiness(
                symbol=symbol,
                shadow_summary=shadow_summary,
                universe_policy=policy,
                enabled=_safe_bool(settings.session_impulse_retest_enabled),
                shadow_only=_safe_bool(settings.session_impulse_retest_shadow_only),
                partial_ratio=_safe_float(settings.session_impulse_retest_partial_activation_ratio, 0.3),
                core_live_slots=_safe_int(settings.session_impulse_retest_core_live_slots, 2),
                secondary_live_enabled=_safe_bool(settings.session_impulse_retest_secondary_live_enabled),
            )
            results.append(micro_main_live_readiness_to_dict(readiness))

    payload = {
        "generated_at": generated_at.isoformat(),
        "family": "session_impulse_retest",
        "symbols": symbols,
        "policy": policy,
        "results": results,
    }
    out_dir = Path(settings.validation_report_dir) / "micro_main_live_readiness"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"micro_main_live_readiness_{generated_at.strftime('%Y%m%dT%H%M%SZ')}.json"
    atomic_write_text(out_path, json.dumps(payload, ensure_ascii=False, indent=2))
    print(str(out_path))


if __name__ == "__main__":
    main()
