import test from "node:test";
import assert from "node:assert/strict";
import { loadUsableCTraderToken } from "../src/cloudflare/ctrader-token-service.js";
import { encryptCTraderTokenRecord, decryptCTraderTokenRecord } from "../src/cloudflare/ctrader-token-crypto.js";

const key = Buffer.alloc(32, 9).toString("base64");
const accountId = "987654321";

function memoryDb(initialRecord) {
  let row = initialRecord ? {
    encrypted_record: JSON.stringify(initialRecord),
    environment: "demo",
    account_id: accountId,
    updated_at: 1
  } : null;
  const writes = [];
  return {
    writes,
    get row() { return row; },
    prepare(sql) {
      return {
        bind(...values) {
          return {
            async first() {
              if (sql.startsWith("SELECT encrypted_record")) return row;
              return null;
            },
            async run() {
              writes.push({ sql, values });
              if (sql.startsWith("INSERT INTO ctrader_tokens")) {
                row = {
                  encrypted_record: values[1],
                  environment: "demo",
                  account_id: values[2],
                  updated_at: values[3]
                };
              }
              return { success: true, meta: { changes: 1 } };
            }
          };
        }
      };
    }
  };
}

async function encryptedPayload(payload, nowMs) {
  return encryptCTraderTokenRecord(payload, key, new Date(nowMs));
}

test("returns a fresh encrypted demo token without contacting cTrader", async () => {
  const now = 1_800_000_000_000;
  const record = await encryptedPayload({
    accessToken: "fresh-access",
    refreshToken: "fresh-refresh",
    tokenType: "Bearer",
    expiresIn: 3600,
    issuedAt: now,
    environment: "demo",
    access: "trading",
    accountId
  }, now);
  const db = memoryDb(record);
  let requested = false;
  const token = await loadUsableCTraderToken({
    db, tokenKind: "trading", encryptionKey: key,
    clientId: "client", clientSecret: "secret", nowMs: now + 1000,
    fetchImpl: async () => { requested = true; throw new Error("unexpected refresh"); }
  });
  assert.equal(requested, false);
  assert.equal(token.accessToken, "fresh-access");
  assert.equal(token.accountId, accountId);
  assert.equal(token.environment, "demo");
  assert.equal(token.expiresAt, now + 3_600_000);
  assert.equal(db.writes.length, 0);
});

test("refreshes an expiring token and persists only the encrypted replacement", async () => {
  const now = 1_800_000_000_000;
  const record = await encryptedPayload({
    accessToken: "old-access",
    refreshToken: "old-refresh",
    tokenType: "Bearer",
    expiresIn: 30,
    issuedAt: now - 29_000,
    environment: "demo",
    access: "trading",
    accountId
  }, now);
  const db = memoryDb(record);
  let requestedUrl;
  const token = await loadUsableCTraderToken({
    db, tokenKind: "trading", encryptionKey: key,
    clientId: "client", clientSecret: "secret", nowMs: now,
    fetchImpl: async (url, options) => {
      requestedUrl = String(url);
      assert.equal(options.method, "POST");
      assert.match(options.headers["content-type"], /application\\/x-www-form-urlencoded/);
      assert.match(String(options.body), /grant_type=refresh_token/);
      assert.match(String(options.body), /refresh_token=old-refresh/);
      return new Response(JSON.stringify({
        accessToken: "new-access",
        refreshToken: "new-refresh",
        tokenType: "Bearer",
        expiresIn: 3600
      }), { status: 200, headers: { "content-type": "application/json" } });
    }
  });
  assert.equal(requestedUrl, "https://openapi.ctrader.com/apps/token");
  assert.equal(token.accessToken, "new-access");
  assert.equal(token.refreshToken, "new-refresh");
  assert.equal(token.expiresAt, now + 3_600_000);
  assert.equal(db.writes.length, 1);
  assert.equal(db.writes[0].values[0], "trading");
  assert.equal(db.row.encrypted_record.includes("new-access"), false);
  const stored = JSON.parse(db.row.encrypted_record);
  const decrypted = await decryptCTraderTokenRecord(stored, key);
  assert.equal(decrypted.accessToken, "new-access");
  assert.equal(decrypted.accountId, accountId);
  assert.equal(decrypted.environment, "demo");
});

test("rejects a stored token bound to a live or different account", async () => {
  const now = 1_800_000_000_000;
  const record = await encryptedPayload({
    accessToken: "access",
    refreshToken: "refresh",
    tokenType: "Bearer",
    expiresIn: 3600,
    issuedAt: now,
    environment: "live",
    access: "trading",
    accountId
  }, now);
  await assert.rejects(loadUsableCTraderToken({
    db: memoryDb(record), tokenKind: "trading", encryptionKey: key,
    clientId: "client", clientSecret: "secret", nowMs: now,
    fetchImpl: async () => { throw new Error("must not refresh invalid data"); }
  }), /failed validation/);
});

test("returns null when no encrypted token exists", async () => {
  const result = await loadUsableCTraderToken({
    db: memoryDb(null), tokenKind: "view-only", encryptionKey: key,
    clientId: "client", clientSecret: "secret", nowMs: 1_800_000_000_000
  });
  assert.equal(result, null);
});
