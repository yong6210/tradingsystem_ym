#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import Connection, create_engine, text

# Allow running the script directly from repository root without editable install.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.db.base import Base


def _resolve_root_path(raw_path: str | Path) -> Path:
    path = Path(raw_path).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify Timescale runtime end-to-end")
    parser.add_argument("--database-url", required=True, help="PostgreSQL DSN")
    parser.add_argument(
        "--migrations-dir",
        default="scripts/migrations",
        help="Directory containing .sql migrations",
    )
    parser.add_argument(
        "--report-path",
        default="",
        help="Optional markdown report output path",
    )
    parser.add_argument(
        "--seed-symbol",
        default="BTCUSDC",
        help="Symbol used for write/read smoke checks",
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


def find_migrations(migrations_dir: str | Path) -> list[Path]:
    return sorted(_resolve_root_path(migrations_dir).glob("*.sql"))


def apply_migrations(conn: Connection, migrations: list[Path]) -> list[tuple[str, int]]:
    applied: list[tuple[str, int]] = []
    for migration in migrations:
        sql_text = migration.read_text(encoding="utf-8")
        statements = split_sql(sql_text)
        for stmt in statements:
            conn.execute(text(stmt))
        applied.append((migration.name, len(statements)))
    return applied


def _upsert_seed_rows(conn: Connection, symbol: str, now_utc: datetime) -> None:
    conn.execute(
        text(
            """
            INSERT INTO candles (symbol, timeframe, ts, o, h, l, c, v, source, is_final, created_at)
            VALUES (:symbol, '5m', :ts, 100.0, 101.0, 99.5, 100.5, 1234.5, 'timescale_verify', TRUE, :ts)
            ON CONFLICT (symbol, timeframe, ts) DO UPDATE
            SET c = EXCLUDED.c, v = EXCLUDED.v, source = EXCLUDED.source
            """
        ),
        {"symbol": symbol, "ts": now_utc},
    )
    conn.execute(
        text(
            """
            INSERT INTO zone_outcomes (
              zone_id, symbol, touch_ts, entry_model_used, entry_ts, entry_price,
              sl_price, tp1, tp2, tp3,
              mfe_atr, mae_atr, mfe_pct, mae_pct,
              hit_1r, hit_2r, hit_3r,
              sweep_detected, sweep_success, friction_at_touch, regime_at_touch, strategy_version
            )
            VALUES (
              :zone_id, :symbol, :ts, 'CONFIRM', :ts, 100.5,
              99.0, 101.5, 102.5, 103.5,
              0.8, 0.4, 1.2, 0.6,
              TRUE, FALSE, FALSE,
              FALSE, FALSE, 0.2, 0.4, 'v1'
            )
            """
        ),
        {
            "zone_id": f"verify_zone_{now_utc.strftime('%Y%m%d%H%M%S')}",
            "symbol": symbol,
            "ts": now_utc,
        },
    )
    old_candle_ts = now_utc.replace(microsecond=0) - timedelta(days=40)
    old_outcome_ts = now_utc.replace(microsecond=0) - timedelta(days=70)
    conn.execute(
        text(
            """
            INSERT INTO candles (symbol, timeframe, ts, o, h, l, c, v, source, is_final, created_at)
            VALUES (:symbol, '5m', :ts, 90.0, 91.0, 89.5, 90.5, 2222.2, 'timescale_verify_old', TRUE, :ts)
            ON CONFLICT (symbol, timeframe, ts) DO UPDATE
            SET c = EXCLUDED.c, v = EXCLUDED.v, source = EXCLUDED.source
            """
        ),
        {"symbol": symbol, "ts": old_candle_ts},
    )
    conn.execute(
        text(
            """
            INSERT INTO zone_outcomes (
              zone_id, symbol, touch_ts, entry_model_used, entry_ts, entry_price,
              sl_price, tp1, tp2, tp3,
              mfe_atr, mae_atr, mfe_pct, mae_pct,
              hit_1r, hit_2r, hit_3r,
              sweep_detected, sweep_success, friction_at_touch, regime_at_touch, strategy_version
            )
            VALUES (
              :zone_id, :symbol, :ts, 'CONFIRM', :ts, 90.5,
              88.0, 91.5, 92.5, 93.5,
              1.1, 0.6, 1.8, 0.9,
              TRUE, TRUE, FALSE,
              FALSE, FALSE, 0.3, 0.5, 'v1'
            )
            """
        ),
        {
            "zone_id": f"verify_zone_old_{now_utc.strftime('%Y%m%d%H%M%S')}",
            "symbol": symbol,
            "ts": old_outcome_ts,
        },
    )


def _run_compression_jobs(conn: Connection) -> dict[str, str]:
    results: dict[str, str] = {}
    rows = conn.execute(
        text(
            """
            SELECT job_id, COALESCE(hypertable_name, '')
            FROM timescaledb_information.jobs
            WHERE proc_name = 'policy_compression'
            """
        )
    ).all()
    for job_id, table_name in rows:
        label = table_name or f"job_{job_id}"
        conn.execute(text("CALL run_job(:job_id)"), {"job_id": int(job_id)})
        results[label] = f"job_id={job_id}"
    return results


def _collect_checks(conn: Connection, symbol: str) -> tuple[dict[str, bool], dict[str, str]]:
    checks: dict[str, bool] = {}
    details: dict[str, str] = {}

    ext_version = conn.execute(
        text("SELECT extversion FROM pg_extension WHERE extname='timescaledb'")
    ).scalar_one_or_none()
    checks["timescaledb_extension"] = ext_version is not None
    details["timescaledb_extension"] = ext_version or "missing"

    hypertables = {
        row[0]
        for row in conn.execute(
            text(
                """
                SELECT hypertable_name
                FROM timescaledb_information.hypertables
                WHERE hypertable_name IN ('candles', 'zone_outcomes')
                """
            )
        ).all()
    }
    for table_name in ("candles", "zone_outcomes"):
        key = f"hypertable_{table_name}"
        checks[key] = table_name in hypertables
        details[key] = "ok" if checks[key] else "missing"

    policy_rows = conn.execute(
        text(
            """
            SELECT COALESCE(hypertable_name, '')
            FROM timescaledb_information.jobs
            WHERE proc_name = 'policy_compression'
            """
        )
    ).all()
    policy_tables = {row[0] for row in policy_rows if row[0]}
    for table_name in ("candles", "zone_outcomes"):
        key = f"compression_policy_{table_name}"
        checks[key] = table_name in policy_tables
        details[key] = "ok" if checks[key] else "missing"

    candle_count = conn.execute(
        text("SELECT COUNT(*) FROM candles WHERE symbol = :symbol"),
        {"symbol": symbol},
    ).scalar_one()
    checks["write_read_candles"] = candle_count > 0
    details["write_read_candles"] = f"rows={candle_count}"

    outcome_count = conn.execute(
        text("SELECT COUNT(*) FROM zone_outcomes WHERE symbol = :symbol"),
        {"symbol": symbol},
    ).scalar_one()
    checks["write_read_zone_outcomes"] = outcome_count > 0
    details["write_read_zone_outcomes"] = f"rows={outcome_count}"

    chunk_rows = conn.execute(
        text(
            """
            SELECT hypertable_name, COUNT(*), SUM(CASE WHEN is_compressed THEN 1 ELSE 0 END)
            FROM timescaledb_information.chunks
            WHERE hypertable_name IN ('candles', 'zone_outcomes')
            GROUP BY hypertable_name
            """
        )
    ).all()
    chunk_map = {name: (int(total), int(compressed)) for name, total, compressed in chunk_rows}
    for table_name in ("candles", "zone_outcomes"):
        key = f"chunks_{table_name}"
        total_chunks = chunk_map.get(table_name, (0, 0))[0]
        checks[key] = total_chunks > 0
        details[key] = f"chunks={total_chunks}"

        compressed_key = f"compressed_chunks_{table_name}"
        compressed_chunks = chunk_map.get(table_name, (0, 0))[1]
        checks[compressed_key] = compressed_chunks > 0
        details[compressed_key] = f"compressed_chunks={compressed_chunks}"

    return checks, details


def write_report(
    *,
    report_path: Path,
    status: str,
    database_url: str,
    migrations: list[tuple[str, int]],
    checks: dict[str, bool],
    details: dict[str, str],
    now_utc: datetime,
) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    lines.append("# Timescale Runtime Validation Report")
    lines.append("")
    lines.append(f"- Generated (UTC): {now_utc.isoformat()}")
    lines.append(f"- Database: `{database_url}`")
    lines.append(f"- Status: **{status}**")
    lines.append("")
    lines.append("## Applied Migrations")
    for name, stmt_count in migrations:
        lines.append(f"- `{name}`: {stmt_count} statements")
    lines.append("")
    lines.append("## Checks")
    for key in sorted(checks):
        mark = "PASS" if checks[key] else "FAIL"
        lines.append(f"- `{key}`: {mark} ({details.get(key, 'n/a')})")
    lines.append("")
    report_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    now_utc = datetime.now(timezone.utc).replace(microsecond=0)

    # Ensure model metadata is loaded before create_all.
    from app.db import models  # noqa: F401

    migrations_dir = _resolve_root_path(args.migrations_dir)
    migrations = find_migrations(migrations_dir)
    if not migrations:
        raise RuntimeError(f"no SQL migration files in: {migrations_dir}")

    engine = create_engine(args.database_url, future=True)
    with engine.begin() as conn:
        Base.metadata.create_all(bind=conn)
        applied = apply_migrations(conn, migrations)
        _upsert_seed_rows(conn, symbol=args.seed_symbol, now_utc=now_utc)

    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        job_runs = _run_compression_jobs(conn)

    with engine.begin() as conn:
        checks, details = _collect_checks(conn, symbol=args.seed_symbol)
        for table_name, info in job_runs.items():
            details[f"compression_job_run_{table_name}"] = info

    status = "PASS" if all(checks.values()) else "FAIL"
    report_path = _resolve_root_path(
        args.report_path or f"reports/timescale/validation_{now_utc.strftime('%Y%m%d_%H%M%S')}.md"
    )
    write_report(
        report_path=report_path,
        status=status,
        database_url=args.database_url,
        migrations=applied,
        checks=checks,
        details=details,
        now_utc=now_utc,
    )

    print(f"Timescale runtime validation: {status}")
    print(f"Report: {report_path}")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
