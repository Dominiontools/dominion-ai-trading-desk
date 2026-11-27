PRAGMA foreign_keys = ON;

-- One recoverable position snapshot per verified demo account.
CREATE TABLE IF NOT EXISTS ctrader_active_positions (
  account_id TEXT PRIMARY KEY,
  position_id TEXT NOT NULL UNIQUE,
  position_json TEXT NOT NULL,
  updated_at INTEGER NOT NULL
);

-- A client order ID is an idempotency key. Once reserved, it can never be reused.
CREATE TABLE IF NOT EXISTS ctrader_order_intents (
  client_order_id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL,
  intent_json TEXT NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('PREPARED', 'SUBMITTED', 'FILLED', 'REJECTED', 'UNKNOWN')),
  broker_position_id TEXT,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS ctrader_order_intents_account_idx
  ON ctrader_order_intents(account_id, created_at);

CREATE TABLE IF NOT EXISTS ctrader_engine_events (
  event_id INTEGER PRIMARY KEY AUTOINCREMENT,
  account_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  event_json TEXT NOT NULL,
  recorded_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS ctrader_engine_events_account_idx
  ON ctrader_engine_events(account_id, recorded_at);
