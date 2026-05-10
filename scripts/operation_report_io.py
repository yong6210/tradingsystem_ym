from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


JsonDefault = Callable[[Any], Any]
MarkdownWriter = Callable[..., None]


def default_json(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def display_path(path: Path, root_dir: Path) -> str:
    try:
        return str(path.resolve().relative_to(root_dir))
    except ValueError:
        return str(path)


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    tmp_path.write_text(content, encoding="utf-8")
    tmp_path.replace(path)


def write_json(path: Path, payload: dict[str, Any], *, json_default: JsonDefault = default_json) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2, default=json_default))


def write_latest_aliases(
    *,
    report_dir: Path,
    payload: dict[str, Any],
    write_markdown_report: MarkdownWriter,
    root_dir: Path,
    json_default: JsonDefault = default_json,
) -> dict[str, str]:
    latest_md = report_dir / "latest.md"
    latest_json = report_dir / "latest.json"
    write_markdown_report(latest_md, payload, atomic=True)
    write_json(latest_json, payload, json_default=json_default)
    return {
        "latest_report_path": display_path(latest_md, root_dir),
        "latest_json_path": display_path(latest_json, root_dir),
    }
