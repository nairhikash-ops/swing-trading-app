CREATE SCHEMA IF NOT EXISTS matsya_intraday;

CREATE TABLE IF NOT EXISTS matsya_intraday.schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS matsya_intraday.ingestion_runs (
    id BIGSERIAL PRIMARY KEY,
    command TEXT NOT NULL,
    dry_run BOOLEAN NOT NULL DEFAULT false,
    requested_from DATE NOT NULL,
    requested_to DATE NOT NULL,
    universe JSONB NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running','completed','failed')),
    requests_made INTEGER NOT NULL DEFAULT 0,
    candles_fetched INTEGER NOT NULL DEFAULT 0,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS matsya_intraday.symbol_days (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT REFERENCES matsya_intraday.ingestion_runs(id),
    provider_code TEXT NOT NULL DEFAULT 'dhan',
    symbol TEXT NOT NULL,
    security_id TEXT NOT NULL,
    trading_date DATE NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('accepted','warning','rejected','unavailable')),
    candle_count INTEGER NOT NULL DEFAULT 0,
    missing_minutes INTEGER NOT NULL DEFAULT 0,
    zero_volume_minutes INTEGER NOT NULL DEFAULT 0,
    defects JSONB NOT NULL DEFAULT '[]'::jsonb,
    request_from TEXT NOT NULL,
    request_to TEXT NOT NULL,
    response_sha256 TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (provider_code, security_id, trading_date)
);

CREATE TABLE IF NOT EXISTS matsya_intraday.minute_candles (
    provider_code TEXT NOT NULL DEFAULT 'dhan',
    security_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    candle_time TIMESTAMPTZ NOT NULL,
    trading_date DATE NOT NULL,
    open_price NUMERIC NOT NULL CHECK (open_price > 0),
    high_price NUMERIC NOT NULL,
    low_price NUMERIC NOT NULL,
    close_price NUMERIC NOT NULL CHECK (close_price > 0),
    volume NUMERIC NOT NULL CHECK (volume >= 0),
    source_day_id BIGINT NOT NULL REFERENCES matsya_intraday.symbol_days(id),
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (provider_code, security_id, candle_time),
    CHECK (high_price >= GREATEST(open_price, low_price, close_price)),
    CHECK (low_price <= LEAST(open_price, high_price, close_price))
);

CREATE INDEX IF NOT EXISTS idx_intraday_minute_symbol_date
ON matsya_intraday.minute_candles(symbol, trading_date, candle_time);

CREATE TABLE IF NOT EXISTS matsya_intraday.quarantine (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT REFERENCES matsya_intraday.ingestion_runs(id),
    symbol TEXT NOT NULL,
    security_id TEXT NOT NULL,
    trading_date DATE NOT NULL,
    reasons JSONB NOT NULL,
    response_sha256 TEXT NOT NULL,
    raw_response JSONB NOT NULL,
    quarantined_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (security_id, trading_date, response_sha256)
);

CREATE TABLE IF NOT EXISTS matsya_intraday.daily_reconciliation (
    id BIGSERIAL PRIMARY KEY,
    symbol_day_id BIGINT NOT NULL REFERENCES matsya_intraday.symbol_days(id),
    symbol TEXT NOT NULL,
    security_id TEXT NOT NULL,
    trading_date DATE NOT NULL,
    intraday_open NUMERIC NOT NULL,
    intraday_high NUMERIC NOT NULL,
    intraday_low NUMERIC NOT NULL,
    last_minute_close NUMERIC NOT NULL,
    normal_session_volume NUMERIC NOT NULL,
    official_daily_open NUMERIC,
    official_daily_high NUMERIC,
    official_daily_low NUMERIC,
    official_daily_close NUMERIC,
    official_daily_volume NUMERIC,
    absolute_differences JSONB,
    percentage_differences JSONB,
    open_high_low_match BOOLEAN NOT NULL,
    close_match BOOLEAN NOT NULL,
    volume_match BOOLEAN NOT NULL,
    structural_acceptance_gate_passed BOOLEAN NOT NULL,
    cross_source_status TEXT NOT NULL CHECK (cross_source_status IN ('validated','warning','unavailable')),
    explanation TEXT NOT NULL DEFAULT '',
    reconciled_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (symbol_day_id)
);

CREATE TABLE IF NOT EXISTS matsya_intraday.derived_candles (
    provider_code TEXT NOT NULL DEFAULT 'dhan',
    security_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    interval_minutes INTEGER NOT NULL CHECK (interval_minutes IN (5,15,30,60,1440)),
    bucket_time TIMESTAMPTZ NOT NULL,
    trading_date DATE NOT NULL,
    open_price NUMERIC NOT NULL,
    high_price NUMERIC NOT NULL,
    low_price NUMERIC NOT NULL,
    close_price NUMERIC NOT NULL,
    volume NUMERIC NOT NULL,
    source_minutes INTEGER NOT NULL,
    source_day_id BIGINT NOT NULL REFERENCES matsya_intraday.symbol_days(id),
    generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (provider_code, security_id, interval_minutes, bucket_time)
);
