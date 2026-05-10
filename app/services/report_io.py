from __future__ import annotations

from pathlib import Path
from uuid import uuid4


def atomic_write_text(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        tmp_path.write_text(content, encoding=encoding)
        tmp_path.replace(path)
    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
