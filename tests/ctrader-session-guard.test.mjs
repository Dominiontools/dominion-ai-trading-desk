import test from "node:test";
import assert from "node:assert/strict";
import {
  evaluateCTraderDemoSession,
  getCTraderReconnectDelayMs,
} from "../src/cloudflare/ctrader-session-guard.js";

const healthy = {
  connected: true,
  authenticated: true,
  environment: "demo",
  isLive: false,
  permissionScope: 1,
  lastHeartbeatAt: 100_000,
  automationEnabled: true,
  liveTradingEnabled: false,
};

test("demo session gate allows only a fresh, authenticated demo trading session", () => {
  assert.deepEqual(evaluateCTraderDemoSession(healthy, 105_000), {
    allowed: true,
    reason: "verified_demo_session",
  });
});

test("demo session gate is closed by default when automation is disabled", () => {
  assert.deepEqual(evaluateCTraderDemoSession({
    ...healthy,
    automationEnabled: false,
  }, 105_000), {
    allowed: false,
    reason: "demo_automation_not_enabled",
  });
});

test("demo session gate rejects live accounts and live-trading enablement", () => {
  assert.equal(evaluateCTraderDemoSession({ ...healthy, isLive: true }, 105_000).allowed, false);
  assert.equal(evaluateCTraderDemoSession({ ...healthy, liveTradingEnabled: true }, 105_000).allowed, false);
});

test("demo session gate rejects missing trading permission", () => {
  assert.deepEqual(evaluateCTraderDemoSession({
    ...healthy,
    permissionScope: 0,
  }, 105_000), {
    allowed: false,
    reason: "trading_scope_not_verified",
  });
});

test("demo session gate rejects stale, future, or missing heartbeats", () => {
  assert.equal(evaluateCTraderDemoSession(healthy, 116_000).reason, "broker_heartbeat_stale");
  assert.equal(evaluateCTraderDemoSession(healthy, 99_999).reason, "broker_heartbeat_stale");
  const { lastHeartbeatAt, ...missing } = healthy;
  assert.equal(evaluateCTraderDemoSession(missing, 105_000).reason, "heartbeat_timestamp_missing");
});

test("reconnect backoff grows exponentially and is capped", () => {
  const options = { baseMs: 1_000, maxMs: 8_000, jitterRatio: 0, random: () => 0.5 };
  assert.equal(getCTraderReconnectDelayMs(0, options), 1_000);
  assert.equal(getCTraderReconnectDelayMs(1, options), 2_000);
  assert.equal(getCTraderReconnectDelayMs(2, options), 4_000);
  assert.equal(getCTraderReconnectDelayMs(8, options), 8_000);
});

test("reconnect backoff applies bounded jitter and rejects invalid options", () => {
  assert.equal(getCTraderReconnectDelayMs(0, {
    baseMs: 1_000, maxMs: 2_000, jitterRatio: 0.2, random: () => 1,
  }), 1_200);
  assert.equal(getCTraderReconnectDelayMs(0, {
    baseMs: 1_000, maxMs: 2_000, jitterRatio: 0.2, random: () => 0,
  }), 800);
  assert.throws(() => getCTraderReconnectDelayMs(-1));
  assert.throws(() => getCTraderReconnectDelayMs(1, { jitterRatio: 2 }));
});
