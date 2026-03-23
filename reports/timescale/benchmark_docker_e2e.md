# Timescale Load + Retention Benchmark Report

- Generated (UTC): 2026-03-04T14:41:06+00:00
- Database: `postgresql+psycopg://postgres:postgres@localhost:55432/trading`
- Benchmark tag: `BMK_03041441`
- Symbol count: `20`
- Status: **PASS**

## Applied Migrations
- `001_timescaledb_init.sql`: 13 statements

## Load Metrics
| Metric | Value |
| --- | ---: |
| migration_apply_seconds | 0.364 |
| candle_insert_seconds | 55.848 |
| outcome_insert_seconds | 1.516 |
| candle_throughput_rows_per_sec | 12376.52 |
| outcome_throughput_rows_per_sec | 19784.28 |

## Query Latency (ms)
| Query | p50 | p95 | max |
| --- | ---: | ---: | ---: |
| recent_5m_symbol | 1.201 | 1.515 | 2.573 |
| daily_aggregate_5m | 3.848 | 4.611 | 5.779 |
| scanner_latest_5m | 20.048 | 23.747 | 24.517 |
| outcome_summary | 10.992 | 15.525 | 16.064 |

## Policy Runtime
| Policy | Table | job_id | seconds | status | detail |
| --- | --- | ---: | ---: | --- | --- |
| policy_compression | candles | 1000 | 0.690 | PASS | - |
| policy_compression | zone_outcomes | 1001 | 3.745 | PASS | - |
| policy_retention | candles | 1002 | 0.004 | PASS | - |
| policy_retention | zone_outcomes | 1003 | 0.004 | PASS | - |

## Row Counts
| Table | before_load | after_load | after_policy | delta(policy) |
| --- | ---: | ---: | ---: | ---: |
| candles | 0 | 691200 | 588360 | -102840 |
| zone_outcomes | 0 | 30000 | 24060 | -5940 |

## Chunk Stats
| Table | before_total | before_compressed | after_total | after_compressed |
| --- | ---: | ---: | ---: | ---: |
| candles | 13 | 0 | 11 | 8 |
| zone_outcomes | 8 | 0 | 6 | 4 |

## Retention Policy Setup
- candles: policy set to 75 days
- zone_outcomes: policy set to 150 days

## Hard Checks
- `timescaledb_extension`: PASS (2.19.3)
- `hypertable_candles`: PASS (present=True)
- `hypertable_zone_outcomes`: PASS (present=True)
- `candles_insert_count`: PASS (expected>=691200, got=691200)
- `zone_outcomes_insert_count`: PASS (expected>=30000, got=30000)
- `compression_jobs_executed`: PASS (jobs=2)
- `retention_jobs_executed`: PASS (jobs=2)

## Threshold Checks
- `candle_throughput_rows_per_sec`: PASS (value=12376.52, min=6000.00)
- `outcome_throughput_rows_per_sec`: PASS (value=19784.28, min=4000.00)
- `recent_query_p95_ms`: PASS (value=1.515, max=120.000)
- `aggregate_query_p95_ms`: PASS (value=4.611, max=260.000)
- `scanner_query_p95_ms`: PASS (value=23.747, max=180.000)
- `compression_total_seconds`: PASS (value=4.435, max=120.000)
- `retention_total_seconds`: PASS (value=0.008, max=120.000)
- `retention_deleted_rows`: PASS (candles_deleted=102840, outcomes_deleted=5940)
