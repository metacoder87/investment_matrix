-- Enable TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Hypertables for time-series data
CREATE TABLE prices (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL, -- Increased length for normalized symbols
    timestamp TIMESTAMPTZ NOT NULL,
    open DECIMAL, high DECIMAL, low DECIMAL, close DECIMAL, volume DECIMAL
);
SELECT create_hypertable('prices', 'timestamp', chunk_time_interval => INTERVAL '1 day');
ALTER TABLE prices SET (
  timescaledb.compress,
  timescaledb.compress_segmentby = 'symbol',
  timescaledb.compress_orderby = 'timestamp'
);
SELECT add_compression_policy('prices', compress_after => INTERVAL '2 hours');

CREATE TABLE indicators (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    rsi DECIMAL, macd DECIMAL, -- etc. for 50+ fields
    INDEX idx_symbol_time (symbol, timestamp DESC)
);
SELECT create_hypertable('indicators', 'timestamp', chunk_time_interval => INTERVAL '1 day');

CREATE TABLE trades (
    id SERIAL PRIMARY KEY,
    user_id UUID NOT NULL,
    symbol VARCHAR(20),
    action VARCHAR(4), -- BUY/SELL
    qty DECIMAL, price DECIMAL, fee DECIMAL,
    timestamp TIMESTAMPTZ DEFAULT NOW()
);

-- For storing encrypted wallet mnemonics
CREATE TABLE wallets (
    user_id UUID PRIMARY KEY,
    encrypted_mnemonic TEXT,
    addresses JSONB
);

-- Continuous aggregates for instant OHLCV data
CREATE MATERIALIZED VIEW candles_1m
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 minute', timestamp) as bucket,
    symbol,
    first(close, timestamp) as open,
    max(close) as high,
    min(close) as low,
    last(close, timestamp) as close,
    sum(volume) as volume
FROM prices
GROUP BY bucket, symbol;

SELECT add_continuous_aggregate_policy('candles_1m',
    start_offset => INTERVAL '1 hour',
    end_offset => INTERVAL '1 minute',
    schedule_interval => INTERVAL '1 minute');
