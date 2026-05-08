#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.db.session import SessionLocal, init_db
from app.services.alt_data_family_research import inspect_alt_data_feasibility


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit alt-data family feasibility against local DB tables.")
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    init_db()
    settings = get_settings()
    generated_at = datetime.now(UTC)

    with SessionLocal() as db:
        payload = {
            "generated_at": generated_at.isoformat(),
            "database_url": settings.database_url,
            **inspect_alt_data_feasibility(bind=db.get_bind()),
        }

    if args.write_report:
        out_dir = Path(settings.validation_report_dir) / "alt_data_family_feasibility"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"alt_data_family_feasibility_{generated_at.strftime('%Y%m%dT%H%M%SZ')}.json"
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        payload["report_path"] = str(out_path)

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
