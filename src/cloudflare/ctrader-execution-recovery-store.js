const encoder = new TextEncoder();

function requireDatabase(db) {
  if (!db || typeof db.prepare !== "function") throw new Error("Cloudflare D1 binding is required.");
}

function requireAccountId(value) {
  const accountId = String(value ?? "");
  if (!/^\d{1,30}$/.test(accountId)) throw new Error("A verified numeric demo account ID is required.");
  return accountId;
}

function requireTimestamp(value) {
  if (!Number.isSafeInteger(value) || value < 0) throw new Error("Invalid recovery timestamp.");
  return Math.floor(value / 1000);
}

function safeJson(value, maxBytes = 16_384) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("A JSON object is required.");
  }
  const json = JSON.stringify(value);
  if (encoder.encode(json).byteLength > maxBytes) throw new Error("Recovery record exceeds its size limit.");
  return json;
}

const TRANSITIONS = Object.freeze({
  PREPARED: new Set(["SUBMITTED", "REJECTED", "UNKNOWN"]),
  SUBMITTED: new Set(["FILLED", "REJECTED", "UNKNOWN"]),
  UNKNOWN: new Set(["FILLED", "REJECTED"]),
  FILLED: new Set(),
  REJECTED: new Set()
});

/** Atomically reserve a unique client order ID before any broker submission. */
export async function reserveCTraderOrderIntent(db, {
  accountId, clientOrderId, intent, nowMs = Date.now()
}) {
  requireDatabase(db);
  const account = requireAccountId(accountId);
  if (typeof clientOrderId !== "string" || !/^[A-Za-z0-9_-]{12,64}$/.test(clientOrderId)) {
    throw new Error("A unique client order ID is required.");
  }
  const json = safeJson(intent, 8_192);
  const now = requireTimestamp(nowMs);
  const row = await db.prepare(
    "INSERT INTO ctrader_order_intents (client_order_id, account_id, intent_json, state, broker_position_id, created_at, updated_at) VALUES (?, ?, ?, 'PREPARED', NULL, ?, ?) ON CONFLICT(client_order_id) DO NOTHING RETURNING client_order_id, account_id, state, created_at"
  ).bind(clientOrderId, account, json, now, now).first();
  if (!row) return null;
  return { clientOrderId: row.client_order_id, accountId: row.account_id, state: row.state, createdAt: row.created_at };
}

/** Advance an order intent only through the explicit fail-closed state machine. */
export async function transitionCTraderOrderIntent(db, {
  clientOrderId, accountId, fromState, toState, brokerPositionId = null,
  nowMs = Date.now()
}) {
  requireDatabase(db);
  const account = requireAccountId(accountId);
  if (typeof clientOrderId !== "string" || !/^[A-Za-z0-9_-]{12,64}$/.test(clientOrderId) ||
      !Object.hasOwn(TRANSITIONS, fromState) || !TRANSITIONS[fromState].has(toState)) {
    throw new Error("Invalid cTrader order intent transition.");
  }
  if (brokerPositionId !== null && !/^\d{1,30}$/.test(String(brokerPositionId))) {
    throw new Error("Invalid broker position ID.");
  }
  const now = requireTimestamp(nowMs);
  const row = await db.prepare(
    "UPDATE ctrader_order_intents SET state = ?, broker_position_id = COALESCE(?, broker_position_id), updated_at = ? WHERE client_order_id = ? AND account_id = ? AND state = ? RETURNING client_order_id, state, broker_position_id"
  ).bind(toState, brokerPositionId === null ? null : String(brokerPositionId), now, clientOrderId, account, fromState).first();
  if (!row) return null;
  return { clientOrderId: row.client_order_id, state: row.state, brokerPositionId: row.broker_position_id };
}

/** Save a broker-confirmed active position snapshot for restart recovery. */
export async function saveCTraderActivePosition(db, { accountId, positionId, position, nowMs = Date.now() }) {
  requireDatabase(db);
  const account = requireAccountId(accountId);
  const id = String(positionId ?? "");
  if (!/^\d{1,30}$/.test(id)) throw new Error("A valid broker position ID is required.");
  if (!position || typeof position !== "object" || Array.isArray(position) ||
      !Number.isFinite(Number(position.symbolId)) || Number(position.symbolId) <= 0 ||
      !["BUY", "SELL"].includes(String(position.side)) ||
      !Number.isFinite(Number(position.volume)) || Number(position.volume) <= 0 ||
      !Number.isFinite(Number(position.stopLoss)) || Number(position.stopLoss) <= 0 ||
      !Number.isFinite(Number(position.takeProfit)) || Number(position.takeProfit) <= 0) {
    throw new Error("A broker-confirmed position with durable volume and SL/TP protection is required.");
  }
  const json = safeJson(position);
  const now = requireTimestamp(nowMs);
  await db.prepare(
    "INSERT INTO ctrader_active_positions (account_id, position_id, position_json, updated_at) VALUES (?, ?, ?, ?) ON CONFLICT(account_id) DO UPDATE SET position_id = excluded.position_id, position_json = excluded.position_json, updated_at = excluded.updated_at"
  ).bind(account, id, json, now).run();
  return { accountId: account, positionId: id, updatedAt: now };
}

export async function readCTraderActivePosition(db, accountId) {
  requireDatabase(db);
  const account = requireAccountId(accountId);
  const row = await db.prepare(
    "SELECT position_id, position_json, updated_at FROM ctrader_active_positions WHERE account_id = ?"
  ).bind(account).first();
  if (!row) return null;
  let position;
  try { position = JSON.parse(row.position_json); }
  catch { throw new Error("Stored cTrader position snapshot is corrupt."); }
  if (!position || typeof position !== "object" || Array.isArray(position)) {
    throw new Error("Stored cTrader position snapshot is invalid.");
  }
  return { accountId: account, positionId: String(row.position_id), position, updatedAt: row.updated_at };
}

/** Delete only the exact broker position that reconciliation confirmed is closed. */
export async function clearCTraderActivePosition(db, accountId, positionId) {
  requireDatabase(db);
  const account = requireAccountId(accountId);
  const id = String(positionId ?? "");
  if (!/^\d{1,30}$/.test(id)) throw new Error("A valid broker position ID is required.");
  const result = await db.prepare(
    "DELETE FROM ctrader_active_positions WHERE account_id = ? AND position_id = ?"
  ).bind(account, id).run();
  return Number(result?.meta?.changes ?? 0) === 1;
}

export async function appendCTraderEngineEvent(db, {
  accountId, eventType, event, nowMs = Date.now()
}) {
  requireDatabase(db);
  const account = requireAccountId(accountId);
  if (typeof eventType !== "string" || !/^[A-Z][A-Z0-9_]{1,63}$/.test(eventType)) {
    throw new Error("Invalid cTrader engine event type.");
  }
  const json = safeJson(event, 4_096);
  const recordedAt = requireTimestamp(nowMs);
  await db.prepare(
    "INSERT INTO ctrader_engine_events (account_id, event_type, event_json, recorded_at) VALUES (?, ?, ?, ?)"
  ).bind(account, eventType, json, recordedAt).run();
  return { accountId: account, eventType, recordedAt };
}


/** Return every non-terminal order intent; any result blocks a fresh entry until broker reconciliation resolves it. */
export async function readUnresolvedCTraderOrderIntents(db, accountId) {
  requireDatabase(db);
  const account = requireAccountId(accountId);
  const result = await db.prepare(
    "SELECT client_order_id, intent_json, state, broker_position_id, created_at, updated_at FROM ctrader_order_intents WHERE account_id = ? AND state IN ('PREPARED', 'SUBMITTED', 'UNKNOWN') ORDER BY created_at ASC"
  ).bind(account).all();
  const rows = Array.isArray(result?.results) ? result.results : [];
  return rows.map((row) => {
    let intent;
    try { intent = JSON.parse(row.intent_json); }
    catch { throw new Error("Stored cTrader order intent is corrupt."); }
    if (!intent || typeof intent !== "object" || Array.isArray(intent)) {
      throw new Error("Stored cTrader order intent is invalid.");
    }
    return {
      clientOrderId: String(row.client_order_id),
      state: row.state,
      brokerPositionId: row.broker_position_id == null ? null : String(row.broker_position_id),
      intent,
      createdAt: row.created_at,
      updatedAt: row.updated_at
    };
  });
}
