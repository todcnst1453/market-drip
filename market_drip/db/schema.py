"""SQLite schema definitions for market-drip."""

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS markets (
    market_pk INTEGER PRIMARY KEY,
    gamma_market_id TEXT UNIQUE NOT NULL,
    slug TEXT,
    question TEXT,
    status TEXT,
    end_ts INTEGER,
    updated_ts INTEGER
);

CREATE TABLE IF NOT EXISTS tokens (
    token_pk INTEGER PRIMARY KEY,
    clob_token_id TEXT UNIQUE NOT NULL,
    market_pk INTEGER NOT NULL REFERENCES markets(market_pk),
    outcome_name TEXT,
    is_short_cycle INTEGER NOT NULL DEFAULT 0,
    updated_ts INTEGER
);

CREATE TABLE IF NOT EXISTS prices (
    token_pk INTEGER NOT NULL REFERENCES tokens(token_pk),
    ts INTEGER NOT NULL,
    resolution INTEGER NOT NULL,
    price_bp INTEGER NOT NULL,
    PRIMARY KEY (token_pk, resolution, ts)
);

CREATE TABLE IF NOT EXISTS fetch_tasks (
    task_pk INTEGER PRIMARY KEY,
    token_pk INTEGER NOT NULL REFERENCES tokens(token_pk),
    resolution INTEGER NOT NULL,
    start_ts INTEGER NOT NULL,
    end_ts INTEGER NOT NULL,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    next_run_at INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    updated_at INTEGER NOT NULL,
    UNIQUE (token_pk, resolution, start_ts, end_ts)
);

CREATE TABLE IF NOT EXISTS run_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""