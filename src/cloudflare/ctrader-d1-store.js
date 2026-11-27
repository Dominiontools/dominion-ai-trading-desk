const encoder = new TextEncoder();

async function sha256Hex(value) {
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", encoder.encode(value)));
  return [...digest].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

function requireDatabase(db) {
  if (!db || typeof db.prepare !== "function") {
    throw new Error("Cloudflare D1 binding is required.");
  }
}

function requireAccessKind(value) {
  if (value !== "view-only" && value !== "trading") {
    throw new Error("Unsupported cTrader access kind.");
  }
}

/**
 * D1 persistence primitives for cTrader OAuth state and encrypted token records.
 * The caller must supply an existing D1 binding; this module never creates resources.
 */
export async function createOAuthState(db, state, accessKind, nowMs = Date.now(), ttlMs = 600_000) {
  requireDatabase(db);
  requireAccessKind(accessKind);
  if (typeof state !== "string" || state.length < 32 || state.length > 512) {
    throw new Error("OAuth state must be a high-entropy string.");
  }
  if (!Number.isSafeInteger(nowMs) || !Number.isSafeInteger(ttlMs) || ttlMs < 1 || ttlMs > 600_000) {
    throw new Error("Invalid OAuth state lifetime.");
  }
  const stateHash = await sha256Hex(state);
  await db.prepare(
    "INSERT INTO oauth_states (state_hash, created_at, expires_at, consumed_at, access_kind) VALUES (?, ?, ?, NULL, ?)",
  ).bind(stateHash, Math.floor(nowMs / 1000), Math.floor((nowMs + ttlMs) / 1000), accessKind).run();
  return { expiresAt: Math.floor((nowMs + ttlMs) / 1000) };
}

/** Atomically consumes a valid, unexpired OAuth state exactly once. */
export async function consumeOAuthState(db, state, nowMs = Date.now()) {
  requireDatabase(db);
  if (typeof state !== "string" || state.length < 32 || state.length > 512) return null;
  if (!Number.isSafeInteger(nowMs)) throw new Error("Invalid current time.");
  const stateHash = await sha256Hex(state);
  const row = await db.prepare(
    "UPDATE oauth_states SET consumed_at = ? WHERE state_hash = ? AND consumed_at IS NULL AND expires_at > ? RETURNING access_kind, expires_at",
  ).bind(Math.floor(nowMs / 1000), stateHash, Math.floor(nowMs / 1000)).first();
  if (!row) return null;
  return { accessKind: row.access_kind, expiresAt: row.expires_at };
}

export async function saveEncryptedCTraderToken(db, tokenKind, record, accountId, nowMs = Date.now()) {
  requireDatabase(db);
  requireAccessKind(tokenKind);
  if (!record || record.version !== 1 || record.algorithm !== "aes-256-gcm" ||
      typeof record.iv !== "string" || typeof record.tag !== "string" ||
      typeof record.ciphertext !== "string" || typeof record.savedAt !== "string") {
    throw new Error("A valid encrypted cTrader token record is required.");
  }
  if (!Number.isSafeInteger(nowMs)) throw new Error("Invalid update time.");
  await db.prepare(
    "INSERT INTO ctrader_tokens (token_kind, encrypted_record, environment, account_id, updated_at) VALUES (?, ?, 'demo', ?, ?) ON CONFLICT(token_kind) DO UPDATE SET encrypted_record = excluded.encrypted_record, environment = 'demo', account_id = excluded.account_id, updated_at = excluded.updated_at",
  ).bind(tokenKind, JSON.stringify(record), accountId == null ? null : String(accountId), Math.floor(nowMs / 1000)).run();
}

export async function readEncryptedCTraderToken(db, tokenKind) {
  requireDatabase(db);
  requireAccessKind(tokenKind);
  const row = await db.prepare(
    "SELECT encrypted_record, environment, account_id, updated_at FROM ctrader_tokens WHERE token_kind = ? AND environment = 'demo'",
  ).bind(tokenKind).first();
  if (!row) return null;
  let record;
  try {
    record = JSON.parse(row.encrypted_record);
  } catch {
    throw new Error("Stored cTrader token record is invalid.");
  }
  return {
    record,
    environment: row.environment,
    accountId: row.account_id,
    updatedAt: row.updated_at,
  };
}
