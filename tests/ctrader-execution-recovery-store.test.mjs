import test from "node:test";
import assert from "node:assert/strict";
import {
  reserveCTraderOrderIntent,
  transitionCTraderOrderIntent,
  saveCTraderActivePosition,
  readCTraderActivePosition,
  clearCTraderActivePosition,
  appendCTraderEngineEvent,
  readUnresolvedCTraderOrderIntents
} from "../src/cloudflare/ctrader-execution-recovery-store.js";

function mockD1({ first = null, changes = 1 } = {}) {
  const calls = [];
  return {
    calls,
    prepare(sql) {
      const call = { sql, values: [] };
      calls.push(call);
      return {
        bind(...values) { call.values = values; return this; },
        async first() { return first; },
        async run() { return { success: true, meta: { changes } }; }
      };
    }
  };
}

const accountId = "123456789";
const clientOrderId = "order_1234567890";

test("order intent reservation is atomic and idempotent", async () => {
  const db = mockD1({ first: {
    client_order_id: clientOrderId, account_id: accountId,
    state: "PREPARED", created_at: 1_800_000_000
  } });
  const result = await reserveCTraderOrderIntent(db, {
    accountId, clientOrderId, intent: { symbol: "EURUSD", side: "BUY", volume: 1000 },
    nowMs: 1_800_000_000_000
  });
  assert.deepEqual(result, {
    clientOrderId, accountId, state: "PREPARED", createdAt: 1_800_000_000
  });
  assert.match(db.calls[0].sql, /ON CONFLICT\(client_order_id\) DO NOTHING RETURNING/);
  assert.equal(db.calls[0].values[0], clientOrderId);
  assert.equal(db.calls[0].values[1], accountId);
  assert.equal(JSON.parse(db.calls[0].values[2]).symbol, "EURUSD");
});

test("duplicate order intent reservation returns null", async () => {
  const db = mockD1();
  assert.equal(await reserveCTraderOrderIntent(db, {
    accountId, clientOrderId, intent: { symbol: "EURUSD" }
  }), null);
});

test("order state transition requires the exact prior state and account", async () => {
  const db = mockD1({ first: {
    client_order_id: clientOrderId, state: "FILLED", broker_position_id: "88"
  } });
  const result = await transitionCTraderOrderIntent(db, {
    accountId, clientOrderId, fromState: "SUBMITTED", toState: "FILLED",
    brokerPositionId: "88", nowMs: 1_800_000_000_000
  });
  assert.deepEqual(result, { clientOrderId, state: "FILLED", brokerPositionId: "88" });
  assert.match(db.calls[0].sql, /WHERE client_order_id = \? AND account_id = \? AND state = \? RETURNING/);
  assert.deepEqual(db.calls[0].values.slice(3, 6), [clientOrderId, accountId, "SUBMITTED"]);
});

test("order state machine rejects regressions and invalid broker IDs", async () => {
  const db = mockD1();
  await assert.rejects(transitionCTraderOrderIntent(db, {
    accountId, clientOrderId, fromState: "FILLED", toState: "SUBMITTED"
  }), /Invalid cTrader order intent transition/);
  await assert.rejects(transitionCTraderOrderIntent(db, {
    accountId, clientOrderId, fromState: "SUBMITTED", toState: "FILLED",
    brokerPositionId: "live-id"
  }), /Invalid broker position ID/);
});

test("active position snapshots can be saved, read, and cleared by exact ID", async () => {
  const position = { side: "BUY", symbol: "EURUSD", symbolId: 10, volume: 1000, stopLoss: 1.08, takeProfit: 1.14, target2R: 1.12 };
  const saveDb = mockD1();
  const saved = await saveCTraderActivePosition(saveDb, {
    accountId, positionId: "88", position, nowMs: 1_800_000_000_000
  });
  assert.equal(saved.positionId, "88");
  assert.match(saveDb.calls[0].sql, /ON CONFLICT\(account_id\) DO UPDATE/);
  assert.equal(JSON.parse(saveDb.calls[0].values[2]).side, "BUY");

  const readDb = mockD1({ first: {
    position_id: "88", position_json: JSON.stringify(position), updated_at: 1_800_000_000
  } });
  const restored = await readCTraderActivePosition(readDb, accountId);
  assert.deepEqual(restored.position, position);
  assert.equal(restored.positionId, "88");

  const clearDb = mockD1({ changes: 1 });
  assert.equal(await clearCTraderActivePosition(clearDb, accountId, "88"), true);
  assert.match(clearDb.calls[0].sql, /WHERE account_id = \? AND position_id = \?/);
  assert.deepEqual(clearDb.calls[0].values, [accountId, "88"]);
});

test("active position reads fail closed on corrupt JSON", async () => {
  const db = mockD1({ first: { position_id: "88", position_json: "{", updated_at: 1 } });
  await assert.rejects(readCTraderActivePosition(db, accountId), /snapshot is corrupt/);
});

test("recovery events are bounded and stored with account scope", async () => {
  const db = mockD1();
  const result = await appendCTraderEngineEvent(db, {
    accountId, eventType: "POSITION_RECONCILED",
    event: { positionId: "88", brokerConfirmed: true },
    nowMs: 1_800_000_000_000
  });
  assert.equal(result.eventType, "POSITION_RECONCILED");
  assert.match(db.calls[0].sql, /INSERT INTO ctrader_engine_events/);
  assert.deepEqual(db.calls[0].values.slice(0, 3), [
    accountId, "POSITION_RECONCILED", JSON.stringify({ positionId: "88", brokerConfirmed: true })
  ]);
});

test("recovery store rejects invalid account IDs and oversized snapshots", async () => {
  const db = mockD1();
  await assert.rejects(readCTraderActivePosition(db, "live"));
  await assert.rejects(saveCTraderActivePosition(db, {
    accountId, positionId: "88", position: { data: "x".repeat(20_000) }
  }), /size limit/);
});


test("unresolved order intents are read by account and decoded safely", async () => {
  const db = {
    calls: [],
    prepare(sql) {
      const call = { sql, values: [] }; this.calls.push(call);
      return { bind(...values) { call.values = values; return this; },
        async all() { return { results: [{
          client_order_id: clientOrderId, intent_json: JSON.stringify({ symbol: "EURUSD" }),
          state: "UNKNOWN", broker_position_id: null, created_at: 10, updated_at: 11
        }] }; } };
    }
  };
  const rows = await readUnresolvedCTraderOrderIntents(db, accountId);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].state, "UNKNOWN");
  assert.deepEqual(rows[0].intent, { symbol: "EURUSD" });
  assert.match(db.calls[0].sql, /state IN \('PREPARED', 'SUBMITTED', 'UNKNOWN'\)/);
  assert.deepEqual(db.calls[0].values, [accountId]);
});

test("active position persistence rejects snapshots without durable broker protection", async () => {
  const db = mockD1();
  await assert.rejects(saveCTraderActivePosition(db, {
    accountId, positionId: "88",
    position: { symbolId: 10, side: "BUY", volume: 1000, stopLoss: 1.08 },
  }), /durable volume and SL\/TP protection/);
  assert.equal(db.calls.length, 0);
});
