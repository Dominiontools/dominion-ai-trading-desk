import { readEncryptedCTraderToken, saveEncryptedCTraderToken } from "./ctrader-d1-store.js";
import { decryptCTraderTokenRecord, encryptCTraderTokenRecord } from "./ctrader-token-crypto.js";
import { validateCTraderTokenResponse } from "./ctrader-oauth.js";

function validateStoredPayload(payload, tokenKind, accountId) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload) ||
      payload.environment !== "demo" || payload.access !== tokenKind ||
      String(payload.accountId ?? "") !== String(accountId ?? "") ||
      !payload.accountId || !Number.isSafeInteger(payload.issuedAt) || payload.issuedAt <= 0) {
    throw new Error("Stored cTrader demo authorization failed validation.");
  }
  const token = validateCTraderTokenResponse(payload);
  return { ...token, issuedAt: payload.issuedAt, environment: "demo", access: tokenKind, accountId: String(accountId) };
}

/**
 * Load a server-side demo token and refresh it before expiry.
 * Returned credentials are for internal broker calls only and must never be serialized to clients or logs.
 */
export async function loadUsableCTraderToken({
  db,
  tokenKind,
  encryptionKey,
  clientId,
  clientSecret,
  nowMs = Date.now(),
  fetchImpl = fetch,
  refreshSkewMs = 60_000
}) {
  if (tokenKind !== "view-only" && tokenKind !== "trading") throw new Error("Unsupported cTrader token kind.");
  if (typeof encryptionKey !== "string" || !encryptionKey ||
      typeof clientId !== "string" || !clientId ||
      typeof clientSecret !== "string" || !clientSecret ||
      !Number.isSafeInteger(nowMs) || nowMs <= 0 ||
      !Number.isSafeInteger(refreshSkewMs) || refreshSkewMs < 0 || refreshSkewMs > 300_000 ||
      typeof fetchImpl !== "function") {
    throw new Error("Invalid cTrader token service configuration.");
  }
  const stored = await readEncryptedCTraderToken(db, tokenKind);
  if (!stored) return null;
  if (stored.environment !== "demo" || !stored.accountId) {
    throw new Error("Stored cTrader token is not bound to a verified demo account.");
  }
  const payload = validateStoredPayload(
    await decryptCTraderTokenRecord(stored.record, encryptionKey),
    tokenKind,
    stored.accountId
  );
  const expiresAt = payload.issuedAt + payload.expiresIn * 1000;
  if (!Number.isSafeInteger(expiresAt)) throw new Error("Stored cTrader token expiry is invalid.");
  if (expiresAt > nowMs + refreshSkewMs) {
    return { ...payload, expiresAt };
  }

  const params = new URLSearchParams({
    grant_type: "refresh_token",
    refresh_token: payload.refreshToken,
    client_id: clientId,
    client_secret: clientSecret
  });
  const response = await fetchImpl(`https://openapi.ctrader.com/apps/token?${params.toString()}`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "content-type": "application/json"
    },
    signal: AbortSignal.timeout(20_000)
  });
  if (!response.ok) throw new Error("cTrader demo token refresh failed.");
  const refreshed = validateCTraderTokenResponse(await response.json());
  const nextPayload = {
    ...refreshed,
    issuedAt: nowMs,
    environment: "demo",
    access: tokenKind,
    accountId: String(stored.accountId)
  };
  const encrypted = await encryptCTraderTokenRecord(nextPayload, encryptionKey, new Date(nowMs));
  await saveEncryptedCTraderToken(db, tokenKind, encrypted, stored.accountId, nowMs);
  return { ...nextPayload, expiresAt: nowMs + refreshed.expiresIn * 1000 };
}
