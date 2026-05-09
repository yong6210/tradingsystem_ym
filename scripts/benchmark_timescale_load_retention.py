#!/usr/bin/env python3
from __future__ import annotations

import argparse
import statistics
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import Connection, create_engine, text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.db.base import Base


def _resolve_root_path(raw_path: str | Path) -> Path:
    path = Path(raw_path).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


@dataclass(slots=True)
class TimedMetric:
    name: str
    seconds: float
    success: bool = True
    detail: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark Timescale load + long-retention scenario")
    parser.add_argument("--database-url", required=True, help="PostgreSQL DSN")
    parser.add_argument("--migrations-dir", default="scripts/migrations", help="Directory containing .sql migrations")
    parser.add_argument("--report-path", default="", help="Optional markdown report output path")
    parser.add_argument("--symbols", type=int, default=12, help="Number of synthetic symbols")
    parser.add_argument("--days", type=int, default=150, help="History days to insert")
    parser.add_argument("--seed-prefix", default="LOAD", help="Synthetic symbol prefix")
    parser.add_argument(
        "--outcome-step-minutes",
        type=int,
        default=60,
        help="Interval in minutes for synthetic zone_outcomes rows",
    )
    parser.add_argument(
        "--retention-days",
        type=int,
        default=90,
        help="drop_chunks older-than days for retention simulation",
    )
    parser.add_argument(
        "--query-runs",
        type=int,
        default=5,
        help="Repeat count for latency measurements",
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
            stmt = "\n".join(buff).strip()
            if stmt:
                chunks.append(stmt)
            buff = []
    rest = "\n".join(buff).strip()
    if rest:
        chunks.append(rest)
    return chunks


def find_migrations(migrations_dir: str | Path) -> list[Path]:
    return sorted(_resolve_root_path(migrations_dir).glob("*.sql"))


def apply_migrations(conn: Connection, migration_paths: list[Path]) -> list[tuple[str, int]]:
    applied: list[tuple[str, int]] = []
    for migration in migration_paths:
        sql_text = migration.read_text(encoding="utf-8")
        statements = split_sql(sql_text)
        for stmt in statements:
            conn.execute(text(stmt))
        applied.append((migration.name, len(statements)))
    return applied


def synthetic_symbols(prefix: str, count: int) -> list[str]:
    return [f"{prefix}{i:02d}USDC" for i in range(1, count + 1)]


def _seconds(start: float) -> float:
    return round(time.perf_counter() - start, 6)


def insert_candles_for_symbol(
    conn: Connection,
    *,
    symbol: str,
    now_utc: datetime,
    days: int,
) -> tuple[int, int]:
    start_ts = now_utc - timedelta(days=days)
    candle_5m_stmt = text(
        """
        INSERT INTO candles (symbol, timeframe, ts, o, h, l, c, v, source, is_final, created_at)
        SELECT
          :symbol,
          '5m',
          gs,
          100.0 + ((EXTRACT(EPOCH FROM gs)::BIGINT % 2000) / 100.0),
          101.0 + ((EXTRACT(EPOCH FROM gs)::BIGINT % 2100) / 100.0),
          99.0 + ((EXTRACT(EPOCH FROM gs)::BIGINT % 1900) / 100.0),
          100.5 + ((EXTRACT(EPOCH FROM gs)::BIGINT % 2000) / 100.0),
          500.0 + ((EXTRACT(EPOCH FROM gs)::BIGINT % 1200) / 10.0),
          'timescale_bench',
          TRUE,
          gs
        FROM generate_series(:start_ts, :end_ts, INTERVAL '5 minute') AS gs
        ON CONFLICT (symbol, timeframe, ts) DO NOTHING
        """
    )
    candle_15m_stmt = text(
        """
        INSERT INTO candles (symbol, timeframe, ts, o, h, l, c, v, source, is_final, created_at)
        SELECT
          :symbol,
          '15m',
          gs,
          100.0 + ((EXTRACT(EPOCH FROM gs)::BIGINT % 2000) / 100.0),
          101.0 + ((EXTRACT(EPOCH FROM gs)::BIGINT % 2100) / 100.0),
          99.0 + ((EXTRACT(EPOCH FROM gs)::BIGINT % 1900) / 100.0),
          100.5 + ((EXTRACT(EPOCH FROM gs)::BIGINT % 2000) / 100.0),
          650.0 + ((EXTRACT(EPOCH FROM gs)::BIGINT % 1600) / 10.0),
          'timescale_bench',
          TRUE,
          gs
        FROM generate_series(:start_ts, :end_ts, INTERVAL '15 minute') AS gs
        ON CONFLICT (symbol, timeframe, ts) DO NOTHING
        """
    )

    params = {
        "symbol": symbol,
        "start_ts": start_ts,
        "end_ts": now_utc,
    }
    inserted_5m = int(conn.execute(candle_5m_stmt, params).rowcount or 0)
    inserted_15m = int(conn.execute(candle_15m_stmt, params).rowcount or 0)
    return inserted_5m, inserted_15m


def insert_outcomes_for_symbol(
    conn: Connection,
    *,
    symbol: str,
    now_utc: datetime,
    days: int,
    step_minutes: int,
) -> int:
    start_ts = now_utc - timedelta(days=days)
    stmt = text(
        """
        INSERT INTO zone_outcomes (
          zone_id, symbol, touch_ts, entry_model_used, entry_ts, entry_price,
          sl_price, tp1, tp2, tp3,
          mfe_atr, mae_atr, mfe_pct, mae_pct,
          hit_1r, hit_2r, hit_3r,
          sweep_detected, sweep_success, friction_at_touch, regime_at_touch, strategy_version
        )
        SELECT
          :symbol || '_zone_' || TO_CHAR(gs, 'YYYYMMDDHH24MI'),
          :symbol,
          gs,
          'CONFIRM',
          gs,
          100.0 + ((EXTRACT(EPOCH FROM gs)::BIGINT % 2000) / 100.0),
          99.0,
          101.0,
          102.0,
          103.0,
          1.0,
          0.5,
          1.2,
          0.8,
          CASE WHEN EXTRACT(HOUR FROM gs)::INT % 3 = 0 THEN TRUE ELSE FALSE END,
          CASE WHEN EXTRACT(HOUR FROM gs)::INT % 5 = 0 THEN TRUE ELSE FALSE END,
          CASE WHEN EXTRACT(HOUR FROM gs)::INT % 9 = 0 THEN TRUE ELSE FALSE END,
          FALSE,
          FALSE,
          0.3,
          0.5,
          'v1'
        FROM generate_series(
          :start_ts,
          :end_ts,
          CAST(:step_minutes || ' minute' AS INTERVAL)
        ) AS gs
        """
    )
    params = {
        "symbol": symbol,
        "start_ts": start_ts,
        "end_ts": now_utc,
        "step_minutes": max(1, step_minutes),
    }
    return int(conn.execute(stmt, params).rowcount or 0)


def latency_samples(conn: Connection, stmt, params: dict, runs: int) -> list[float]:
    values: list[float] = []
    for _ in range(max(1, runs)):
        begin = time.perf_counter()
        conn.execute(stmt, params).all()
        values.append(_seconds(begin))
    return values


def avg_seconds(values: list[float]) -> float:
    if not values:
        return 0.0
    return round(statistics.fmean(values), 6)


def p95_seconds(values: list[float]) -> float:
    if not values:
        return 0.0
    values_sorted = sorted(values)
    idx = min(len(values_sorted) - 1, int(round(0.95 * (len(values_sorted) - 1))))
    return round(values_sorted[idx], 6)


def relation_size_bytes(conn: Connection, table_name: str) -> int:
    if table_name in {"candles", "zone_outcomes"}:
        value = conn.execute(
            text(f"SELECT COALESCE(total_bytes, 0) FROM hypertable_detailed_size('{table_name}')")  # noqa: S608
        ).scalar_one_or_none()
        return int(value or 0)
    value = conn.execute(text("SELECT pg_total_relation_size(to_regclass(:table_name))"), {"table_name": table_name}).scalar_one()
    return int(value or 0)


def table_row_count(conn: Connection, table_name: str) -> int:
    if table_name not in {"candles", "zone_outcomes"}:
        raise RuntimeError(f"unsupported table_name for row count: {table_name}")
    value = conn.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar_one()  # noqa: S608
    return int(value or 0)


def run_compression_jobs(conn: Connection) -> list[TimedMetric]:
    rows = conn.execute(
        text(
            """
            SELECT job_id, COALESCE(hypertable_name, '')
            FROM timescaledb_information.jobs
            WHERE proc_name = 'policy_compression'
            ORDER BY job_id
            """
        )
    ).all()
    metrics: list[TimedMetric] = []
    for job_id, table_name in rows:
        label = table_name or f"job_{job_id}"
        begin = time.perf_counter()
        try:
            conn.execute(text("CALL run_job(:job_id)"), {"job_id": int(job_id)})
            metrics.append(
                TimedMetric(
                    name=f"compression_job_{label}",
                    seconds=_seconds(begin),
                    success=True,
                    detail=f"job_id={int(job_id)}",
                )
            )
        except Exception as exc:
            metrics.append(
                TimedMetric(
                    name=f"compression_job_{label}",
                    seconds=_seconds(begin),
                    success=False,
                    detail=exc.__class__.__name__,
                )
            )
    return metrics


def run_manual_compression(conn: Connection) -> list[TimedMetric]:
    config: list[tuple[str, str]] = [
        ("candles", "14 days"),
        ("zone_outcomes", "30 days"),
    ]
    metrics: list[TimedMetric] = []
    for table_name, older_than in config:
        begin = time.perf_counter()
        try:
            stmt = f"""
            SELECT compress_chunk(chunk_name, if_not_compressed => TRUE)
            FROM show_chunks('{table_name}', older_than => INTERVAL '{older_than}') AS chunk_name
            """  # noqa: S608
            rows = conn.execute(text(stmt)).all()
            metrics.append(
                TimedMetric(
                    name=f"manual_compress_{table_name}",
                    seconds=_seconds(begin),
                    success=True,
                    detail=f"chunks={len(rows)}",
                )
            )
        except Exception as exc:
            metrics.append(
                TimedMetric(
                    name=f"manual_compress_{table_name}",
                    seconds=_seconds(begin),
                    success=False,
                    detail=exc.__class__.__name__,
                )
            )
    return metrics


def compressed_chunk_counts(conn: Connection) -> dict[str, int]:
    rows = conn.execute(
        text(
            """
            SELECT hypertable_name, SUM(CASE WHEN is_compressed THEN 1 ELSE 0 END)
            FROM timescaledb_information.chunks
            WHERE hypertable_name IN ('candles', 'zone_outcomes')
            GROUP BY hypertable_name
            """
        )
    ).all()
    out = {"candles": 0, "zone_outcomes": 0}
    for name, compressed in rows:
        out[str(name)] = int(compressed or 0)
    return out


def run_drop_chunks(conn: Connection, retention_days: int) -> list[TimedMetric]:
    days = max(1, int(retention_days))
    statements: list[tuple[str, str]] = [
        ("drop_chunks_candles", f"SELECT drop_chunks(relation => 'candles', older_than => INTERVAL '{days} days')"),
        (
            "drop_chunks_zone_outcomes",
            f"SELECT drop_chunks(relation => 'zone_outcomes', older_than => INTERVAL '{days} days')",
        ),
    ]
    metrics: list[TimedMetric] = []
    for label, stmt in statements:
        begin = time.perf_counter()
        try:
            rows = conn.execute(text(stmt)).all()
            metrics.append(
                TimedMetric(
                    name=label,
                    seconds=_seconds(begin),
                    success=True,
                    detail=f"chunks={len(rows)}",
                )
            )
        except Exception as exc:
            metrics.append(
                TimedMetric(
                    name=label,
                    seconds=_seconds(begin),
                    success=False,
                    detail=exc.__class__.__name__,
                )
            )
    return metrics


def write_report(
    *,
    report_path: Path,
    status: str,
    database_url: str,
    now_utc: datetime,
    migrations: list[tuple[str, int]],
    scenario: dict[str, int],
    checks: dict[str, bool],
    row_counts: dict[str, int],
    row_counts_before_retention: dict[str, int],
    row_counts_after_retention: dict[str, int],
    sizes_before: dict[str, int],
    sizes_after_compression: dict[str, int],
    sizes_after_retention: dict[str, int],
    query_metrics: dict[str, dict[str, float]],
    policy_metrics: list[TimedMetric],
    manual_compression_metrics: list[TimedMetric],
    retention_metrics: list[TimedMetric],
    compressed_counts: dict[str, int],
) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    lines.append("# Timescale Load and Retention Benchmark Report")
    lines.append("")
    lines.append(f"- Generated (UTC): {now_utc.isoformat()}")
    lines.append(f"- Database: `{database_url}`")
    lines.append(f"- Status: **{status}**")
    lines.append("")

    lines.append("## Scenario")
    for key in ("symbols", "days", "retention_days", "outcome_step_minutes", "query_runs"):
        lines.append(f"- `{key}`: {scenario[key]}")
    lines.append("")

    lines.append("## Applied Migrations")
    for name, stmt_count in migrations:
        lines.append(f"- `{name}`: {stmt_count} statements")
    lines.append("")

    lines.append("## Checks")
    for key in sorted(checks):
        mark = "PASS" if checks[key] else "FAIL"
        lines.append(f"- `{key}`: {mark}")
    lines.append("")

    lines.append("## Inserted Rows")
    for key in ("candles_5m", "candles_15m", "candles_total", "zone_outcomes"):
        lines.append(f"- `{key}`: {row_counts.get(key, 0)}")
    lines.append("")

    lines.append("## Query Latency")
    for name in sorted(query_metrics):
        m = query_metrics[name]
        lines.append(
            f"- `{name}`: avg={m['avg_seconds']}s, p95={m['p95_seconds']}s, runs={int(m['runs'])}"
        )
    lines.append("")

    lines.append("## Policy Runtime")
    for metric in policy_metrics:
        mark = "ok" if metric.success else "error"
        suffix = f", detail={metric.detail}" if metric.detail else ""
        lines.append(f"- `{metric.name}`: {metric.seconds}s ({mark}{suffix})")
    if not policy_metrics:
        lines.append("- `compression_jobs`: none")
    for metric in manual_compression_metrics:
        mark = "ok" if metric.success else "error"
        suffix = f", detail={metric.detail}" if metric.detail else ""
        lines.append(f"- `{metric.name}`: {metric.seconds}s ({mark}{suffix})")
    for metric in retention_metrics:
        mark = "ok" if metric.success else "error"
        suffix = f", detail={metric.detail}" if metric.detail else ""
        lines.append(f"- `{metric.name}`: {metric.seconds}s ({mark}{suffix})")
    lines.append("")

    lines.append("## Compression and Retention Effect")
    for table in ("candles", "zone_outcomes"):
        lines.append(
            f"- `{table}` row_count: before_retention={row_counts_before_retention.get(table, 0)}, "
            f"after_retention={row_counts_after_retention.get(table, 0)}"
        )
        lines.append(
            f"- `{table}` size bytes: before={sizes_before.get(table, 0)}, "
            f"after_compression={sizes_after_compression.get(table, 0)}, "
            f"after_retention={sizes_after_retention.get(table, 0)}"
        )
        lines.append(f"- `{table}` compressed_chunks: {compressed_counts.get(table, 0)}")
    lines.append("")

    report_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    now_utc = datetime.now(timezone.utc).replace(microsecond=0)

    if args.symbols < 1:
        raise RuntimeError("--symbols must be >= 1")
    if args.days < 1:
        raise RuntimeError("--days must be >= 1")

    from app.db import models  # noqa: F401

    migrations_dir = _resolve_root_path(args.migrations_dir)
    migrations = find_migrations(migrations_dir)
    if not migrations:
        raise RuntimeError(f"no SQL migration files in: {migrations_dir}")

    scenario = {
        "symbols": int(args.symbols),
        "days": int(args.days),
        "retention_days": int(args.retention_days),
        "outcome_step_minutes": int(args.outcome_step_minutes),
        "query_runs": int(args.query_runs),
    }

    symbols = synthetic_symbols(args.seed_prefix, args.symbols)
    row_counts = {
        "candles_5m": 0,
        "candles_15m": 0,
        "candles_total": 0,
        "zone_outcomes": 0,
    }

    engine = create_engine(args.database_url, future=True)
    with engine.begin() as conn:
        Base.metadata.create_all(bind=conn)
        applied = apply_migrations(conn, migrations)

        for symbol in symbols:
            c5, c15 = insert_candles_for_symbol(conn, symbol=symbol, now_utc=now_utc, days=args.days)
            row_counts["candles_5m"] += c5
            row_counts["candles_15m"] += c15
            row_counts["candles_total"] += c5 + c15

            outcomes = insert_outcomes_for_symbol(
                conn,
                symbol=symbol,
                now_utc=now_utc,
                days=args.days,
                step_minutes=args.outcome_step_minutes,
            )
            row_counts["zone_outcomes"] += outcomes

        conn.execute(text("ANALYZE candles"))
        conn.execute(text("ANALYZE zone_outcomes"))

    with engine.begin() as conn:
        query_metrics: dict[str, dict[str, float]] = {}
        sample_symbol = symbols[0]

        recent_plan_query = text(
            """
            SELECT ts, c
            FROM candles
            WHERE symbol = :symbol AND timeframe = '5m'
            ORDER BY ts DESC
            LIMIT 300
            """
        )
        recent_samples = latency_samples(conn, recent_plan_query, {"symbol": sample_symbol}, args.query_runs)
        query_metrics["recent_300bars"] = {
            "avg_seconds": avg_seconds(recent_samples),
            "p95_seconds": p95_seconds(recent_samples),
            "runs": float(len(recent_samples)),
        }

        window_scan_query = text(
            """
            SELECT symbol, COUNT(*)
            FROM candles
            WHERE timeframe = '5m' AND ts >= :cutoff
            GROUP BY symbol
            ORDER BY COUNT(*) DESC
            LIMIT 30
            """
        )
        for window_days in (7, 30, 90):
            cutoff = now_utc - timedelta(days=window_days)
            samples = latency_samples(conn, window_scan_query, {"cutoff": cutoff}, args.query_runs)
            query_metrics[f"scanner_window_{window_days}d"] = {
                "avg_seconds": avg_seconds(samples),
                "p95_seconds": p95_seconds(samples),
                "runs": float(len(samples)),
            }

        outcome_query = text(
            """
            SELECT symbol, COUNT(*)
            FROM zone_outcomes
            WHERE entry_ts >= :cutoff
            GROUP BY symbol
            ORDER BY COUNT(*) DESC
            LIMIT 30
            """
        )
        outcome_samples = latency_samples(
            conn,
            outcome_query,
            {"cutoff": now_utc - timedelta(days=90)},
            args.query_runs,
        )
        query_metrics["outcome_90d_aggregation"] = {
            "avg_seconds": avg_seconds(outcome_samples),
            "p95_seconds": p95_seconds(outcome_samples),
            "runs": float(len(outcome_samples)),
        }

        sizes_before = {
            "candles": relation_size_bytes(conn, "candles"),
            "zone_outcomes": relation_size_bytes(conn, "zone_outcomes"),
        }

    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        policy_metrics = run_compression_jobs(conn)
        manual_compression_metrics = run_manual_compression(conn)

    with engine.begin() as conn:
        compressed_counts = compressed_chunk_counts(conn)
        sizes_after_compression = {
            "candles": relation_size_bytes(conn, "candles"),
            "zone_outcomes": relation_size_bytes(conn, "zone_outcomes"),
        }
        row_counts_before_retention = {
            "candles": table_row_count(conn, "candles"),
            "zone_outcomes": table_row_count(conn, "zone_outcomes"),
        }

    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        retention_metrics = run_drop_chunks(conn, args.retention_days)

    with engine.begin() as conn:
        sizes_after_retention = {
            "candles": relation_size_bytes(conn, "candles"),
            "zone_outcomes": relation_size_bytes(conn, "zone_outcomes"),
        }
        row_counts_after_retention = {
            "candles": table_row_count(conn, "candles"),
            "zone_outcomes": table_row_count(conn, "zone_outcomes"),
        }

    checks = {
        "candles_inserted": row_counts["candles_total"] > 0,
        "outcomes_inserted": row_counts["zone_outcomes"] > 0,
        "compression_execution_succeeded": any(item.success for item in policy_metrics + manual_compression_metrics),
        "compressed_chunks_present": compressed_counts.get("candles", 0) > 0,
        "retention_calls_succeeded": all(item.success for item in retention_metrics),
        "retention_reduced_or_equal_candles_rows": row_counts_after_retention["candles"]
        <= row_counts_before_retention["candles"],
        "retention_reduced_or_equal_outcomes_rows": row_counts_after_retention["zone_outcomes"]
        <= row_counts_before_retention["zone_outcomes"],
    }

    expected_retention_drop = args.days > args.retention_days
    if expected_retention_drop:
        checks["retention_dropped_candles_rows"] = row_counts_after_retention["candles"] < row_counts_before_retention["candles"]
        checks["retention_dropped_outcomes_rows"] = (
            row_counts_after_retention["zone_outcomes"] < row_counts_before_retention["zone_outcomes"]
        )

    status = "PASS" if all(checks.values()) else "FAIL"
    report_path = _resolve_root_path(
        args.report_path or f"reports/timescale/load_retention_{now_utc.strftime('%Y%m%d_%H%M%S')}.md"
    )

    write_report(
        report_path=report_path,
        status=status,
        database_url=args.database_url,
        now_utc=now_utc,
        migrations=applied,
        scenario=scenario,
        checks=checks,
        row_counts=row_counts,
        row_counts_before_retention=row_counts_before_retention,
        row_counts_after_retention=row_counts_after_retention,
        sizes_before=sizes_before,
        sizes_after_compression=sizes_after_compression,
        sizes_after_retention=sizes_after_retention,
        query_metrics=query_metrics,
        policy_metrics=policy_metrics,
        manual_compression_metrics=manual_compression_metrics,
        retention_metrics=retention_metrics,
        compressed_counts=compressed_counts,
    )

    print(f"Timescale load/retention benchmark: {status}")
    print(f"Report: {report_path}")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
