import test from "node:test";
import assert from "node:assert/strict";
import { confirmCTraderDemoOrderFromBroker } from "../src/cloudflare/ctrader-order-reconciliation.js";

function mockD1({ existing = null, transition = true } = {}) {
  const calls = [];
  return {
    calls,
    prepare(sql) {
      const call = { sql, values: [] };
      calls.push(call);
      return {
        bind(...values) { call.values = values; return this; },
        async first() {
          if (sql.startsWith("SELECT position_id")) return existing;
          if (sql.startsWith("UPDATE ctrader_order_intents")) {
            return transition ? { client_order_id: "order_1234567890", state: "FILLED", broker_position_id: "88" } : null;
          }
          return null;
        },
        async run() { return { meta: { changes: 1 } }; }
      };
    }
  };
}

const base = {
  accountId: "123456789",
  clientOrderId: "order_1234567890",
  fromState: "SUBMITTED",
  brokerOrder: { clientOrderId: "order_1234567890", orderId: 77 },
  brokerPosition: {
    positionId: 88,
    price: 1.1,
    stopLoss: 1.09,
    takeProfit: 1.13,
    tradeData: { symbolId: 10, tradeSide: 1, volume: 1000 }
  },
  management: { target2R: 1.12, initialRiskDistance: 0.01, partialTaken: false },
  nowMs: 1_800_000_000_000
};

test("exact broker client order ID and protected position are saved before intent is marked filled", async () => {
  const db = mockD1();
  const result = await confirmCTraderDemoOrderFromBroker({ ...base, db });
  assert.equal(result.confirmed, true);
  assert.equal(result.positionId, "88");
  assert.equal(result.position.stopLoss, 1.09);
  assert.equal(db.calls.length, 3);
  assert.match(db.calls[0].sql, /^SELECT position_id/);
  assert.match(db.calls[1].sql, /^INSERT INTO ctrader_active_positions/);
  assert.match(db.calls[2].sql, /^UPDATE ctrader_order_intents/);
  assert.equal(db.calls[2].values[0], "FILLED");
});

test("a different broker client order ID cannot resolve the intent", async () => {
  const db = mockD1();
  const result = await confirmCTraderDemoOrderFromBroker({
    ...base, db, brokerOrder: { clientOrderId: "some_other_order" }
  });
  assert.equal(result.status, "BROKER_ORDER_IDENTITY_NOT_CONFIRMED");
  assert.equal(db.calls.length, 0);
});

test("an unprotected broker position is rejected before durable save", async () => {
  const db = mockD1();
  const result = await confirmCTraderDemoOrderFromBroker({
    ...base, db, brokerPosition: { ...base.brokerPosition, stopLoss: 0 }
  }).catch((error) => error);
  assert.match(result.message, /stop-loss/);
  assert.equal(db.calls.length, 0);
});

test("a different already-stored position prevents overwrite", async () => {
  const db = mockD1({ existing: { position_id: "99", position_json: "{}", updated_at: 10 } });
  const result = await confirmCTraderDemoOrderFromBroker({ ...base, db });
  assert.equal(result.status, "DIFFERENT_ACTIVE_POSITION_ALREADY_STORED");
  assert.equal(db.calls.length, 1);
});

test("intent transition conflict leaves broker position durable and blocks retry", async () => {
  const db = mockD1({ transition: false });
  const result = await confirmCTraderDemoOrderFromBroker({ ...base, db });
  assert.equal(result.status, "BROKER_POSITION_SAVED_ORDER_INTENT_TRANSITION_CONFLICT");
  assert.equal(result.safe, false);
  assert.match(db.calls[1].sql, /^INSERT INTO ctrader_active_positions/);
});
