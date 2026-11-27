import test from "node:test";
import assert from "node:assert/strict";
import { verifyCTraderControlSignature } from "../src/cloudflare/ctrader-control-auth.js";

const secret = "dominion-control-test-secret-which-is-long-enough";
const timestampText = "1800000000000";
const nonce = "12345678-1234-4234-8234-123456789abc";
const rawBody = JSON.stringify({ enabled: false });

async function sign(secretValue, timestamp, nonceValue, body) {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secretValue),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const signature = new Uint8Array(await crypto.subtle.sign(
    "HMAC",
    key,
    new TextEncoder().encode(`${timestamp}.${nonceValue}.${body}`),
  ));
  return [...signature].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

test("control HMAC accepts the legacy timestamp.nonce.raw-body signature", async () => {
  const signature = await sign(secret, timestampText, nonce, rawBody);
  assert.equal(await verifyCTraderControlSignature({
    secret, timestampText, nonce, signature, rawBody, nowMs: 1_800_000_000_000,
  }), true);
});

test("control HMAC rejects a modified body or incorrect secret", async () => {
  const signature = await sign(secret, timestampText, nonce, rawBody);
  assert.equal(await verifyCTraderControlSignature({
    secret, timestampText, nonce, signature, rawBody: rawBody + " ", nowMs: 1_800_000_000_000,
  }), false);
  assert.equal(await verifyCTraderControlSignature({
    secret: secret + "wrong", timestampText, nonce, signature, rawBody, nowMs: 1_800_000_000_000,
  }), false);
});

test("control HMAC rejects stale timestamps and malformed headers", async () => {
  const signature = await sign(secret, timestampText, nonce, rawBody);
  assert.equal(await verifyCTraderControlSignature({
    secret, timestampText, nonce, signature, rawBody, nowMs: 1_800_000_060_001,
  }), false);
  assert.equal(await verifyCTraderControlSignature({
    secret, timestampText: "not-a-time", nonce, signature, rawBody, nowMs: 1_800_000_000_000,
  }), false);
  assert.equal(await verifyCTraderControlSignature({
    secret, timestampText, nonce: "bad", signature, rawBody, nowMs: 1_800_000_000_000,
  }), false);
  assert.equal(await verifyCTraderControlSignature({
    secret, timestampText, nonce, signature: "0".repeat(62), rawBody, nowMs: 1_800_000_000_000,
  }), false);
});

test("control HMAC rejects missing or weak secrets and oversized bodies", async () => {
  const signature = await sign(secret, timestampText, nonce, rawBody);
  assert.equal(await verifyCTraderControlSignature({
    secret: "short", timestampText, nonce, signature, rawBody, nowMs: 1_800_000_000_000,
  }), false);
  assert.equal(await verifyCTraderControlSignature({
    secret, timestampText, nonce, signature, rawBody: "x".repeat(16_385), nowMs: 1_800_000_000_000,
  }), false);
});
