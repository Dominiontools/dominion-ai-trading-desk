import test from "node:test";
import assert from "node:assert/strict";
import {
  buildCTraderAuthorizationUrl,
  validateCTraderTokenResponse,
} from "../src/cloudflare/ctrader-oauth.js";

const state = "s".repeat(48);
const origin = "https://desk.example";

test("cTrader authorization URL uses the same-origin HTTPS callback and requested scope", () => {
  const url = new URL(buildCTraderAuthorizationUrl({
    clientId: "client-123",
    redirectUri: origin + "/api/ctrader/oauth/callback",
    requestOrigin: origin,
    accessKind: "trading",
    state,
  }));
  assert.equal(url.origin, "https://id.ctrader.com");
  assert.equal(url.searchParams.get("client_id"), "client-123");
  assert.equal(url.searchParams.get("redirect_uri"), origin + "/api/ctrader/oauth/callback");
  assert.equal(url.searchParams.get("scope"), "trading");
  assert.equal(url.searchParams.get("product"), "web");
  assert.equal(url.searchParams.get("state"), state);
});

test("cTrader authorization URL defaults are explicit and view-only scope is accounts", () => {
  const url = new URL(buildCTraderAuthorizationUrl({
    clientId: "client-123",
    redirectUri: origin + "/api/ctrader/oauth/callback",
    requestOrigin: origin,
    accessKind: "view-only",
    state,
  }));
  assert.equal(url.searchParams.get("scope"), "accounts");
});

test("cTrader authorization URL rejects off-origin, insecure, and incorrect callback URLs", () => {
  const base = {
    clientId: "client-123",
    requestOrigin: origin,
    accessKind: "view-only",
    state,
  };
  for (const redirectUri of [
    "http://desk.example/api/ctrader/oauth/callback",
    "https://attacker.example/api/ctrader/oauth/callback",
    origin + "/wrong-callback",
    origin + "/api/ctrader/oauth/callback?next=https://attacker.example",
  ]) {
    assert.throws(() => buildCTraderAuthorizationUrl({ ...base, redirectUri }));
  }
});

test("cTrader authorization URL rejects malformed client IDs, access modes, and state", () => {
  const base = {
    clientId: "client-123",
    redirectUri: origin + "/api/ctrader/oauth/callback",
    requestOrigin: origin,
    accessKind: "view-only",
    state,
  };
  assert.throws(() => buildCTraderAuthorizationUrl({ ...base, clientId: "" }));
  assert.throws(() => buildCTraderAuthorizationUrl({ ...base, accessKind: "live" }));
  assert.throws(() => buildCTraderAuthorizationUrl({ ...base, state: "short" }));
});

test("cTrader token response validator accepts complete token data and normalizes expiry", () => {
  const result = validateCTraderTokenResponse({
    accessToken: "access",
    refreshToken: "refresh",
    tokenType: "Bearer",
    expiresIn: "3600",
  });
  assert.equal(result.expiresIn, 3600);
  assert.equal(result.accessToken, "access");
});

test("cTrader token response validator rejects errors and incomplete or invalid tokens", () => {
  assert.throws(() => validateCTraderTokenResponse({ errorCode: "invalid_grant" }));
  assert.throws(() => validateCTraderTokenResponse({
    accessToken: "access", refreshToken: "", tokenType: "Bearer", expiresIn: 3600,
  }));
  assert.throws(() => validateCTraderTokenResponse({
    accessToken: "access", refreshToken: "refresh", tokenType: "Bearer", expiresIn: 0,
  }));
});
