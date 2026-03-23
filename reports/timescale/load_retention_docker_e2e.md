# Timescale Load and Retention Benchmark Report

- Generated (UTC): 2026-03-04T14:39:03+00:00
- Database: `postgresql+psycopg://postgres:postgres@localhost:55433/trading`
- Status: **PASS**

## Scenario
- `symbols`: 12
- `days`: 150
- `retention_days`: 90
- `outcome_step_minutes`: 60
- `query_runs`: 5

## Applied Migrations
- `001_timescaledb_init.sql`: 13 statements

## Checks
- `candles_inserted`: PASS
- `compressed_chunks_present`: PASS
- `compression_execution_succeeded`: PASS
- `outcomes_inserted`: PASS
- `retention_calls_succeeded`: PASS
- `retention_dropped_candles_rows`: PASS
- `retention_dropped_outcomes_rows`: PASS
- `retention_reduced_or_equal_candles_rows`: PASS
- `retention_reduced_or_equal_outcomes_rows`: PASS

## Inserted Rows
- `candles_5m`: 518412
- `candles_15m`: 172812
- `candles_total`: 691224
- `zone_outcomes`: 43212

## Query Latency
- `outcome_90d_aggregation`: avg=0.005538s, p95=0.008382s, runs=5
- `recent_300bars`: avg=0.004535s, p95=0.011971s, runs=5
- `scanner_window_30d`: avg=0.015295s, p95=0.019569s, runs=5
- `scanner_window_7d`: avg=0.004965s, p95=0.006384s, runs=5
- `scanner_window_90d`: avg=0.026958s, p95=0.037927s, runs=5

## Policy Runtime
- `compression_job_candles`: 0.9409s (error, detail=ProgrammingError)
- `compression_job_zone_outcomes`: 4.005529s (error, detail=ProgrammingError)
- `manual_compress_candles`: 0.00224s (ok, detail=chunks=19)
- `manual_compress_zone_outcomes`: 0.001072s (ok, detail=chunks=4)
- `drop_chunks_candles`: 0.021059s (ok, detail=chunks=9)
- `drop_chunks_zone_outcomes`: 0.007517s (ok, detail=chunks=2)

## Compression and Retention Effect
- `candles` row_count: before_retention=691224, after_retention=417540
- `candles` size bytes: before=240689152, after_compression=39460864, after_retention=36552704
- `candles` compressed_chunks: 19
- `zone_outcomes` row_count: before_retention=43212, after_retention=33588
- `zone_outcomes` size bytes: before=20381696, after_compression=64856064, after_retention=44122112
- `zone_outcomes` compressed_chunks: 4
