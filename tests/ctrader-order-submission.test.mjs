import test from "node:test";
import assert from "node:assert/strict";
import { submitCTraderDemoOrderOnce } from "../src/cloudflare/ctrader-order-submission.js";

const accountId = "123456789";
const clientOrderId = "order_1234567890";

function mockD1({ duplicate = false } = {}) {
  const calls = [];
  return {
    calls,
    prepare(sql) {
      const call = { sql, values: [] };
      calls.push(call);
      return {
        bind(...values) { call.values = values; return this; },
        async first() {
          if (sql.startsWith("INSERT")) return duplicate ? null : {
            client_order_id: clientOrderId, account_id: accountId, state: "PREPARED", created_at: 10
          };
          if (sql.startsWith("UPDATE")) return {
            client_order_id: clientOrderId, state: "SUBMITTED", broker_position_id: null
          };
          return null;
        }
      };
    }
  };
}

const args = {
  accountId,
  clientOrderId,
  intent: { symbol: "EURUSD", side: "BUY", volume: 1000 },
  order: { symbolId: 1, side: "BUY", volume: 1000, entryPrice: 1.1, stopLoss: 1.09, takeProfit: 1.13 },
  nowMs: 1_800_000_000_000
};

test("demo order reserves and marks intent before one broker submission", async () => {
  const db = mockD1();
  let submits = 0;
  const result = await submitCTraderDemoOrderOnce({
    ...args, db, session: { async newMarketRangeOrder(order) {
      submits++;
      assert.equal(order.clientOrderId, clientOrderId);
      return { executionType: 3 };
    } }
  });
  assert.equal(submits, 1);
  assert.equal(result.status, "SUBMITTED_AWAITING_BROKER_RECONCILIATION");
  assert.equal(db.calls.length, 2);
  assert.match(db.calls[0].sql, /^INSERT INTO ctrader_order_intents/);
  assert.match(db.calls[1].sql, /^UPDATE ctrader_order_intents/);
  assert.equal(result.brokerResponse.executionType, 3);
});

test("duplicate intent never reaches broker", async () => {
  const db = mockD1({ duplicate: true });
  let submits = 0;
  const result = await submitCTraderDemoOrderOnce({
    ...args, db, session: { async newMarketRangeOrder() { submits++; } }
  });
  assert.equal(result.status, "DUPLICATE_ORDER_INTENT");
  assert.equal(submits, 0);
  assert.equal(db.calls.length, 1);
});

test("uncertain broker result is marked UNKNOWN and never auto-retried", async () => {
  const db = mockD1();
  let submits = 0;
  const result = await submitCTraderDemoOrderOnce({
    ...args, db, session: { async newMarketRangeOrder() { submits++; throw new Error("socket closed"); } }
  });
  assert.equal(result.status, "ORDER_RESULT_UNKNOWN_RECONCILIATION_REQUIRED");
  assert.equal(submits, 1);
  assert.equal(db.calls.length, 3);
  assert.match(db.calls[2].sql, /state = \?/);
  assert.equal(db.calls[2].values[0], "UNKNOWN");
});
