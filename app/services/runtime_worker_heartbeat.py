from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import Settings, get_settings


def _settings_or_default(settings: Settings | None = None) -> Settings:
    return settings or get_settings()


def heartbeat_dir(*, settings: Settings | None = None) -> Path:
    active = _settings_or_default(settings)
    return Path(active.runtime_worker_heartbeat_dir).expanduser()


def heartbeat_path(role: str, *, settings: Settings | None = None) -> Path:
    normalized_role = str(role or "").strip().lower()
    if normalized_role not in {"loop", "ws"}:
        raise ValueError(f"unsupported worker heartbeat role: {role}")
    return heartbeat_dir(settings=settings) / f"{normalized_role}.json"


def write_worker_heartbeat(
    role: str,
    *,
    settings: Settings | None = None,
    status: str = "ok",
    details: dict[str, Any] | None = None,
    at: datetime | None = None,
    pid: int | None = None,
) -> str:
    active = _settings_or_default(settings)
    out_dir = heartbeat_dir(settings=active)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = (at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    payload = {
        "role": str(role or "").strip().lower(),
        "status": str(status or "ok"),
        "ts": ts.isoformat(),
        "pid": int(pid or os.getpid()),
        "details": details or {},
    }
    out_path = heartbeat_path(role, settings=active)
    tmp_path = out_path.with_name(f".{out_path.name}.{os.getpid()}.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(out_path)
    return str(out_path)


def read_worker_heartbeat(role: str, *, settings: Settings | None = None) -> dict[str, Any] | None:
    path = heartbeat_path(role, settings=settings)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
