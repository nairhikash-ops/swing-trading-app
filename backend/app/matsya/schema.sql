CREATE SCHEMA IF NOT EXISTS matsya;

CREATE TABLE IF NOT EXISTS matsya.providers (
    id BIGSERIAL PRIMARY KEY,
    provider_code TEXT NOT NULL UNIQUE,
    provider_name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO matsya.providers (provider_code, provider_name)
VALUES ('dhan', 'Dhan')
ON CONFLICT (provider_code) DO UPDATE
SET provider_name = EXCLUDED.provider_name,
    updated_at = now();

CREATE TABLE IF NOT EXISTS matsya.raw_import_runs (
    id BIGSERIAL PRIMARY KEY,
    provider_code TEXT NOT NULL REFERENCES matsya.providers(provider_code),
    import_type TEXT NOT NULL,
    source_name TEXT NOT NULL DEFAULT '',
    source_url TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    total_rows_seen INTEGER NOT NULL DEFAULT 0,
    inserted_rows INTEGER NOT NULL DEFAULT 0,
    updated_rows INTEGER NOT NULL DEFAULT 0,
    unchanged_rows INTEGER NOT NULL DEFAULT 0,
    skipped_rows INTEGER NOT NULL DEFAULT 0,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_matsya_raw_import_runs_type
ON matsya.raw_import_runs(provider_code, import_type, started_at DESC);

CREATE TABLE IF NOT EXISTS matsya.raw_import_errors (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT REFERENCES matsya.raw_import_runs(id) ON DELETE SET NULL,
    provider_code TEXT NOT NULL REFERENCES matsya.providers(provider_code),
    source_ref TEXT NOT NULL DEFAULT '',
    error_type TEXT NOT NULL,
    error_message TEXT NOT NULL,
    raw_payload JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS matsya.raw_dhan_responses (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT REFERENCES matsya.raw_import_runs(id) ON DELETE SET NULL,
    endpoint_name TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    request_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    response_hash TEXT NOT NULL DEFAULT '',
    response_json JSONB,
    response_text_ref TEXT NOT NULL DEFAULT '',
    status_code INTEGER,
    error_message TEXT NOT NULL DEFAULT '',
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_matsya_raw_dhan_responses_endpoint
ON matsya.raw_dhan_responses(endpoint_name, fetched_at DESC);

CREATE TABLE IF NOT EXISTS matsya.dhan_profile_snapshots (
    id BIGSERIAL PRIMARY KEY,
    provider_code TEXT NOT NULL DEFAULT 'dhan' REFERENCES matsya.providers(provider_code),
    dhan_client_id TEXT NOT NULL DEFAULT '',
    access_token_hash TEXT NOT NULL,
    profile_json JSONB NOT NULL,
    profile_hash TEXT NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (provider_code, access_token_hash, profile_hash)
);

CREATE TABLE IF NOT EXISTS matsya.dhan_token_renewal_runs (
    id BIGSERIAL PRIMARY KEY,
    provider_code TEXT NOT NULL DEFAULT 'dhan' REFERENCES matsya.providers(provider_code),
    dhan_client_id TEXT NOT NULL,
    previous_access_token_hash TEXT NOT NULL,
    renewed_access_token_hash TEXT NOT NULL DEFAULT '',
    response_json JSONB,
    response_hash TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    error_message TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS matsya.instruments (
    id BIGSERIAL PRIMARY KEY,
    provider_code TEXT NOT NULL DEFAULT 'dhan' REFERENCES matsya.providers(provider_code),
    natural_key TEXT NOT NULL,
    row_hash TEXT NOT NULL,
    exchange_id TEXT NOT NULL DEFAULT '',
    segment TEXT NOT NULL DEFAULT '',
    security_id TEXT NOT NULL DEFAULT '',
    isin TEXT NOT NULL DEFAULT '',
    instrument TEXT NOT NULL DEFAULT '',
    underlying_security_id TEXT NOT NULL DEFAULT '',
    underlying_symbol TEXT NOT NULL DEFAULT '',
    symbol_name TEXT NOT NULL DEFAULT '',
    display_name TEXT NOT NULL DEFAULT '',
    instrument_type TEXT NOT NULL DEFAULT '',
    series TEXT NOT NULL DEFAULT '',
    lot_size NUMERIC,
    expiry_date TEXT NOT NULL DEFAULT '',
    strike_price NUMERIC,
    option_type TEXT NOT NULL DEFAULT '',
    tick_size NUMERIC,
    raw_row JSONB NOT NULL,
    active BOOLEAN NOT NULL DEFAULT true,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_import_run_id BIGINT REFERENCES matsya.raw_import_runs(id),
    UNIQUE (provider_code, natural_key)
);

CREATE INDEX IF NOT EXISTS idx_matsya_instruments_security
ON matsya.instruments(provider_code, security_id);

CREATE INDEX IF NOT EXISTS idx_matsya_instruments_symbol
ON matsya.instruments(symbol_name);

CREATE INDEX IF NOT EXISTS idx_matsya_instruments_exchange_active
ON matsya.instruments(exchange_id, segment, active);

CREATE TABLE IF NOT EXISTS matsya.market_universe_members (
    id BIGSERIAL PRIMARY KEY,
    provider_code TEXT NOT NULL DEFAULT 'nse' REFERENCES matsya.providers(provider_code),
    universe_name TEXT NOT NULL,
    natural_key TEXT NOT NULL,
    row_hash TEXT NOT NULL,
    company_name TEXT NOT NULL DEFAULT '',
    industry TEXT NOT NULL DEFAULT '',
    symbol TEXT NOT NULL DEFAULT '',
    series TEXT NOT NULL DEFAULT '',
    isin TEXT NOT NULL DEFAULT '',
    raw_row JSONB NOT NULL,
    active BOOLEAN NOT NULL DEFAULT true,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_import_run_id BIGINT REFERENCES matsya.raw_import_runs(id),
    UNIQUE (universe_name, natural_key)
);

INSERT INTO matsya.providers (provider_code, provider_name)
VALUES ('nse', 'National Stock Exchange of India')
ON CONFLICT (provider_code) DO UPDATE
SET provider_name = EXCLUDED.provider_name,
    updated_at = now();

CREATE INDEX IF NOT EXISTS idx_matsya_universe_active
ON matsya.market_universe_members(universe_name, active);

CREATE INDEX IF NOT EXISTS idx_matsya_universe_symbol
ON matsya.market_universe_members(symbol);

CREATE TABLE IF NOT EXISTS matsya.ohlcv_daily (
    id BIGSERIAL PRIMARY KEY,
    provider_code TEXT NOT NULL DEFAULT 'dhan' REFERENCES matsya.providers(provider_code),
    security_id TEXT NOT NULL,
    exchange_segment TEXT NOT NULL DEFAULT '',
    instrument TEXT NOT NULL DEFAULT '',
    trading_date DATE NOT NULL,
    source_timestamp BIGINT,
    open_price NUMERIC NOT NULL,
    high_price NUMERIC NOT NULL,
    low_price NUMERIC NOT NULL,
    close_price NUMERIC NOT NULL,
    volume NUMERIC NOT NULL,
    open_interest NUMERIC,
    raw_candle JSONB NOT NULL,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_import_run_id BIGINT REFERENCES matsya.raw_import_runs(id),
    UNIQUE (provider_code, security_id, trading_date)
);

CREATE INDEX IF NOT EXISTS idx_matsya_ohlcv_security_date
ON matsya.ohlcv_daily(provider_code, security_id, trading_date DESC);

