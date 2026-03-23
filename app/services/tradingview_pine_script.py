from __future__ import annotations

from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
PINE_SCRIPT_PATH = ROOT_DIR / "scripts" / "tradingview" / "trading_engine_v1_mirror.pine"


def load_tradingview_pine_script() -> str:
    return PINE_SCRIPT_PATH.read_text(encoding="utf-8")
