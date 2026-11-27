const ALLOWED_STATUSES = new Set(["NOT_CONFIGURED", "DISCONNECTED", "CONNECTING", "CONNECTED", "RUNNING", "PAUSED", "ERROR"]);
const ALLOWED_REASONS = new Set([
  "ENGINE_HAS_NOT_RUN", "OAUTH_REQUIRED", "BROKER_DISCONNECTED", "ACCOUNT_NOT_VERIFIED",
  "DEMO_ACCOUNT_REQUIRED", "TRADING_PERMISSION_REQUIRED", "ENGINE_DISABLED", "RISK_BLOCKED",
  "MARKET_CLOSED", "NO_SIGNAL", "EXECUTION_LOCKED", "HEARTBEAT_STALE", "INTERNAL_ERROR"
]);

function requireDatabase(db) {
  if (!db || typeof db.prepare !== "function") throw new Error("Cloudflare D1 binding is required.");
}

function safeCount(value) {
  return Number.isSafeInteger(value) && value >= 0 && value <= 100 ? value : 0;
}

/** Validate and persist only a bounded, explicitly demo-scoped status snapshot. */
export async function saveCTraderEngineStatus(db, snapshot, nowMs = Date.now()) {
  requireDatabase(db);
  if (!snapshot || typeof snapshot !== "object" || Array.isArray(snapshot)) {
    throw new Error("A cTrader status snapshot is required.");
  }
  if (!Number.isSafeInteger(nowMs) || nowMs < 0) throw new Error("Invalid status update time.");
  const status = snapshot.status;
  const reason = snapshot.reason;
  if (!ALLOWED_STATUSES.has(status) || !ALLOWED_REASONS.has(reason)) {
    throw new Error("Unsupported cTrader status or reason.");
  }
  if (snapshot.environment !== "demo" || snapshot.liveTradingEnabled === true) {
    throw new Error("Only non-live demo status may be stored.");
  }
  const connected = snapshot.connected === true;
  const access = snapshot.access === "trading" || snapshot.access === "view-only" ? snapshot.access : "none";
  const permissionScope = snapshot.permissionScope === 1 ? 1 : 0;
  if (connected && (snapshot.isLive !== false || access === "none")) {
    throw new Error("A connected cTrader status must be verified as a demo account.");
  }
  if (access !== "trading" && permissionScope !== 0) {
    throw new Error("Trading permission scope requires trading access.");
  }
  const safe = {
    status,
    reason,
    connected,
    environment: "demo",
    access,
    permissionScope,
    demoAccountCount: safeCount(snapshot.demoAccountCount),
    liveTradingEnabled: false,
    updatedAt: Math.floor(nowMs / 1000)
  };
  await db.prepare(
    "INSERT INTO engine_status (id, status_json, updated_at) VALUES (1, ?, ?) ON CONFLICT(id) DO UPDATE SET status_json = excluded.status_json, updated_at = excluded.updated_at"
  ).bind(JSON.stringify(safe), safe.updatedAt).run();
  return safe;
}

/** Read the singleton status row and fail closed on malformed or live-looking data. */
export async function readCTraderEngineStatus(db) {
  requireDatabase(db);
  const row = await db.prepare(
    "SELECT status_json, updated_at FROM engine_status WHERE id = 1"
  ).first();
  if (!row) {
    return {
      status: "NOT_CONFIGURED",
      reason: "ENGINE_HAS_NOT_RUN",
      connected: false,
      environment: "demo",
      access: "none",
      permissionScope: 0,
      demoAccountCount: 0,
      liveTradingEnabled: false,
      updatedAt: null
    };
  }
  let stored;
  try {
    stored = JSON.parse(row.status_json);
  } catch {
    throw new Error("Stored cTrader engine status is invalid.");
  }
  if (!stored || typeof stored !== "object" || Array.isArray(stored) ||
      stored.environment !== "demo" || stored.liveTradingEnabled !== false ||
      !ALLOWED_STATUSES.has(stored.status) || !ALLOWED_REASONS.has(stored.reason)) {
    throw new Error("Stored cTrader engine status failed safety validation.");
  }
  const connected = stored.connected === true && stored.isLive === false &&
    (stored.access === "trading" || stored.access === "view-only");
  const access = connected ? stored.access : "none";
  const permissionScope = access === "trading" && stored.permissionScope === 1 ? 1 : 0;
  return {
    status: stored.status,
    reason: stored.reason,
    connected,
    environment: "demo",
    access,
    permissionScope,
    demoAccountCount: safeCount(stored.demoAccountCount),
    liveTradingEnabled: false,
    updatedAt: Number.isSafeInteger(row.updated_at) ? row.updated_at : null
  };
}
