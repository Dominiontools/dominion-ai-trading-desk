import test from "node:test";
import assert from "node:assert/strict";
import { reconcileCTraderDemoCycle } from "../src/cloudflare/ctrader-demo-cycle-preflight.js";

const config = {
  enabled: true, environment: "demo", profile: "intraday", scoreThreshold: 6,
  useSessionFilter: true, riskPerTradePct: 0.5, dailyLossLimitPct: 2,
  symbols: ["XAUUSD", "EURUSD", "GBPUSD"],
  maxRiskPerTradePct: 0.5, maxDailyLossPct: 2, maxOpenPositions: 1
};
const status = {
  connected: true, environment: "demo", isLive: false, access: "trading",
  permissionScope: 1, liveTradingEnabled: false
};
const token = {
  accessToken: "internal-test-token", accountId: "12345", access: "trading",
  environment: "demo", expiresAt: 1_900_000_000_000
};

function setup(overrides = {}) {
  const calls = [];
  const session = {
    lastMessageAt: 1_800_000_000_000,
    async connect() { calls.push("connect"); },
    async authorize(...args) { calls.push(["authorize", ...args.slice(1, 2)]); },
    async reconcile() { calls.push("reconcile"); return { positions: [], orders: [] }; },
    async close() { calls.push("close"); }
  };
  const services = {
    async readConfig() { return { config }; },
    async readStatus() { return status; },
    async loadToken() { return token; },
    async acquireLock(_db, lockName, lockId) {
      calls.push("lock");
      return { lockName, lockId };
    },
    async releaseLock() { calls.push("unlock"); },
    async readPosition() { return null; },
    async readIntents() { return []; },
    async appendEvent(_db, event) { calls.push(["event", event.eventType]); },
    reconcilePosition: ({ brokerPositions, storedPosition }) =>
      brokerPositions.length === 0 && storedPosition === null
        ? { safe: true, state: "FLAT", position: null }
        : { safe: false, reason: "BROKER_D1_POSITION_MISMATCH" },
    assertNoUnresolved: (intents) => ({ safe: intents.length === 0 }),
    evaluateSession: () => ({ allowed: true })
  };
  Object.assign(services, overrides.services ?? {});
  if (overrides.brokerState) session.reconcile = async () => overrides.brokerState;
  const db = { prepare() { throw new Error("Injected service should own D1 access."); } };
  const resultPromise = reconcileCTraderDemoCycle({
    db,
    env: {
      CTRADER_TOKEN_ENCRYPTION_KEY: "test-encryption-key",
      CTRADER_CLIENT_ID: "test-client-id",
      CTRADER_CLIENT_SECRET: "test-client-secret"
    },
    nowMs: 1_800_000_000_000,
    sessionFactory: () => session,
    services
  });
  return { resultPromise, calls };
}

test("demo cycle preflight locks, authenticates, reconciles flat state, and releases", async () => {
  const { resultPromise, calls } = setup();
  const result = await resultPromise;
  assert.equal(result.safe, true);
  assert.equal(result.state, "FLAT");
  assert.ok(calls.includes("connect"));
  assert.ok(calls.includes("reconcile"));
  assert.ok(calls.includes("close"));
  assert.ok(calls.includes("unlock"));
  assert.ok(calls.some((item) => Array.isArray(item) && item[1] === "CYCLE_PREFLIGHT_RECONCILED"));
});

test("disabled automation stops before acquiring a lock or connecting", async () => {
  const { resultPromise, calls } = setup({
    services: { async readConfig() { return { config: { ...config, enabled: false } }; } }
  });
  const result = await resultPromise;
  assert.equal(result.reason, "DEMO_AUTOMATION_NOT_ENABLED_OR_CONFIG_INVALID");
  assert.equal(calls.includes("lock"), false);
  assert.equal(calls.includes("connect"), false);
});

test("missing trading scope blocks before token use", async () => {
  const { resultPromise, calls } = setup({
    services: { async readStatus() { return { ...status, permissionScope: 0 }; } }
  });
  const result = await resultPromise;
  assert.equal(result.reason, "VERIFIED_DEMO_TRADING_AUTHORIZATION_REQUIRED");
  assert.equal(calls.includes("lock"), false);
});

test("execution lock contention prevents a broker connection", async () => {
  const { resultPromise, calls } = setup({
    services: { async acquireLock() { calls.push("lock"); return null; } }
  });
  const result = await resultPromise;
  assert.equal(result.reason, "EXECUTION_LOCKED");
  assert.equal(calls.includes("connect"), false);
});

test("broker and D1 position disagreement blocks the cycle", async () => {
  const { resultPromise, calls } = setup({
    brokerState: { positions: [{ positionId: "99" }], orders: [] },
    services: {
      async readPosition() { return null; },
      reconcilePosition: () => ({ safe: false, reason: "UNTRACKED_BROKER_POSITION" })
    }
  });
  const result = await resultPromise;
  assert.equal(result.safe, false);
  assert.equal(result.reason, "UNTRACKED_BROKER_POSITION");
  assert.ok(calls.some((item) => Array.isArray(item) && item[1] === "BROKER_D1_MISMATCH"));
  assert.ok(calls.includes("unlock"));
});

test("unresolved intents and pending broker orders both block entries", async () => {
  const unresolved = setup({
    services: {
      async readIntents() { return [{ clientOrderId: "dominion_order_123" }]; },
      assertNoUnresolved: () => ({ safe: false })
    }
  });
  assert.equal((await unresolved.resultPromise).reason, "UNRESOLVED_ORDER_INTENT");

  const pending = setup({ brokerState: { positions: [], orders: [{ orderId: "1" }] } });
  assert.equal((await pending.resultPromise).reason, "PENDING_BROKER_ORDER");
});

test("expired or wrong-environment token blocks without connecting", async () => {
  const { resultPromise, calls } = setup({
    services: { async loadToken() { return { ...token, expiresAt: 1 }; } }
  });
  const result = await resultPromise;
  assert.equal(result.reason, "DEMO_TRADING_TOKEN_UNAVAILABLE");
  assert.equal(calls.includes("connect"), false);
});
