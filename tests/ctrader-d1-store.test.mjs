import test from "node:test";
import assert from "node:assert/strict";
import {
  createOAuthState,
  consumeOAuthState,
  saveEncryptedCTraderToken,
  readEncryptedCTraderToken,
} from "../src/cloudflare/ctrader-d1-store.js";

function mockD1({ firstResult = null } = {}) {
  const calls = [];
  return {
    calls,
    prepare(sql) {
      const call = { sql, values: [] };
      calls.push(call);
      return {
        bind(...values) {
          call.values = values;
          return this;
        },
        async run() {
          return { success: true };
        },
        async first() {
          return firstResult;
        },
      };
    },
  };
}

test("OAuth state is stored as a SHA-256 hash with a ten-minute maximum lifetime", async () => {
  const db = mockD1();
  const state = "s".repeat(48);
  const result = await createOAuthState(db, state, "trading", 1_800_000_000_000, 600_000);
  assert.equal(result.expiresAt, 1_800_000_600);
  assert.match(db.calls[0].sql, /INSERT INTO oauth_states/);
  assert.notEqual(db.calls[0].values[0], state);
  assert.match(db.calls[0].values[0], /^[a-f0-9]{64}$/);
  assert.equal(db.calls[0].values[3], "trading");
});

test("OAuth state rejects invalid access modes and excessive lifetimes", async () => {
  const db = mockD1();
  await assert.rejects(createOAuthState(db, "s".repeat(48), "live"));
  await assert.rejects(createOAuthState(db, "s".repeat(48), "trading", Date.now(), 600_001));
});

test("OAuth state consumption uses one atomic, unexpired, one-time update", async () => {
  const db = mockD1({ firstResult: { access_kind: "view-only", expires_at: 1_900_000_000 } });
  const result = await consumeOAuthState(db, "x".repeat(48), 1_800_000_000_000);
  assert.deepEqual(result, { accessKind: "view-only", expiresAt: 1_900_000_000 });
  assert.match(db.calls[0].sql, /consumed_at IS NULL AND expires_at > \? RETURNING/);
  assert.equal(db.calls[0].values.length, 3);
});

test("OAuth state returns null when it is missing, consumed, or expired", async () => {
  const db = mockD1();
  assert.equal(await consumeOAuthState(db, "x".repeat(48), 1_800_000_000_000), null);
  assert.equal(await consumeOAuthState(db, "short"), null);
});

test("token persistence accepts only encrypted demo token records", async () => {
  const db = mockD1();
  const record = {
    version: 1,
    algorithm: "aes-256-gcm",
    iv: "a".repeat(16),
    tag: "b".repeat(24),
    ciphertext: "c".repeat(32),
    savedAt: "2026-11-27T12:00:00.000Z",
  };
  await saveEncryptedCTraderToken(db, "trading", record, "demo-account-1", 1_800_000_000_000);
  assert.match(db.calls[0].sql, /'demo'/);
  assert.equal(db.calls[0].values[0], "trading");
  assert.equal(JSON.parse(db.calls[0].values[1]).algorithm, "aes-256-gcm");
  await assert.rejects(saveEncryptedCTraderToken(db, "trading", { accessToken: "plain" }, null));
});

test("token reads are restricted to demo records and return parsed ciphertext only", async () => {
  const record = { version: 1, algorithm: "aes-256-gcm", iv: "iv", tag: "tag", ciphertext: "cipher", savedAt: "now" };
  const db = mockD1({ firstResult: {
    encrypted_record: JSON.stringify(record),
    environment: "demo",
    account_id: "demo-1",
    updated_at: 1_800_000_000,
  } });
  const result = await readEncryptedCTraderToken(db, "trading");
  assert.deepEqual(result, {
    record,
    environment: "demo",
    accountId: "demo-1",
    updatedAt: 1_800_000_000,
  });
  assert.match(db.calls[0].sql, /environment = 'demo'/);
});
