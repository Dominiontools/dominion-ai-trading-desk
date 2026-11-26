import test from "node:test";
import assert from "node:assert/strict";
import { closeAndVerify } from "../lib/ctrader-close.mjs";

test("closeAndVerify reports flat only after broker reconciliation removes the position", async () => {
  const calls = [];
  const session = {
    async closePosition(id, volume) { calls.push(["close", id, volume]); },
    async reconcile() { calls.push(["reconcile"]); return { positions: [] }; },
  };
  assert.deepEqual(await closeAndVerify(session, 42, 1000), {
    closed: true, remainingVolume: 0,
  });
  assert.deepEqual(calls, [["close", 42, 1000], ["reconcile"]]);
});

test("closeAndVerify retains remaining broker volume when a close is partial or pending", async () => {
  const remaining = { positionId: 42, tradeData: { volume: 400 } };
  const session = {
    async closePosition() {},
    async reconcile() { return { positions: [remaining] }; },
  };
  const result = await closeAndVerify(session, 42, 600);
  assert.equal(result.closed, false);
  assert.equal(result.remaining, remaining);
  assert.equal(result.remainingVolume, 400);
});

test("closeAndVerify rejects invalid requests before calling the broker", async () => {
  let called = false;
  const session = {
    async closePosition() { called = true; },
    async reconcile() { return { positions: [] }; },
  };
  await assert.rejects(() => closeAndVerify(session, 0, 10), /INVALID_POSITION_CLOSE_REQUEST/);
  await assert.rejects(() => closeAndVerify(session, 42, Number.NaN), /INVALID_POSITION_CLOSE_REQUEST/);
  assert.equal(called, false);
});

test("closeAndVerify fails closed when broker reconciliation is malformed", async () => {
  const session = {
    async closePosition() {},
    async reconcile() { return {}; },
  };
  await assert.rejects(() => closeAndVerify(session, 42, 10), /POSITION_CLOSE_RECONCILIATION_INVALID/);
});

test("closeAndVerify trusts broker reconciliation when the close response times out but the position is flat", async () => {
  const session = {
    async closePosition() { throw new Error("socket timed out"); },
    async reconcile() { return { positions: [] }; },
  };
  const result = await closeAndVerify(session, 42, 1000);
  assert.equal(result.closed, true);
  assert.equal(result.closeRequestError, "Error");
});

test("closeAndVerify returns the actual remaining volume after a close timeout", async () => {
  const session = {
    async closePosition() { throw new Error("socket timed out"); },
    async reconcile() {
      return { positions: [{ positionId: 42, tradeData: { volume: 250 } }] };
    },
  };
  const result = await closeAndVerify(session, 42, 1000);
  assert.equal(result.closed, false);
  assert.equal(result.remainingVolume, 250);
  assert.equal(result.closeRequestError, "Error");
});
