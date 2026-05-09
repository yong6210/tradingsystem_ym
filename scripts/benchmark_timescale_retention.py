#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Sequence

from sqlalchemy import Connection, create_engine, text

# Allow running the script directly from repository root without editable install.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.db.base import Base


TARGET_TABLES = ("candles", "zone_outcomes")


def _resolve_root_path(raw_path: str | Path) -> Path:
    path = Path(raw_path).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


@dataclass(frozen=True)
class LatencyStats:
    p50_ms: float
    p95_ms: float
    max_ms: float


@dataclass(frozen=True)
class PolicyJobResult:
    proc_name: str
    table_name: str
    job_id: int
    duration_seconds: float
    status: str
    error: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark Timescale load and long-retention policy runtime"
    )
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
        "--symbol-prefix",
        default="BMK",
        help="Benchmark symbol prefix",
    )
    parser.add_argument(
        "--symbol-count",
        type=int,
        default=30,
        help="Number of synthetic symbols",
    )
    parser.add_argument(
        "--candle-days",
        type=int,
        default=90,
        help="Days of candles per symbol/timeframe",
    )
    parser.add_argument(
        "--outcome-days",
        type=int,
        default=220,
        help="Days covered by synthetic outcomes",
    )
    parser.add_argument(
        "--outcomes-per-symbol",
        type=int,
        default=2000,
        help="Synthetic zone_outcomes rows per symbol",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="Bulk insert batch size",
    )
    parser.add_argument(
        "--query-repeats",
        type=int,
        default=30,
        help="Latency measurement repetitions per query",
    )
    parser.add_argument(
        "--candle-retention-days",
        type=int,
        default=75,
        help="Retention policy horizon for candles",
    )
    parser.add_argument(
        "--outcome-retention-days",
        type=int,
        default=150,
        help="Retention policy horizon for zone_outcomes",
    )
    parser.add_argument(
        "--min-candle-throughput-rps",
        type=float,
        default=6000.0,
        help="WARN threshold for candle insert throughput rows/s",
    )
    parser.add_argument(
        "--min-outcome-throughput-rps",
        type=float,
        default=4000.0,
        help="WARN threshold for outcome insert throughput rows/s",
    )
    parser.add_argument(
        "--max-recent-query-p95-ms",
        type=float,
        default=120.0,
        help="WARN threshold for recent-candle query p95 latency",
    )
    parser.add_argument(
        "--max-aggregate-query-p95-ms",
        type=float,
        default=260.0,
        help="WARN threshold for aggregate query p95 latency",
    )
    parser.add_argument(
        "--max-scanner-query-p95-ms",
        type=float,
        default=180.0,
        help="WARN threshold for scanner query p95 latency",
    )
    parser.add_argument(
        "--max-compression-seconds",
        type=float,
        default=120.0,
        help="WARN threshold for total compression job runtime",
    )
    parser.add_argument(
        "--max-retention-seconds",
        type=float,
        default=120.0,
        help="WARN threshold for total retention job runtime",
    )
    parser.add_argument(
        "--strict-thresholds",
        action="store_true",
        help="Return non-zero when WARN thresholds are exceeded",
    )
    parser.add_argument(
        "--reset-target",
        action="store_true",
        help="Truncate candles/zone_outcomes before benchmark load",
    )
    return parser.parse_args()


def split_sql(sql_text: str) -> list[str]:
    statements: list[str] = []
    chunk: list[str] = []
    for line in sql_text.splitlines():
        if line.strip().startswith("--"):
            continue
        chunk.append(line)
        if line.strip().endswith(";"):
            stmt = "\n".join(chunk).strip()
            if stmt:
                statements.append(stmt)
            chunk = []
    tail = "\n".join(chunk).strip()
    if tail:
        statements.append(tail)
    return statements


def find_migrations(migrations_dir: str | Path) -> list[Path]:
    return sorted(_resolve_root_path(migrations_dir).glob("*.sql"))


def apply_migrations(conn: Connection, migrations: Sequence[Path]) -> list[tuple[str, int]]:
    applied: list[tuple[str, int]] = []
    for path in migrations:
        statements = split_sql(path.read_text(encoding="utf-8"))
        for stmt in statements:
            conn.execute(text(stmt))
        applied.append((path.name, len(statements)))
    return applied


def _format_symbol_prefix(prefix: str, now_utc: datetime) -> str:
    safe = "".join(ch for ch in prefix.upper() if ch.isalnum())[:10] or "BMK"
    return f"{safe}_{now_utc.strftime('%m%d%H%M')}_"


def _build_symbols(prefix: str, count: int) -> list[str]:
    return [f"{prefix}{idx:02d}"[:30] for idx in range(count)]


def _steps_for_days(days: int, tf_minutes: int) -> int:
    return max(1, (days * 24 * 60) // tf_minutes)


def _iter_candle_rows(
    symbols: Sequence[str],
    *,
    start_utc: datetime,
    days: int,
    created_at: datetime,
) -> Iterable[dict]:
    for symbol_idx, symbol in enumerate(symbols):
        for timeframe, tf_minutes, tf_shift in (("5m", 5, 0.0), ("15m", 15, 0.8)):
            total_steps = _steps_for_days(days, tf_minutes)
            ts = start_utc
            delta = timedelta(minutes=tf_minutes)
            for step in range(total_steps):
                trend = step * 0.015
                cycle = ((step % 17) - 8) * 0.028
                base = 100.0 + symbol_idx * 2.3 + tf_shift + trend + cycle
                close_move = (((step + symbol_idx) % 7) - 3) * 0.012
                o = round(base, 6)
                c = round(base + close_move, 6)
                h = round(max(o, c) + 0.06 + (step % 3) * 0.004, 6)
                l = round(min(o, c) - 0.06 - (step % 2) * 0.003, 6)
                v = round(1200.0 + (step % 40) * 11.0 + symbol_idx * 3.0, 6)
                yield {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "ts": ts,
                    "o": o,
                    "h": h,
                    "l": l,
                    "c": c,
                    "v": v,
                    "source": "timescale_benchmark",
                    "created_at": created_at,
                }
                ts += delta


def _iter_outcome_rows(
    symbols: Sequence[str],
    *,
    now_utc: datetime,
    outcome_days: int,
    outcomes_per_symbol: int,
) -> Iterable[dict]:
    span_minutes = max(1, outcome_days * 24 * 60)
    step_minutes = max(1, span_minutes // max(outcomes_per_symbol, 1))
    window_start = now_utc - timedelta(minutes=span_minutes)
    model_cycle = ("LIMIT", "CONFIRM", "SWEEP_CONFIRM")

    for symbol_idx, symbol in enumerate(symbols):
        for idx in range(outcomes_per_symbol):
            entry_ts = window_start + timedelta(minutes=idx * step_minutes)
            touch_ts = entry_ts - timedelta(minutes=5)
            base_price = 90.0 + symbol_idx * 1.8 + (idx % 50) * 0.07
            mfe_atr = round(0.35 + (idx % 12) * 0.12, 6)
            mae_atr = round(0.20 + (idx % 9) * 0.07, 6)
            yield {
                "zone_id": f"{symbol}_zone_{idx:06d}",
                "symbol": symbol,
                "touch_ts": touch_ts,
                "entry_model_used": model_cycle[idx % len(model_cycle)],
                "entry_ts": entry_ts,
                "entry_price": round(base_price, 6),
                "sl_price": round(base_price - 1.1, 6),
                "tp1": round(base_price + 0.9, 6),
                "tp2": round(base_price + 1.8, 6),
                "tp3": round(base_price + 2.7, 6),
                "mfe_atr": mfe_atr,
                "mae_atr": mae_atr,
                "mfe_pct": round(mfe_atr * 0.9, 6),
                "mae_pct": round(mae_atr * 0.9, 6),
                "hit_1r": (idx % 10) < 7,
                "hit_2r": (idx % 10) < 4,
                "hit_3r": (idx % 10) < 2,
                "sweep_detected": (idx % 8) == 0,
                "sweep_success": (idx % 16) == 0,
                "friction_at_touch": round(0.12 + (idx % 11) * 0.04, 6),
                "regime_at_touch": round(0.15 + (idx % 10) * 0.07, 6),
                "strategy_version": "benchmark_v1",
            }


def _bulk_insert(
    conn: Connection,
    *,
    statement: str,
    rows: Iterable[dict],
    batch_size: int,
    commit_each_batch: bool = False,
) -> tuple[int, float]:
    query = text(statement)
    inserted = 0
    t0 = time.perf_counter()
    batch: list[dict] = []

    for row in rows:
        batch.append(row)
        if len(batch) >= batch_size:
            conn.execute(query, batch)
            inserted += len(batch)
            if commit_each_batch:
                conn.commit()
            batch = []

    if batch:
        conn.execute(query, batch)
        inserted += len(batch)
        if commit_each_batch:
            conn.commit()

    elapsed = time.perf_counter() - t0
    return inserted, elapsed


def _percentile(values: Sequence[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    lower = int(math.floor(pos))
    upper = int(math.ceil(pos))
    if lower == upper:
        return ordered[lower]
    frac = pos - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * frac


def _measure_query_latency(
    conn: Connection,
    *,
    query: str,
    params: dict,
    repeats: int,
) -> LatencyStats:
    stmt = text(query)
    elapsed_ms: list[float] = []
    for _ in range(max(1, repeats)):
        start = time.perf_counter()
        conn.execute(stmt, params).all()
        elapsed_ms.append((time.perf_counter() - start) * 1000.0)
    return LatencyStats(
        p50_ms=round(_percentile(elapsed_ms, 0.50), 3),
        p95_ms=round(_percentile(elapsed_ms, 0.95), 3),
        max_ms=round(max(elapsed_ms), 3),
    )


def _row_counts(conn: Connection, symbol_like: str) -> dict[str, int]:
    candles = int(
        conn.execute(
            text("SELECT COUNT(*) FROM candles WHERE symbol LIKE :symbol_like"),
            {"symbol_like": symbol_like},
        ).scalar_one()
    )
    outcomes = int(
        conn.execute(
            text("SELECT COUNT(*) FROM zone_outcomes WHERE symbol LIKE :symbol_like"),
            {"symbol_like": symbol_like},
        ).scalar_one()
    )
    return {"candles": candles, "zone_outcomes": outcomes}


def _chunk_stats(conn: Connection) -> dict[str, tuple[int, int]]:
    rows = conn.execute(
        text(
            """
            SELECT hypertable_name, COUNT(*)::bigint AS total_chunks,
                   COALESCE(SUM(CASE WHEN is_compressed THEN 1 ELSE 0 END), 0)::bigint AS compressed_chunks
            FROM timescaledb_information.chunks
            WHERE hypertable_name IN ('candles', 'zone_outcomes')
            GROUP BY hypertable_name
            """
        )
    ).all()
    stats = {name: (int(total), int(compressed)) for name, total, compressed in rows}
    for name in TARGET_TABLES:
        stats.setdefault(name, (0, 0))
    return stats


def _configure_retention_policy(
    conn: Connection,
    *,
    candle_days: int,
    outcome_days: int,
) -> list[str]:
    messages: list[str] = []
    for table_name, days in (("candles", candle_days), ("zone_outcomes", outcome_days)):
        interval_value = f"{int(days)} days"
        try:
            conn.execute(
                text(
                    f"""
                    SELECT add_retention_policy(
                      '{table_name}',
                      CAST(:interval_value AS INTERVAL),
                      if_not_exists => TRUE
                    )
                    """
                ),
                {"interval_value": interval_value},
            )
            messages.append(f"{table_name}: policy set to {interval_value}")
        except Exception as exc:  # noqa: BLE001
            messages.append(f"{table_name}: retention policy skipped ({exc})")
    return messages


def _run_policy_jobs(
    conn: Connection,
    *,
    proc_name: str,
) -> list[PolicyJobResult]:
    rows = conn.execute(
        text(
            """
            SELECT job_id, COALESCE(hypertable_name, '')
            FROM timescaledb_information.jobs
            WHERE proc_name = :proc_name
            """
        ),
        {"proc_name": proc_name},
    ).all()

    results: list[PolicyJobResult] = []
    for job_id, table_name in rows:
        if table_name not in TARGET_TABLES:
            continue
        start = time.perf_counter()
        try:
            conn.execute(text("CALL run_job(:job_id)"), {"job_id": int(job_id)})
            duration = time.perf_counter() - start
            results.append(
                PolicyJobResult(
                    proc_name=proc_name,
                    table_name=table_name,
                    job_id=int(job_id),
                    duration_seconds=round(duration, 3),
                    status="PASS",
                )
            )
        except Exception as exc:  # noqa: BLE001
            duration = time.perf_counter() - start
            results.append(
                PolicyJobResult(
                    proc_name=proc_name,
                    table_name=table_name,
                    job_id=int(job_id),
                    duration_seconds=round(duration, 3),
                    status="FAIL",
                    error=str(exc),
                )
            )
    return results


def _threshold_pass(value: float, threshold: float, *, mode: str) -> bool:
    if mode == "min":
        return value >= threshold
    if mode == "max":
        return value <= threshold
    raise ValueError(f"unknown threshold mode: {mode}")


def _write_report(
    *,
    report_path: Path,
    status: str,
    now_utc: datetime,
    database_url: str,
    benchmark_tag: str,
    symbol_count: int,
    migrations: Sequence[tuple[str, int]],
    timing: dict[str, float],
    throughputs: dict[str, float],
    query_latency: dict[str, LatencyStats],
    row_counts_before: dict[str, int],
    row_counts_after_load: dict[str, int],
    row_counts_after_policy: dict[str, int],
    chunk_before: dict[str, tuple[int, int]],
    chunk_after: dict[str, tuple[int, int]],
    retention_messages: Sequence[str],
    compression_jobs: Sequence[PolicyJobResult],
    retention_jobs: Sequence[PolicyJobResult],
    hard_checks: Sequence[tuple[str, bool, str]],
    threshold_checks: Sequence[tuple[str, bool, str]],
) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    lines.append("# Timescale Load + Retention Benchmark Report")
    lines.append("")
    lines.append(f"- Generated (UTC): {now_utc.isoformat()}")
    lines.append(f"- Database: `{database_url}`")
    lines.append(f"- Benchmark tag: `{benchmark_tag}`")
    lines.append(f"- Symbol count: `{symbol_count}`")
    lines.append(f"- Status: **{status}**")
    lines.append("")
    lines.append("## Applied Migrations")
    for name, stmt_count in migrations:
        lines.append(f"- `{name}`: {stmt_count} statements")
    lines.append("")

    lines.append("## Load Metrics")
    lines.append("| Metric | Value |")
    lines.append("| --- | ---: |")
    lines.append(f"| migration_apply_seconds | {timing['migration_apply_seconds']:.3f} |")
    lines.append(f"| candle_insert_seconds | {timing['candle_insert_seconds']:.3f} |")
    lines.append(f"| outcome_insert_seconds | {timing['outcome_insert_seconds']:.3f} |")
    lines.append(f"| candle_throughput_rows_per_sec | {throughputs['candle_rps']:.2f} |")
    lines.append(f"| outcome_throughput_rows_per_sec | {throughputs['outcome_rps']:.2f} |")
    lines.append("")

    lines.append("## Query Latency (ms)")
    lines.append("| Query | p50 | p95 | max |")
    lines.append("| --- | ---: | ---: | ---: |")
    for key, stat in query_latency.items():
        lines.append(f"| {key} | {stat.p50_ms:.3f} | {stat.p95_ms:.3f} | {stat.max_ms:.3f} |")
    lines.append("")

    lines.append("## Policy Runtime")
    if compression_jobs or retention_jobs:
        lines.append("| Policy | Table | job_id | seconds | status | detail |")
        lines.append("| --- | --- | ---: | ---: | --- | --- |")
        for job in [*compression_jobs, *retention_jobs]:
            detail = job.error.replace("|", "/") if job.error else "-"
            lines.append(
                f"| {job.proc_name} | {job.table_name} | {job.job_id} | {job.duration_seconds:.3f} | {job.status} | {detail} |"
            )
    else:
        lines.append("- No policy jobs found.")
    lines.append("")

    lines.append("## Row Counts")
    lines.append("| Table | before_load | after_load | after_policy | delta(policy) |")
    lines.append("| --- | ---: | ---: | ---: | ---: |")
    for table_name in TARGET_TABLES:
        before = row_counts_before.get(table_name, 0)
        after_load = row_counts_after_load.get(table_name, 0)
        after_policy = row_counts_after_policy.get(table_name, 0)
        lines.append(f"| {table_name} | {before} | {after_load} | {after_policy} | {after_policy - after_load} |")
    lines.append("")

    lines.append("## Chunk Stats")
    lines.append("| Table | before_total | before_compressed | after_total | after_compressed |")
    lines.append("| --- | ---: | ---: | ---: | ---: |")
    for table_name in TARGET_TABLES:
        bt, bc = chunk_before.get(table_name, (0, 0))
        at, ac = chunk_after.get(table_name, (0, 0))
        lines.append(f"| {table_name} | {bt} | {bc} | {at} | {ac} |")
    lines.append("")

    lines.append("## Retention Policy Setup")
    for msg in retention_messages:
        lines.append(f"- {msg}")
    lines.append("")

    lines.append("## Hard Checks")
    for name, passed, detail in hard_checks:
        mark = "PASS" if passed else "FAIL"
        lines.append(f"- `{name}`: {mark} ({detail})")
    lines.append("")

    lines.append("## Threshold Checks")
    for name, passed, detail in threshold_checks:
        mark = "PASS" if passed else "WARN"
        lines.append(f"- `{name}`: {mark} ({detail})")
    lines.append("")

    report_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    now_utc = datetime.now(timezone.utc).replace(microsecond=0)
    symbol_prefix = _format_symbol_prefix(args.symbol_prefix, now_utc)
    symbols = _build_symbols(symbol_prefix, args.symbol_count)
    symbol_like = f"{symbol_prefix}%"

    # Ensure model metadata is loaded before create_all.
    from app.db import models  # noqa: F401

    migrations_dir = _resolve_root_path(args.migrations_dir)
    migrations = find_migrations(migrations_dir)
    if not migrations:
        raise RuntimeError(f"no SQL migration files in: {migrations_dir}")

    engine = create_engine(args.database_url, future=True)

    migration_started = time.perf_counter()
    with engine.begin() as conn:
        Base.metadata.create_all(bind=conn)
        applied_migrations = apply_migrations(conn, migrations)
        if args.reset_target:
            conn.execute(text("TRUNCATE TABLE zone_outcomes, candles RESTART IDENTITY"))
    migration_elapsed = time.perf_counter() - migration_started

    row_counts_before: dict[str, int]
    row_counts_after_load: dict[str, int]
    row_counts_after_policy: dict[str, int]
    chunk_before: dict[str, tuple[int, int]]
    chunk_after: dict[str, tuple[int, int]]

    candle_inserted = 0
    outcome_inserted = 0
    candle_elapsed = 0.0
    outcome_elapsed = 0.0
    retention_messages: list[str] = []

    candle_stmt = """
        INSERT INTO candles (
          symbol, timeframe, ts, o, h, l, c, v, source, is_final, created_at
        )
        VALUES (
          :symbol, :timeframe, :ts, :o, :h, :l, :c, :v, :source, TRUE, :created_at
        )
        ON CONFLICT (symbol, timeframe, ts) DO UPDATE
        SET o = EXCLUDED.o,
            h = EXCLUDED.h,
            l = EXCLUDED.l,
            c = EXCLUDED.c,
            v = EXCLUDED.v,
            source = EXCLUDED.source,
            is_final = EXCLUDED.is_final,
            created_at = EXCLUDED.created_at
    """
    outcome_stmt = """
        INSERT INTO zone_outcomes (
          zone_id, symbol, touch_ts, entry_model_used, entry_ts, entry_price,
          sl_price, tp1, tp2, tp3,
          mfe_atr, mae_atr, mfe_pct, mae_pct,
          hit_1r, hit_2r, hit_3r,
          sweep_detected, sweep_success, friction_at_touch, regime_at_touch, strategy_version
        )
        VALUES (
          :zone_id, :symbol, :touch_ts, :entry_model_used, :entry_ts, :entry_price,
          :sl_price, :tp1, :tp2, :tp3,
          :mfe_atr, :mae_atr, :mfe_pct, :mae_pct,
          :hit_1r, :hit_2r, :hit_3r,
          :sweep_detected, :sweep_success, :friction_at_touch, :regime_at_touch, :strategy_version
        )
    """

    with engine.connect() as conn:
        row_counts_before = _row_counts(conn, symbol_like)

        candle_inserted, candle_elapsed = _bulk_insert(
            conn,
            statement=candle_stmt,
            rows=_iter_candle_rows(
                symbols,
                start_utc=now_utc - timedelta(days=args.candle_days),
                days=args.candle_days,
                created_at=now_utc,
            ),
            batch_size=args.batch_size,
            commit_each_batch=True,
        )

        outcome_inserted, outcome_elapsed = _bulk_insert(
            conn,
            statement=outcome_stmt,
            rows=_iter_outcome_rows(
                symbols,
                now_utc=now_utc,
                outcome_days=args.outcome_days,
                outcomes_per_symbol=args.outcomes_per_symbol,
            ),
            batch_size=args.batch_size,
            commit_each_batch=True,
        )
        conn.commit()
        row_counts_after_load = _row_counts(conn, symbol_like)
        chunk_before = _chunk_stats(conn)

    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        retention_messages = _configure_retention_policy(
            conn,
            candle_days=args.candle_retention_days,
            outcome_days=args.outcome_retention_days,
        )
        compression_jobs = _run_policy_jobs(conn, proc_name="policy_compression")
        retention_jobs = _run_policy_jobs(conn, proc_name="policy_retention")

    with engine.begin() as conn:
        row_counts_after_policy = _row_counts(conn, symbol_like)
        chunk_after = _chunk_stats(conn)

        anchor_symbol = symbols[0]
        query_latency = {
            "recent_5m_symbol": _measure_query_latency(
                conn,
                query="""
                    SELECT ts, o, h, l, c, v
                    FROM candles
                    WHERE symbol = :symbol AND timeframe = '5m'
                    ORDER BY ts DESC
                    LIMIT 300
                """,
                params={"symbol": anchor_symbol},
                repeats=args.query_repeats,
            ),
            "daily_aggregate_5m": _measure_query_latency(
                conn,
                query="""
                    SELECT time_bucket('1 day', ts) AS bucket, AVG(c) AS avg_close, SUM(v) AS total_vol
                    FROM candles
                    WHERE symbol = :symbol
                      AND timeframe = '5m'
                      AND ts >= :since_ts
                    GROUP BY bucket
                    ORDER BY bucket DESC
                    LIMIT 90
                """,
                params={"symbol": anchor_symbol, "since_ts": now_utc - timedelta(days=90)},
                repeats=args.query_repeats,
            ),
            "scanner_latest_5m": _measure_query_latency(
                conn,
                query="""
                    SELECT symbol, MAX(ts) AS latest_ts
                    FROM candles
                    WHERE symbol LIKE :symbol_like
                      AND timeframe = '5m'
                    GROUP BY symbol
                    ORDER BY latest_ts DESC
                    LIMIT :limit_rows
                """,
                params={"symbol_like": symbol_like, "limit_rows": args.symbol_count},
                repeats=args.query_repeats,
            ),
            "outcome_summary": _measure_query_latency(
                conn,
                query="""
                    SELECT
                      COUNT(*) AS trades,
                      AVG(mfe_atr) AS avg_mfe_atr,
                      AVG(mae_atr) AS avg_mae_atr,
                      AVG(CASE WHEN hit_1r THEN 1.0 ELSE 0.0 END) AS p1r
                    FROM zone_outcomes
                    WHERE symbol = :symbol
                      AND entry_ts >= :since_ts
                """,
                params={"symbol": anchor_symbol, "since_ts": now_utc - timedelta(days=180)},
                repeats=args.query_repeats,
            ),
        }

        ext_version = conn.execute(
            text("SELECT extversion FROM pg_extension WHERE extname = 'timescaledb'")
        ).scalar_one_or_none()
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

    expected_candle_rows = args.symbol_count * (
        _steps_for_days(args.candle_days, 5) + _steps_for_days(args.candle_days, 15)
    )
    expected_outcome_rows = args.symbol_count * args.outcomes_per_symbol

    candle_rps = candle_inserted / candle_elapsed if candle_elapsed > 0 else 0.0
    outcome_rps = outcome_inserted / outcome_elapsed if outcome_elapsed > 0 else 0.0

    compression_total_seconds = sum(job.duration_seconds for job in compression_jobs)
    retention_total_seconds = sum(job.duration_seconds for job in retention_jobs)
    retention_deleted_candles = row_counts_after_load["candles"] - row_counts_after_policy["candles"]
    retention_deleted_outcomes = row_counts_after_load["zone_outcomes"] - row_counts_after_policy["zone_outcomes"]

    hard_checks: list[tuple[str, bool, str]] = [
        ("timescaledb_extension", ext_version is not None, str(ext_version or "missing")),
        (
            "hypertable_candles",
            "candles" in hypertables,
            f"present={'candles' in hypertables}",
        ),
        (
            "hypertable_zone_outcomes",
            "zone_outcomes" in hypertables,
            f"present={'zone_outcomes' in hypertables}",
        ),
        (
            "candles_insert_count",
            row_counts_after_load["candles"] >= expected_candle_rows,
            f"expected>={expected_candle_rows}, got={row_counts_after_load['candles']}",
        ),
        (
            "zone_outcomes_insert_count",
            row_counts_after_load["zone_outcomes"] >= expected_outcome_rows,
            f"expected>={expected_outcome_rows}, got={row_counts_after_load['zone_outcomes']}",
        ),
        (
            "compression_jobs_executed",
            any(job.status == "PASS" for job in compression_jobs),
            f"jobs={len(compression_jobs)}",
        ),
        (
            "retention_jobs_executed",
            any(job.status == "PASS" for job in retention_jobs),
            f"jobs={len(retention_jobs)}",
        ),
    ]

    threshold_checks: list[tuple[str, bool, str]] = [
        (
            "candle_throughput_rows_per_sec",
            _threshold_pass(candle_rps, args.min_candle_throughput_rps, mode="min"),
            f"value={candle_rps:.2f}, min={args.min_candle_throughput_rps:.2f}",
        ),
        (
            "outcome_throughput_rows_per_sec",
            _threshold_pass(outcome_rps, args.min_outcome_throughput_rps, mode="min"),
            f"value={outcome_rps:.2f}, min={args.min_outcome_throughput_rps:.2f}",
        ),
        (
            "recent_query_p95_ms",
            _threshold_pass(
                query_latency["recent_5m_symbol"].p95_ms,
                args.max_recent_query_p95_ms,
                mode="max",
            ),
            f"value={query_latency['recent_5m_symbol'].p95_ms:.3f}, max={args.max_recent_query_p95_ms:.3f}",
        ),
        (
            "aggregate_query_p95_ms",
            _threshold_pass(
                query_latency["daily_aggregate_5m"].p95_ms,
                args.max_aggregate_query_p95_ms,
                mode="max",
            ),
            f"value={query_latency['daily_aggregate_5m'].p95_ms:.3f}, max={args.max_aggregate_query_p95_ms:.3f}",
        ),
        (
            "scanner_query_p95_ms",
            _threshold_pass(
                query_latency["scanner_latest_5m"].p95_ms,
                args.max_scanner_query_p95_ms,
                mode="max",
            ),
            f"value={query_latency['scanner_latest_5m'].p95_ms:.3f}, max={args.max_scanner_query_p95_ms:.3f}",
        ),
        (
            "compression_total_seconds",
            _threshold_pass(
                compression_total_seconds,
                args.max_compression_seconds,
                mode="max",
            ),
            f"value={compression_total_seconds:.3f}, max={args.max_compression_seconds:.3f}",
        ),
        (
            "retention_total_seconds",
            _threshold_pass(
                retention_total_seconds,
                args.max_retention_seconds,
                mode="max",
            ),
            f"value={retention_total_seconds:.3f}, max={args.max_retention_seconds:.3f}",
        ),
        (
            "retention_deleted_rows",
            retention_deleted_candles > 0 and retention_deleted_outcomes > 0,
            f"candles_deleted={retention_deleted_candles}, outcomes_deleted={retention_deleted_outcomes}",
        ),
    ]

    has_hard_fail = any(not passed for _, passed, _ in hard_checks)
    has_warn = any(not passed for _, passed, _ in threshold_checks)

    if has_hard_fail:
        status = "FAIL"
    elif has_warn:
        status = "WARN"
    else:
        status = "PASS"

    report_path = _resolve_root_path(
        args.report_path or f"reports/timescale/benchmark_{now_utc.strftime('%Y%m%d_%H%M%S')}.md"
    )
    _write_report(
        report_path=report_path,
        status=status,
        now_utc=now_utc,
        database_url=args.database_url,
        benchmark_tag=symbol_prefix.rstrip("_"),
        symbol_count=args.symbol_count,
        migrations=applied_migrations,
        timing={
            "migration_apply_seconds": migration_elapsed,
            "candle_insert_seconds": candle_elapsed,
            "outcome_insert_seconds": outcome_elapsed,
        },
        throughputs={
            "candle_rps": candle_rps,
            "outcome_rps": outcome_rps,
        },
        query_latency=query_latency,
        row_counts_before=row_counts_before,
        row_counts_after_load=row_counts_after_load,
        row_counts_after_policy=row_counts_after_policy,
        chunk_before=chunk_before,
        chunk_after=chunk_after,
        retention_messages=retention_messages,
        compression_jobs=compression_jobs,
        retention_jobs=retention_jobs,
        hard_checks=hard_checks,
        threshold_checks=threshold_checks,
    )

    print(f"Timescale load/retention benchmark: {status}")
    print(f"Report: {report_path}")
    print(
        f"Candle rows inserted={candle_inserted} ({candle_rps:.2f} rows/s), "
        f"Outcome rows inserted={outcome_inserted} ({outcome_rps:.2f} rows/s)"
    )
    print(
        f"Retention deleted candles={retention_deleted_candles}, "
        f"zone_outcomes={retention_deleted_outcomes}"
    )
    if status == "FAIL":
        return 1
    if status == "WARN" and args.strict_thresholds:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
