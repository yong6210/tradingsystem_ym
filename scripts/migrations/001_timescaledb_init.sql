-- Trading Engine v1 TimescaleDB bootstrap
-- Run on PostgreSQL with TimescaleDB extension installed.

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Timescale requires every UNIQUE index (including PK) to include partition column.
-- Rebuild PKs to include time columns before hypertable conversion.
ALTER TABLE candles DROP CONSTRAINT IF EXISTS candles_pkey;
ALTER TABLE candles ADD CONSTRAINT candles_pkey PRIMARY KEY (id, ts);

ALTER TABLE zone_outcomes DROP CONSTRAINT IF EXISTS zone_outcomes_pkey;
ALTER TABLE zone_outcomes ADD CONSTRAINT zone_outcomes_pkey PRIMARY KEY (id, entry_ts);

-- Candles as primary hypertable.
SELECT create_hypertable(
  'candles',
  'ts',
  if_not_exists => TRUE,
  migrate_data => TRUE,
  chunk_time_interval => INTERVAL '7 days'
);

CREATE INDEX IF NOT EXISTS ix_candles_symbol_tf_ts_desc
  ON candles (symbol, timeframe, ts DESC);

-- Outcomes as secondary hypertable for validation analytics.
SELECT create_hypertable(
  'zone_outcomes',
  'entry_ts',
  if_not_exists => TRUE,
  migrate_data => TRUE,
  chunk_time_interval => INTERVAL '30 days'
);

CREATE INDEX IF NOT EXISTS ix_zone_outcomes_symbol_entry_desc
  ON zone_outcomes (symbol, entry_ts DESC);

-- Compression policies (optional in dev).
ALTER TABLE candles SET (
  timescaledb.compress,
  timescaledb.compress_segmentby = 'symbol,timeframe'
);
SELECT add_compression_policy('candles', INTERVAL '14 days', if_not_exists => TRUE);

ALTER TABLE zone_outcomes SET (
  timescaledb.compress,
  timescaledb.compress_segmentby = 'symbol,zone_id'
);
SELECT add_compression_policy('zone_outcomes', INTERVAL '30 days', if_not_exists => TRUE);
