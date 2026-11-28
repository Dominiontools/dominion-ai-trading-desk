import test from "node:test";
import assert from "node:assert/strict";
import { verifyCloudflareAccessRequest } from "../src/cloudflare/cloudflare-access-auth.js";

const encoder = new TextEncoder();
const issuer = "https://dominion.cloudflareaccess.com";
const audience = "dominion-dashboard-audience";
const email = "operator@example.com";

function base64url(bytes) {
  return Buffer.from(bytes).toString("base64url");
}

async function signedToken({ claims = {}, tamper = false } = {}) {
  const pair = await crypto.subtle.generateKey(
    { name: "RSASSA-PKCS1-v1_5", modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256" },
    true,
    ["sign", "verify"]
  );
  const jwk = await crypto.subtle.exportKey("jwk", pair.publicKey);
  jwk.kid = "test-key";
  jwk.use = "sig";
  const header = base64url(encoder.encode(JSON.stringify({ alg: "RS256", typ: "JWT", kid: "test-key" })));
  const payload = base64url(encoder.encode(JSON.stringify({
    iss: issuer,
    aud: [audience],
    email,
    iat: 1_800_000_000,
    exp: 1_800_000_300,
    ...claims
  })));
  const input = `${header}.${payload}`;
  const signature = new Uint8Array(await crypto.subtle.sign(
    { name: "RSASSA-PKCS1-v1_5" }, pair.privateKey, encoder.encode(input)
  ));
  if (tamper) signature[0] ^= 1;
  return {
    token: `${input}.${base64url(signature)}`,
    jwks: { keys: [jwk] }
  };
}

function requestWithToken(token) {
  return new Request("https://desk.example.com/api/ctrader/engine/control", {
    method: "POST",
    headers: { "cf-access-jwt-assertion": token, origin: "https://desk.example.com" }
  });
}

test("accepts a correctly signed Cloudflare Access token for the configured operator", async () => {
  const signed = await signedToken();
  const result = await verifyCloudflareAccessRequest({
    request: requestWithToken(signed.token),
    issuer,
    audience,
    allowedEmail: email,
    nowMs: 1_800_000_100_000,
    fetchImpl: async () => ({ ok: true, json: async () => signed.jwks })
  });
  assert.deepEqual(result, { ok: true, email });
});

test("rejects an untrusted signature", async () => {
  const signed = await signedToken({ tamper: true });
  const result = await verifyCloudflareAccessRequest({
    request: requestWithToken(signed.token),
    issuer,
    audience,
    allowedEmail: email,
    nowMs: 1_800_000_100_000,
    fetchImpl: async () => ({ ok: true, json: async () => signed.jwks })
  });
  assert.equal(result.ok, false);
  assert.equal(result.error, "ACCESS_SIGNATURE_INVALID");
});

test("rejects an unexpected audience and an expired token", async () => {
  const wrongAudience = await signedToken({ claims: { aud: ["other-audience"] } });
  const expired = await signedToken({ claims: { exp: 1_800_000_099 } });
  const verify = (token, jwks) => verifyCloudflareAccessRequest({
    request: requestWithToken(token), issuer, audience, allowedEmail: email,
    nowMs: 1_800_000_100_000, fetchImpl: async () => ({ ok: true, json: async () => jwks })
  });
  assert.equal((await verify(wrongAudience.token, wrongAudience.jwks)).error, "ACCESS_TOKEN_CLAIMS_REJECTED");
  assert.equal((await verify(expired.token, expired.jwks)).error, "ACCESS_TOKEN_CLAIMS_REJECTED");
});

test("fails closed when Access configuration or identity is missing", async () => {
  const result = await verifyCloudflareAccessRequest({
    request: new Request("https://desk.example.com"),
    issuer: "",
    audience,
    allowedEmail: email
  });
  assert.deepEqual(result, { ok: false, error: "ACCESS_AUTH_NOT_CONFIGURED" });
});
