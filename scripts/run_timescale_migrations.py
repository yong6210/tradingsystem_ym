#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from sqlalchemy import create_engine, text

ROOT_DIR = Path(__file__).resolve().parents[1]


def _resolve_root_path(raw_path: str | Path) -> Path:
    path = Path(raw_path).expanduser()
    return path if path.is_absolute() else ROOT_DIR / path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run TimescaleDB SQL migrations")
    parser.add_argument("--database-url", required=True, help="PostgreSQL DSN")
    parser.add_argument(
        "--migrations-dir",
        default="scripts/migrations",
        help="Directory containing .sql migrations",
    )
    return parser.parse_args()


def split_sql(sql: str) -> list[str]:
    chunks: list[str] = []
    buff: list[str] = []
    for line in sql.splitlines():
        if line.strip().startswith("--"):
            continue
        buff.append(line)
        if line.strip().endswith(";"):
            chunk = "\n".join(buff).strip()
            if chunk:
                chunks.append(chunk)
            buff = []
    rest = "\n".join(buff).strip()
    if rest:
        chunks.append(rest)
    return chunks


def main() -> int:
    args = parse_args()
    migrations = sorted(_resolve_root_path(args.migrations_dir).glob("*.sql"))
    if not migrations:
        print("No migration files found.")
        return 0

    engine = create_engine(args.database_url, future=True)
    with engine.begin() as conn:
        for migration in migrations:
            sql_text = migration.read_text(encoding="utf-8")
            statements = split_sql(sql_text)
            print(f"Applying {migration} ({len(statements)} statements)")
            for stmt in statements:
                conn.execute(text(stmt))

    print("Timescale migrations completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
