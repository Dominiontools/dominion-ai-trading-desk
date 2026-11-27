import test from "node:test";
import assert from "node:assert/strict";
import {
  reconcileCTraderPositionState,
  assertNoUnresolvedCTraderOrderIntents
} from "../src/cloudflare/ctrader-execution-reconciliation.js";

const brokerPosition = {
  positionId: 88,
  tradeData: { symbolId: 10, tradeSide: 1, volume: 1000 },
  stopLoss: 1.09,
  takeProfit: 1.13
};
const storedPosition = {
  positionId: "88",
  position: { symbolId: 10, side: "BUY", volume: 1000, stopLoss: 1.09, target3R: 1.13 }
};

test("flat broker and empty recovery store reconcile safely", () => {
  assert.deepEqual(reconcileCTraderPositionState({ brokerPositions: [], storedPosition: null }), {
    safe: true, state: "FLAT", position: null
  });
});

test("matching broker and D1 position including protection reconciles", () => {
  const result = reconcileCTraderPositionState({ brokerPositions: [brokerPosition], storedPosition });
  assert.equal(result.safe, true);
  assert.equal(result.state, "POSITION_RECONCILED");
  assert.equal(result.positionId, "88");
});

test("a broker position missing from D1 fails closed", () => {
  const result = reconcileCTraderPositionState({ brokerPositions: [brokerPosition], storedPosition: null });
  assert.equal(result.safe, false);
  assert.equal(result.reason, "UNTRACKED_BROKER_POSITION");
});

test("a D1 position missing at broker fails closed", () => {
  const result = reconcileCTraderPositionState({ brokerPositions: [], storedPosition });
  assert.equal(result.safe, false);
  assert.equal(result.reason, "D1_POSITION_MISSING_AT_BROKER");
});

test("volume, side, symbol, or protection disagreement fails closed", () => {
  const changed = { ...brokerPosition, tradeData: { ...brokerPosition.tradeData, volume: 900 } };
  const result = reconcileCTraderPositionState({ brokerPositions: [changed], storedPosition });
  assert.equal(result.safe, false);
  assert.ok(result.mismatches.includes("VOLUME"));
  const unprotected = { ...brokerPosition, stopLoss: 0 };
  assert.ok(reconcileCTraderPositionState({ brokerPositions: [unprotected], storedPosition }).mismatches.includes("BROKER_PROTECTION_MISSING"));
});

test("multiple broker positions and malformed snapshots fail closed", () => {
  assert.equal(reconcileCTraderPositionState({
    brokerPositions: [brokerPosition, brokerPosition], storedPosition
  }).reason, "MULTIPLE_BROKER_POSITIONS");
  assert.throws(() => reconcileCTraderPositionState({
    brokerPositions: [{ ...brokerPosition, positionId: "live" }], storedPosition
  }), /invalid position ID/);
});

test("unresolved intents block fresh entries", () => {
  assert.deepEqual(assertNoUnresolvedCTraderOrderIntents([]), { safe: true });
  const blocked = assertNoUnresolvedCTraderOrderIntents([{ clientOrderId: "order_123" }]);
  assert.equal(blocked.safe, false);
  assert.equal(blocked.reason, "UNRESOLVED_ORDER_INTENT");
});

test("missing durable D1 stop-loss or take-profit fails closed", () => {
  const incomplete = {
    ...storedPosition,
    position: { symbolId: 10, side: "BUY", volume: 1000 }
  };
  const result = reconcileCTraderPositionState({
    brokerPositions: [brokerPosition], storedPosition: incomplete
  });
  assert.equal(result.safe, false);
  assert.ok(result.mismatches.includes("D1_PROTECTION_MISSING"));
});

test("legacy durable snapshot aliases reconcile the original protected stop", () => {
  const legacy = {
    positionId: "88",
    position: {
      symbolId: 10, side: "BUY", volume: 1000,
      initialStopLoss: 1.09, target3R: 1.13,
      entryPrice: 1.10, breakEvenSet: false
    }
  };
  assert.equal(reconcileCTraderPositionState({
    brokerPositions: [brokerPosition], storedPosition: legacy
  }).safe, true);
});

test("legacy durable snapshot expects entry stop after break-even is confirmed", () => {
  const legacy = {
    positionId: "88",
    position: {
      symbolId: 10, side: "BUY", volume: 1000,
      initialStopLoss: 1.09, target3R: 1.13,
      entryPrice: 1.10, breakEvenSet: true
    }
  };
  const atBreakEven = { ...brokerPosition, stopLoss: 1.10 };
  assert.equal(reconcileCTraderPositionState({
    brokerPositions: [atBreakEven], storedPosition: legacy
  }).safe, true);
  assert.ok(reconcileCTraderPositionState({
    brokerPositions: [brokerPosition], storedPosition: legacy
  }).mismatches.includes("STOP_LOSS"));
});
