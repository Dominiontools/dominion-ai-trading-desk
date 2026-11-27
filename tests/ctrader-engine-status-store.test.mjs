import test from "node:test";
import assert from "node:assert/strict";
import { readCTraderEngineStatus, saveCTraderEngineStatus } from "../src/cloudflare/ctrader-engine-status-store.js";

function mockD1({ row = null } = {}) {
  const calls = [];
  return {
    calls,
    prepare(sql) {
      const call = { sql, values: [] };
      calls.push(call);
      return {
        bind(...values) { call.values = values; return this; },
        async run() { return { success: true }; },
        async first() { return row; }
      };
    }
  };
}

const connectedDemo = {
  status: "CONNECTED",
  reason: "ENGINE_DISABLED",
  connected: true,
  isLive: false,
  environment: "demo",
  access: "trading",
  permissionScope: 1,
  demoAccountCount: 1,
  liveTradingEnabled: false
};

test("missing status returns a safe disconnected demo default", async () => {
  const result = await readCTraderEngineStatus(mockD1());
  assert.deepEqual(result, {
    status: "NOT_CONFIGURED", reason: "ENGINE_HAS_NOT_RUN", connected: false,
    environment: "demo", access: "none", permissionScope: 0,
    demoAccountCount: 0, liveTradingEnabled: false, updatedAt: null
  });
});

test("status save persists only an allowlisted demo snapshot", async () => {
  const db = mockD1();
  const result = await saveCTraderEngineStatus(db, connectedDemo, 1_800_000_000_000);
  assert.equal(result.connected, true);
  assert.equal(result.updatedAt, 1_800_000_000);
  assert.match(db.calls[0].sql, /ON CONFLICT\(id\) DO UPDATE/);
  const stored = JSON.parse(db.calls[0].values[0]);
  assert.equal(stored.environment, "demo");
  assert.equal(stored.isLive, false);
  assert.equal(stored.liveTradingEnabled, false);
  assert.equal(stored.permissionScope, 1);
});

test("status save rejects live, unknown, and inconsistent connected states", async () => {
  const db = mockD1();
  await assert.rejects(saveCTraderEngineStatus(db, { ...connectedDemo, environment: "live" }));
  await assert.rejects(saveCTraderEngineStatus(db, { ...connectedDemo, liveTradingEnabled: true }));
  await assert.rejects(saveCTraderEngineStatus(db, { ...connectedDemo, isLive: true }));
  await assert.rejects(saveCTraderEngineStatus(db, { ...connectedDemo, access: "view-only", permissionScope: 1 }));
  await assert.rejects(saveCTraderEngineStatus(db, { ...connectedDemo, status: "UNKNOWN" }));
});

test("read status fails closed for corrupted or live-looking stored rows", async () => {
  const badRows = [
    { status_json: "{bad", updated_at: 1 },
    { status_json: JSON.stringify({ ...connectedDemo, environment: "live" }), updated_at: 1 },
    { status_json: JSON.stringify({ ...connectedDemo, liveTradingEnabled: true }), updated_at: 1 },
    { status_json: JSON.stringify({ ...connectedDemo, status: "UNRECOGNIZED" }), updated_at: 1 }
  ];
  for (const row of badRows) await assert.rejects(readCTraderEngineStatus(mockD1({ row })));
});

test("read status exposes only sanitized fields and requires verified demo marker", async () => {
  const row = { status_json: JSON.stringify({ ...connectedDemo, isLive: false, accountId: "private", token: "secret" }), updated_at: 1_800_000_000 };
  const result = await readCTraderEngineStatus(mockD1({ row }));
  assert.deepEqual(result, {
    status: "CONNECTED", reason: "ENGINE_DISABLED", connected: true,
    environment: "demo", access: "trading", permissionScope: 1,
    demoAccountCount: 1, liveTradingEnabled: false, updatedAt: 1_800_000_000
  });
  assert.equal("token" in result, false);
  assert.equal("accountId" in result, false);
});

test("unverified connection is downgraded to disconnected", async () => {
  const row = { status_json: JSON.stringify({ ...connectedDemo, isLive: true }), updated_at: 12 };
  const result = await readCTraderEngineStatus(mockD1({ row }));
  assert.equal(result.connected, false);
  assert.equal(result.access, "none");
  assert.equal(result.permissionScope, 0);
});
