function numericId(value) {
  const id = String(value ?? "");
  if (!/^\d{1,30}$/.test(id)) throw new Error("Broker reconciliation contains an invalid position ID.");
  return id;
}

function positiveNumber(value, field) {
  const number = Number(value);
  if (!Number.isFinite(number) || number <= 0) {
    throw new Error(`Broker reconciliation contains invalid ${field}.`);
  }
  return number;
}

/**
 * Compare the broker's authoritative open-position snapshot with the durable
 * D1 snapshot before an engine is allowed to evaluate a new entry.
 * Any manual, extra, missing, or materially changed position fails closed.
 */
export function reconcileCTraderPositionState({ brokerPositions, storedPosition }) {
  if (!Array.isArray(brokerPositions)) throw new Error("A broker position list is required.");
  if (brokerPositions.length > 1) {
    return { safe: false, reason: "MULTIPLE_BROKER_POSITIONS", brokerPositionCount: brokerPositions.length };
  }
  if (brokerPositions.length === 0 && storedPosition == null) {
    return { safe: true, state: "FLAT", position: null };
  }
  if (brokerPositions.length === 0 || storedPosition == null) {
    return {
      safe: false,
      reason: brokerPositions.length === 0 ? "D1_POSITION_MISSING_AT_BROKER" : "UNTRACKED_BROKER_POSITION",
      brokerPositionCount: brokerPositions.length
    };
  }

  const broker = brokerPositions[0];
  const brokerId = numericId(broker?.positionId);
  const storedId = numericId(storedPosition.positionId);
  const brokerTrade = broker.tradeData && typeof broker.tradeData === "object" ? broker.tradeData : {};
  const stored = storedPosition.position;
  if (!stored || typeof stored !== "object" || Array.isArray(stored)) {
    throw new Error("Stored cTrader position snapshot is invalid.");
  }

  const brokerSymbolId = positiveNumber(brokerTrade.symbolId, "symbol ID");
  const storedSymbolId = positiveNumber(stored.symbolId, "stored symbol ID");
  const brokerVolume = positiveNumber(brokerTrade.volume, "volume");
  const storedVolume = positiveNumber(stored.volume ?? stored.remainingVolume, "stored volume");
  const brokerSide = Number(brokerTrade.tradeSide) === 1 ? "BUY" :
    Number(brokerTrade.tradeSide) === 2 ? "SELL" : "";
  const storedSide = String(stored.side ?? "");
  const brokerStop = Number(broker.stopLoss ?? 0);
  const brokerTarget = Number(broker.takeProfit ?? 0);
  const storedStop = Number(stored.stopLoss ?? 0);
  const storedTarget = Number(stored.takeProfit ?? stored.target3R ?? 0);

  const mismatches = [];
  if (brokerId !== storedId) mismatches.push("POSITION_ID");
  if (brokerSymbolId !== storedSymbolId) mismatches.push("SYMBOL");
  if (!brokerSide || brokerSide !== storedSide) mismatches.push("SIDE");
  if (Math.abs(brokerVolume - storedVolume) > 0.000001) mismatches.push("VOLUME");
  if (!(brokerStop > 0) || !(brokerTarget > 0)) mismatches.push("BROKER_PROTECTION_MISSING");
  if (storedStop > 0 && Math.abs(brokerStop - storedStop) > 1e-8) mismatches.push("STOP_LOSS");
  if (storedTarget > 0 && Math.abs(brokerTarget - storedTarget) > 1e-8) mismatches.push("TAKE_PROFIT");

  if (mismatches.length) {
    return { safe: false, reason: "BROKER_D1_POSITION_MISMATCH", mismatches, brokerPositionId: brokerId, storedPositionId: storedId };
  }
  return { safe: true, state: "POSITION_RECONCILED", positionId: brokerId, symbolId: brokerSymbolId, side: brokerSide, volume: brokerVolume };
}

/** Any non-terminal order intent blocks a new order; never retry an uncertain submit blindly. */
export function assertNoUnresolvedCTraderOrderIntents(intents) {
  if (!Array.isArray(intents)) throw new Error("A verified order-intent list is required.");
  if (intents.length) {
    return {
      safe: false,
      reason: "UNRESOLVED_ORDER_INTENT",
      clientOrderIds: intents.map((item) => String(item?.clientOrderId ?? "")).filter(Boolean)
    };
  }
  return { safe: true };
}
