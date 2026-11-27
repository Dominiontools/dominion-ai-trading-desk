import {
  readCTraderActivePosition,
  saveCTraderActivePosition,
  transitionCTraderOrderIntent
} from "./ctrader-execution-recovery-store.js";

function positive(value, field) {
  const number = Number(value);
  if (!Number.isFinite(number) || number <= 0) {
    throw new Error(`Broker-confirmed order is missing valid ${field}.`);
  }
  return number;
}

/**
 * Resolve a submitted/unknown intent only when broker order evidence carries
 * the exact clientOrderId and a matching protected open position is present.
 * No matching-by-symbol/volume heuristic is allowed.
 */
export async function confirmCTraderDemoOrderFromBroker({
  db,
  accountId,
  clientOrderId,
  fromState,
  brokerOrder,
  brokerPosition,
  management = {},
  nowMs = Date.now()
}) {
  if (!["SUBMITTED", "UNKNOWN"].includes(fromState)) {
    throw new Error("Only submitted or unknown order intents can be broker-confirmed.");
  }
  if (String(brokerOrder?.clientOrderId ?? "") !== clientOrderId) {
    return { confirmed: false, safe: false, status: "BROKER_ORDER_IDENTITY_NOT_CONFIRMED" };
  }
  if (!brokerPosition || typeof brokerPosition !== "object") {
    return { confirmed: false, safe: false, status: "BROKER_POSITION_NOT_CONFIRMED" };
  }

  const positionId = String(brokerPosition.positionId ?? "");
  if (!/^\d{1,30}$/.test(positionId)) {
    throw new Error("Broker-confirmed position ID is invalid.");
  }
  const trade = brokerPosition.tradeData && typeof brokerPosition.tradeData === "object"
    ? brokerPosition.tradeData : {};
  const symbolId = positive(trade.symbolId, "symbol ID");
  const volume = positive(trade.volume, "volume");
  const side = Number(trade.tradeSide) === 1 ? "BUY" :
    Number(trade.tradeSide) === 2 ? "SELL" : "";
  if (!side) throw new Error("Broker-confirmed position side is invalid.");
  const stopLoss = positive(brokerPosition.stopLoss, "stop-loss");
  const takeProfit = positive(brokerPosition.takeProfit, "take-profit");
  const entryPrice = positive(brokerPosition.price, "entry price");

  const existing = await readCTraderActivePosition(db, accountId);
  if (existing && existing.positionId !== positionId) {
    return { confirmed: false, safe: false, status: "DIFFERENT_ACTIVE_POSITION_ALREADY_STORED" };
  }

  const canonical = {
    ...management,
    symbolId,
    side,
    volume,
    stopLoss,
    takeProfit,
    entryPrice,
    brokerConfirmed: true,
    clientOrderId
  };
  await saveCTraderActivePosition(db, {
    accountId, positionId, position: canonical, nowMs
  });

  const transitioned = await transitionCTraderOrderIntent(db, {
    clientOrderId, accountId, fromState, toState: "FILLED",
    brokerPositionId: positionId, nowMs
  });
  if (!transitioned) {
    return {
      confirmed: false,
      safe: false,
      status: "BROKER_POSITION_SAVED_ORDER_INTENT_TRANSITION_CONFLICT",
      positionId
    };
  }
  return {
    confirmed: true,
    safe: true,
    status: "BROKER_FILLED_PROTECTED_POSITION_DURABLY_RECORDED",
    positionId,
    position: canonical
  };
}
