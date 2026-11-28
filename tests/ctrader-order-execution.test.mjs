import test from "node:test";
import assert from "node:assert/strict";
import { submitAndConfirmCTraderDemoOrder } from "../src/cloudflare/ctrader-order-execution.js";

const base = {
  db: {},
  session: { reconcile: async () => ({ positions: [] }) },
  accountId: "123456",
  clientOrderId: "dominion-123456789abc",
  intent: { symbol: "EURUSD", side: "BUY", volume: 1000 },
  order: { symbolId: 1, side: "BUY", volume: 1000, stopLoss: 1.08, takeProfit: 1.12 },
  management: { initialRiskDistance: 0.01, target3R: 1.12 },
  nowMs: 1_800_000_000_000
};

function execution(positionId = "777") {
  return {
    order: { clientOrderId: base.clientOrderId, positionId },
    position: {
      positionId,
      price: 1.1,
      stopLoss: 1.08,
      takeProfit: 1.12,
      tradeData: { symbolId: 1, volume: 1000, tradeSide: 1 }
    }
  };
}

const submitted = async () => ({
  submitted: true,
  status: "SUBMITTED_AWAITING_BROKER_RECONCILIATION",
  brokerResponse: execution()
});

test("confirms only the exact broker clientOrderId and linked protected position", async () => {
  let confirmation;
  const result = await submitAndConfirmCTraderDemoOrder({
    ...base,
    submitOnce: submitted,
    confirmFromBroker: async (input) => {
      confirmation = input;
      return { confirmed: true, safe: true, status: "BROKER_FILLED_PROTECTED_POSITION_DURABLY_RECORDED", positionId: "777" };
    }
  });
  assert.equal(result.safe, true);
  assert.equal(confirmation.brokerOrder.clientOrderId, base.clientOrderId);
  assert.equal(confirmation.brokerPosition.positionId, "777");
  assert.equal(confirmation.fromState, "SUBMITTED");
});

test("reconciles by the exact broker-linked position ID when execution position is omitted", async () => {
  let reconciled = false;
  let confirmed = false;
  const result = await submitAndConfirmCTraderDemoOrder({
    ...base,
    session: {
      reconcile: async () => {
        reconciled = true;
        return { positions: [execution().position] };
      }
    },
    submitOnce: async () => ({
      submitted: true,
      status: "SUBMITTED_AWAITING_BROKER_RECONCILIATION",
      brokerResponse: { order: execution().order }
    }),
    confirmFromBroker: async ({ brokerPosition }) => {
      confirmed = brokerPosition.positionId === "777";
      return { confirmed, safe: confirmed, status: "BROKER_FILLED_PROTECTED_POSITION_DURABLY_RECORDED", positionId: "777" };
    }
  });
  assert.equal(reconciled, true);
  assert.equal(confirmed, true);
  assert.equal(result.safe, true);
});

test("leaves the submitted intent unresolved when broker order identity is missing", async () => {
  let confirmCalled = false;
  const result = await submitAndConfirmCTraderDemoOrder({
    ...base,
    submitOnce: async () => ({
      submitted: true,
      status: "SUBMITTED_AWAITING_BROKER_RECONCILIATION",
      brokerResponse: { order: { positionId: "777" }, position: execution().position }
    }),
    confirmFromBroker: async () => { confirmCalled = true; return { confirmed: true, safe: true }; }
  });
  assert.equal(result.status, "SUBMITTED_BROKER_ORDER_IDENTITY_UNCONFIRMED");
  assert.equal(confirmCalled, false);
});

test("rejects a position that does not match the broker order's linked position ID", async () => {
  let confirmCalled = false;
  const response = execution("777");
  response.position.positionId = "888";
  const result = await submitAndConfirmCTraderDemoOrder({
    ...base,
    submitOnce: async () => ({ submitted: true, brokerResponse: response }),
    confirmFromBroker: async () => { confirmCalled = true; return { confirmed: true, safe: true }; }
  });
  assert.equal(result.status, "SUBMITTED_BROKER_POSITION_LINK_MISMATCH");
  assert.equal(confirmCalled, false);
});

test("does not reconcile or confirm when submission outcome is unknown", async () => {
  let reconcileCalled = false;
  const result = await submitAndConfirmCTraderDemoOrder({
    ...base,
    session: { reconcile: async () => { reconcileCalled = true; return { positions: [] }; } },
    submitOnce: async () => ({
      submitted: false,
      safe: false,
      status: "ORDER_RESULT_UNKNOWN_RECONCILIATION_REQUIRED"
    }),
    confirmFromBroker: async () => { throw new Error("must not run"); }
  });
  assert.equal(result.status, "ORDER_RESULT_UNKNOWN_RECONCILIATION_REQUIRED");
  assert.equal(reconcileCalled, false);
});
