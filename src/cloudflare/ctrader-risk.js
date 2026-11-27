export const MAX_RISK_PER_TRADE = 0.005;

export function moneyScale(digits) {
  if (!Number.isInteger(digits) || digits < 0 || digits > 10) throw new Error("INVALID_MONEY_DIGITS");
  return 10 ** digits;
}

export function calculateDailyRisk(balance, moneyDigits, deals, cashFlows) {
  const scale = moneyScale(moneyDigits);
  if (!Array.isArray(deals) || !Array.isArray(cashFlows)) throw new Error("INVALID_DAILY_RISK_HISTORY");
  const dealPnl = deals.reduce((sum, deal) => {
    const detail = deal?.closePositionDetail;
    if (!detail) return sum;
    const digits = Number(detail.moneyDigits ?? deal.moneyDigits ?? moneyDigits);
    const dealScale = moneyScale(digits);
    const gross = Number(detail.grossProfit ?? 0);
    const swap = Number(detail.swap ?? 0);
    const commission = Number(detail.commission ?? 0);
    const conversionFee = Number(detail.pnlConversionFee ?? 0);
    if (![gross, swap, commission, conversionFee].every(Number.isFinite)) throw new Error("INVALID_DAILY_DEAL_PNL");
    return sum + (gross + swap + commission + conversionFee) / dealScale;
  }, 0);

  let capitalFlows = 0;
  let otherCashFlowPnl = 0;
  for (const flow of cashFlows) {
    const digits = Number(flow?.moneyDigits ?? moneyDigits);
    const deltaRaw = Number(flow?.delta ?? 0);
    const operationType = Number(flow?.operationType);
    if (!Number.isFinite(deltaRaw) || !Number.isFinite(operationType)) throw new Error("INVALID_DAILY_CASH_FLOW");
    const delta = deltaRaw / moneyScale(digits);
    if (operationType === 0 || operationType === 1) capitalFlows += delta;
    else otherCashFlowPnl += delta;
  }

  const dailyNetPnl = dealPnl + otherCashFlowPnl;
  const equity = Number(balance) / scale;
  const startingEquity = equity - dailyNetPnl - capitalFlows;
  if (!(equity > 0) || !(startingEquity > 0) ||
      ![equity, dailyNetPnl, startingEquity].every(Number.isFinite)) {
    throw new Error("INVALID_ACCOUNT_EQUITY");
  }
  const dailyLossFraction = Math.max(0, -dailyNetPnl / startingEquity);
  return { equity, dailyNetPnl, startingEquity, dailyLossFraction };
}

export function estimateRoundTripCommission(symbol, volumeCents, entryPrice) {
  const rate = Number(symbol?.preciseTradingCommissionRate);
  const lotSize = Number(symbol?.lotSize);
  const commissionType = Number(symbol?.commissionType ?? 1);
  if (!Number.isFinite(rate) || rate < 0 || !(lotSize > 0)) throw new Error("UNVERIFIED_BROKER_COMMISSION");
  const units = volumeCents / 100;
  const lots = volumeCents / lotSize;
  const notionalUsd = units * entryPrice;
  let perSide = 0;
  if (commissionType === 1) perSide = (rate / 1e8) * (notionalUsd / 1_000_000);
  else if (commissionType === 2) perSide = (rate / 1e8) * lots;
  else if (commissionType === 3) perSide = (rate / 1e7) * notionalUsd;
  else if (commissionType === 4) perSide = (rate / 1e8) * lots;
  else throw new Error("UNSUPPORTED_BROKER_COMMISSION_TYPE");
  const minAsset = String(symbol.minCommissionAsset ?? "USD").toUpperCase();
  if (minAsset !== "USD") throw new Error("UNSUPPORTED_MINIMUM_COMMISSION_CURRENCY");
  const minimum = Number(symbol.preciseMinCommission ?? 0) / 1e8;
  if (!Number.isFinite(perSide) || perSide < 0 || !Number.isFinite(minimum) || minimum < 0) {
    throw new Error("INVALID_BROKER_COMMISSION");
  }
  return 2 * Math.max(perSide, minimum);
}

export function sizeVolume(symbol, entryPrice, stopDistance, equity, riskFraction = MAX_RISK_PER_TRADE) {
  const minVolume = Number(symbol?.minVolume);
  const maxVolume = Number(symbol?.maxVolume);
  const stepVolume = Number(symbol?.stepVolume);
  if (!(minVolume > 0) || !(maxVolume >= minVolume) || !(stepVolume > 0)) throw new Error("BROKER_VOLUME_RULES_MISSING");
  if (!(entryPrice > 0) || !(stopDistance > 0) || !(equity > 0)) throw new Error("INVALID_TRADE_PRICES");
  if (!Number.isFinite(riskFraction) || riskFraction <= 0 || riskFraction > MAX_RISK_PER_TRADE) {
    throw new Error("RISK_FRACTION_EXCEEDS_HARD_LIMIT");
  }
  const riskBudget = equity * riskFraction;
  const rawVolume = Math.floor((riskBudget / stopDistance) * 100);
  let volume = Math.min(maxVolume, Math.floor(rawVolume / stepVolume) * stepVolume);
  for (let attempts = 0; attempts < 10_000 && volume >= minVolume; attempts++, volume -= stepVolume) {
    const riskAmount = (volume / 100) * stopDistance;
    const commission = estimateRoundTripCommission(symbol, volume, entryPrice);
    if (riskAmount + commission <= riskBudget + 1e-9) return { volume, riskAmount, commission };
  }
  throw new Error("BROKER_MINIMUM_VOLUME_EXCEEDS_RISK_BUDGET");
}

export function classifyPartialClose({ originalVolume, remainingVolume, requestedCloseVolume, stepVolume, minVolume }) {
  const values = [originalVolume, remainingVolume, requestedCloseVolume, stepVolume, minVolume].map(Number);
  if (values.some((value) => !Number.isFinite(value) || value < 0) ||
      !(values[0] > 0) || !(values[2] > 0) || !(values[3] > 0) || !(values[4] > 0) ||
      values[1] > values[0]) throw new Error("INVALID_PARTIAL_CLOSE_RECONCILIATION");
  const [original, remaining, requested, step, minimum] = values;
  if (remaining === 0) return { status: "FULLY_CLOSED", closedVolume: original, remainingVolume: 0, outstandingVolume: 0 };
  const closedVolume = original - remaining;
  const tolerance = step / 2;
  const outstandingVolume = Math.max(0, requested - closedVolume);
  if (remaining < minimum) return { status: "REMAINDER_BELOW_MINIMUM", closedVolume, remainingVolume: remaining, outstandingVolume };
  if (closedVolume + tolerance < requested) return { status: "PARTIAL_CLOSE_INCOMPLETE", closedVolume, remainingVolume: remaining, outstandingVolume };
  return { status: "PARTIAL_CLOSE_CONFIRMED", closedVolume, remainingVolume: remaining, outstandingVolume: 0 };
}

export function planPartialClose({ currentVolume, minVolume, stepVolume, pendingTargetVolume = 0 }) {
  const current = Number(currentVolume);
  const minimum = Number(minVolume);
  const step = Number(stepVolume);
  const pending = Number(pendingTargetVolume);
  if (![current, minimum, step, pending].every(Number.isFinite) ||
      !(current > 0) || !(minimum > 0) || !(step > 0) || pending < 0) throw new Error("INVALID_PARTIAL_CLOSE_PLAN");
  const requested = pending > 0 ? Math.min(current, pending) : Math.floor((current / 2) / step) * step;
  if (requested >= minimum && current - requested >= minimum) {
    return { action: "PARTIAL_CLOSE", requestedVolume: requested, resumesPendingTarget: pending > 0 };
  }
  return { action: "FULL_CLOSE", requestedVolume: current, resumesPendingTarget: false };
}
