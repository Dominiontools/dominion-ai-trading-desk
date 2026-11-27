PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS oauth_states (
  state_hash TEXT PRIMARY KEY,
  created_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL,
  consumed_at INTEGER,
  access_kind TEXT NOT NULL CHECK (access_kind IN ('view-only', 'trading'))
);

CREATE INDEX IF NOT EXISTS oauth_states_expiry_idx ON oauth_states(expires_at);

CREATE TABLE IF NOT EXISTS ctrader_tokens (
  token_kind TEXT PRIMARY KEY CHECK (token_kind IN ('view-only', 'trading')),
  encrypted_record TEXT NOT NULL,
  environment TEXT NOT NULL CHECK (environment = 'demo'),
  account_id TEXT,
  updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS engine_config (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  config_json TEXT NOT NULL,
  updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS engine_status (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  status_json TEXT NOT NULL,
  updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS engine_events (
  event_id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_json TEXT NOT NULL,
  recorded_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS engine_events_recorded_idx ON engine_events(recorded_at);

CREATE TABLE IF NOT EXISTS request_nonces (
  nonce TEXT PRIMARY KEY,
  purpose TEXT NOT NULL CHECK (purpose IN ('dashboard-control', 'scheduled-worker')),
  accepted_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS request_nonces_expiry_idx ON request_nonces(expires_at);

CREATE TABLE IF NOT EXISTS execution_locks (
  lock_name TEXT PRIMARY KEY,
  lock_id TEXT NOT NULL UNIQUE,
  acquired_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS execution_locks_expiry_idx ON execution_locks(expires_at);
