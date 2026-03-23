#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.services.parameter_changelog import ParameterChangelogService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate strategy parameter changelog snapshot")
    parser.add_argument("--version", default="", help="Strategy version override (default: settings.strategy_version)")
    parser.add_argument("--trigger", default="manual", help="Generation trigger label")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = get_settings()
    version = args.version.strip() or settings.strategy_version
    payload = ParameterChangelogService().generate(version=version, trigger=args.trigger)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
