import {
  reserveCTraderOrderIntent,
  transitionCTraderOrderIntent
} from "./ctrader-execution-recovery-store.js";

/**
 * Submit exactly once after durable reservation. A timeout or transport error
 * is UNKNOWN, never a reason to retry. Broker reconciliation must resolve it.
 */
export async function submitCTraderDemoOrderOnce({
  db,
  session,
  accountId,
  clientOrderId,
  intent,
  order,
  nowMs = Date.now()
}) {
  if (!session || typeof session.newMarketRangeOrder !== "function") {
    throw new Error("A verified cTrader demo session is required.");
  }
  const reserved = await reserveCTraderOrderIntent(db, {
    accountId, clientOrderId, intent, nowMs
  });
  if (!reserved) {
    return { submitted: false, safe: false, status: "DUPLICATE_ORDER_INTENT" };
  }

  const marked = await transitionCTraderOrderIntent(db, {
    clientOrderId, accountId, fromState: "PREPARED", toState: "SUBMITTED", nowMs
  });
  if (!marked) {
    return { submitted: false, safe: false, status: "ORDER_INTENT_STATE_CONFLICT" };
  }

  try {
    const brokerResponse = await session.newMarketRangeOrder({
      ...order,
      clientOrderId
    });
    return {
      submitted: true,
      safe: true,
      status: "SUBMITTED_AWAITING_BROKER_RECONCILIATION",
      clientOrderId,
      brokerResponse
    };
  } catch {
    await transitionCTraderOrderIntent(db, {
      clientOrderId, accountId, fromState: "SUBMITTED", toState: "UNKNOWN", nowMs: Date.now()
    });
    return {
      submitted: false,
      safe: false,
      status: "ORDER_RESULT_UNKNOWN_RECONCILIATION_REQUIRED",
      clientOrderId
    };
  }
}
