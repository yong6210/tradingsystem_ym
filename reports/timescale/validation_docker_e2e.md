# Timescale Runtime Validation Report

- Generated (UTC): 2026-03-04T14:20:42+00:00
- Database: `postgresql+psycopg://postgres:postgres@localhost:55432/trading`
- Status: **PASS**

## Applied Migrations
- `001_timescaledb_init.sql`: 13 statements

## Checks
- `chunks_candles`: PASS (chunks=2)
- `chunks_zone_outcomes`: PASS (chunks=2)
- `compressed_chunks_candles`: PASS (compressed_chunks=1)
- `compressed_chunks_zone_outcomes`: PASS (compressed_chunks=1)
- `compression_policy_candles`: PASS (ok)
- `compression_policy_zone_outcomes`: PASS (ok)
- `hypertable_candles`: PASS (ok)
- `hypertable_zone_outcomes`: PASS (ok)
- `timescaledb_extension`: PASS (2.19.3)
- `write_read_candles`: PASS (rows=2)
- `write_read_zone_outcomes`: PASS (rows=2)
