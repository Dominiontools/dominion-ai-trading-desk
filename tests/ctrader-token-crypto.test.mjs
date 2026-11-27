import test from "node:test";
import assert from "node:assert/strict";
import {
  encryptCTraderTokenRecord,
  decryptCTraderTokenRecord,
} from "../src/cloudflare/ctrader-token-crypto.js";

const key = Buffer.alloc(32, 7).toString("base64");

test("cTrader token record round-trips with the legacy AES-256-GCM shape", async () => {
  const payload = {
    accessToken: "test-access-token",
    refreshToken: "test-refresh-token",
    expiresAt: 1_900_000_000,
  };
  const savedAt = new Date("2026-11-27T12:00:00.000Z");
  const record = await encryptCTraderTokenRecord(payload, key, savedAt);

  assert.equal(record.version, 1);
  assert.equal(record.algorithm, "aes-256-gcm");
  assert.equal(record.savedAt, savedAt.toISOString());
  assert.deepEqual(await decryptCTraderTokenRecord(record, key), payload);
});

test("cTrader token record encryption uses a fresh IV", async () => {
  const first = await encryptCTraderTokenRecord({ token: "same" }, key);
  const second = await encryptCTraderTokenRecord({ token: "same" }, key);
  assert.notEqual(first.iv, second.iv);
});

test("cTrader token record rejects an invalid key length", async () => {
  await assert.rejects(
    encryptCTraderTokenRecord({ token: "test" }, Buffer.alloc(16, 1).toString("base64")),
    /32-byte key/,
  );
});

test("cTrader token record rejects tampering or the wrong key", async () => {
  const record = await encryptCTraderTokenRecord({ token: "secret" }, key);
  const altered = { ...record, ciphertext: Buffer.from("tampered").toString("base64") };
  await assert.rejects(decryptCTraderTokenRecord(altered, key));
  await assert.rejects(
    decryptCTraderTokenRecord(record, Buffer.alloc(32, 8).toString("base64")),
  );
});

test("cTrader token record rejects unknown record formats", async () => {
  await assert.rejects(
    decryptCTraderTokenRecord({ version: 2, algorithm: "unknown" }, key),
    /unsupported format/,
  );
});


test("cTrader token encryption rejects non-object payloads", async () => {
  await assert.rejects(encryptCTraderTokenRecord(null, key), /JSON object/);
  await assert.rejects(encryptCTraderTokenRecord("token", key), /JSON object/);
});

test("cTrader token decryption rejects malformed base64 and invalid component lengths", async () => {
  const record = await encryptCTraderTokenRecord({ token: "secret" }, key);
  await assert.rejects(
    decryptCTraderTokenRecord({ ...record, iv: "not base64!" }, key),
    /Invalid base64/,
  );
  await assert.rejects(
    decryptCTraderTokenRecord({ ...record, iv: Buffer.alloc(8, 1).toString("base64") }, key),
    /component lengths/,
  );
  await assert.rejects(
    decryptCTraderTokenRecord({ ...record, tag: Buffer.alloc(8, 1).toString("base64") }, key),
    /component lengths/,
  );
});
