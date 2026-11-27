import test from "node:test";
import assert from "node:assert/strict";
import { readCTraderEngineConfig, saveCTraderEngineConfig } from "../src/cloudflare/ctrader-engine-config-store.js";

const valid = {
  enabled: false,
  profile: "intraday",
  scoreThreshold: 6,
  useSessionFilter: true,
  riskPerTradePct: 0.5,
  dailyLossLimitPct: 2,
  symbols: ["XAUUSD", "EURUSD", "GBPUSD"],
  maxRiskPerTradePct: 0.5,
  maxDailyLossPct: 2,
  maxOpenPositions: 1,
  environment: "demo",
};

function mockD1({ row = null } = {}) {
  const calls = [];
  return {
    calls,
    prepare(sql) {
      const call = { sql, values: [] };
      calls.push(call);
      return {
        bind(...values) { call.values = values; return this; },
        async first() { return row; },
        async run() { return { success: true }; },
      };
    },
  };
}

test("reads missing engine config as null", async () => {
  assert.equal(await readCTraderEngineConfig(mockD1()), null);
});

test("reads and validates the stored demo configuration", async () => {
  const db = mockD1({ row: { config_json: JSON.stringify(valid), updated_at: 1_800_000_000 } });
  assert.deepEqual(await readCTraderEngineConfig(db), { config: valid, updatedAt: 1_800_000_000 });
  assert.match(db.calls[0].sql, /WHERE id = 1/);
});

test("rejects malformed, live, or over-limit stored configuration", async () => {
  const invalidConfigs = [
    { ...valid, environment: "live" },
    { ...valid, maxOpenPositions: 2 },
    { ...valid, riskPerTradePct: 0.51 },
    { ...valid, symbols: ["EURUSD", "EURUSD"] },
  ];
  for (const config of invalidConfigs) {
    await assert.rejects(readCTraderEngineConfig(mockD1({
      row: { config_json: JSON.stringify(config), updated_at: 1 },
    })));
  }
});

test("saves validated config through singleton upsert", async () => {
  const db = mockD1();
  const result = await saveCTraderEngineConfig(db, valid, 1_800_000_000_500);
  assert.deepEqual(result, { updatedAt: 1_800_000_000 });
  assert.match(db.calls[0].sql, /ON CONFLICT\(id\) DO UPDATE/);
  assert.equal(db.calls[0].values[0], JSON.stringify(valid));
});

test("refuses invalid config and invalid timestamps before writing", async () => {
  const db = mockD1();
  await assert.rejects(saveCTraderEngineConfig(db, { ...valid, enabled: true, environment: "live" }));
  await assert.rejects(saveCTraderEngineConfig(db, valid, NaN));
  assert.equal(db.calls.length, 0);
});
