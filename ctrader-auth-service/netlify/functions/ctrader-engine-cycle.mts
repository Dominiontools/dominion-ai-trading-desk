import { getStore } from "@netlify/blobs";
import { randomUUID } from "node:crypto";
import {
  CTraderDemoSession,
  loadTradingCredentials,
  trendbarsToCandles,
} from "../lib/ctrader-demo-session.mts";
import {
  evaluateConfluence,
  TIMEFRAME_PROFILES,
  type StrategyProfile,
} from "../lib/ctrader-strategy.mts";

const MAX_RISK_PER_TRADE = 0.005;
const MAX_DAILY_LOSS = 0.02;
const MAX_SPREAD_BPS = 20;
const MAX_SLIPPAGE_BPS = 15;
const MAX_QUOTE_AGE_SECONDS = 10;
const MAX_MARGIN_FRACTION = 0.5;
const DEFAULT_SYMBOLS = ["XAUUSD", "EURUSD", "GBPUSD"];

type RecordData = Record<string, unknown>;
type Candidate = {
  symbolName: string;
  symbolId: number;
  symbol: RecordData;
  lightSymbol: RecordData;
  setup: NonNullable<ReturnType<typeof evaluateConfluence>>;
  bid: number;
  ask: number;
  quoteTimestamp: number;
  spreadBps: number;
};

function number(value: unknown): number {
  return Number(value);
}

function normalizeSymbol(value: unknown): string {
  return String(value ?? "").replace(/[\s/_.-]/g, "").toUpperCase();
}

function utcDayStart(now: Date): number {
  return Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
}

function moneyScale(digits: number): number {
  if (!Number.isInteger(digits) || digits < 0 || digits > 10) {
    throw new Error("INVALID_MONEY_DIGITS");
  }
  return 10 ** digits;
}

function calculateDailyRisk(
  balance: number,
  moneyDigits: number,
  deals: RecordData[],
  cashFlows: RecordData[],
): { equity: number; dailyNetPnl: number; startingEquity: number; dailyLossFraction: number } {
  const scale = moneyScale(moneyDigits);
  const dailyNetPnl = deals.reduce((sum, deal) => {
    const detail = deal.closePositionDetail as RecordData | undefined;
    if (!detail) return sum;
    const digits = Number(detail.moneyDigits ?? deal.moneyDigits ?? moneyDigits);
    const dealScale = moneyScale(digits);
    const gross = number(detail.grossProfit ?? 0);
    const swap = number(detail.swap ?? 0);
    const commission = number(detail.commission ?? 0);
    const conversionFee = number(detail.pnlConversionFee ?? 0);
    return sum + (gross + swap + commission + conversionFee) / dealScale;
  }, 0);
  let capitalFlows = 0;
  let otherCashFlowPnl = 0;
  for (const flow of cashFlows) {
    const digits = Number(flow.moneyDigits ?? moneyDigits);
    const delta = number(flow.delta ?? 0) / moneyScale(digits);
    const operationType = number(flow.operationType);
    if (operationType === 0 || operationType === 1) capitalFlows += delta;
    else otherCashFlowPnl += delta;
  }
  const totalDailyPnl = dailyNetPnl + otherCashFlowPnl;
  const equity = balance / scale;
  const startingEquity = equity - totalDailyPnl - capitalFlows;
  if (!(equity > 0) || !(startingEquity > 0)) throw new Error("INVALID_ACCOUNT_EQUITY");
  const dailyLossFraction = Math.max(0, -totalDailyPnl / startingEquity);
  return { equity, dailyNetPnl: totalDailyPnl, startingEquity, dailyLossFraction };
}

function estimateRoundTripCommission(
  symbol: RecordData,
  volumeCents: number,
  entryPrice: number,
): number {
  const rate = number(symbol.preciseTradingCommissionRate);
  const lotSize = number(symbol.lotSize);
  const commissionType = number(symbol.commissionType ?? 1);
  if (!Number.isFinite(rate) || rate < 0 || !(lotSize > 0)) {
    throw new Error("UNVERIFIED_BROKER_COMMISSION");
  }
  const units = volumeCents / 100;
  const lots = volumeCents / lotSize;
  const notionalUsd = units * entryPrice;
  let perSide = 0;
  if (commissionType === 1) {
    perSide = (rate / 1e8) * (notionalUsd / 1_000_000);
  } else if (commissionType === 2) {
    perSide = (rate / 1e8) * lots;
  } else if (commissionType === 3) {
    perSide = (rate / 1e7) * notionalUsd;
  } else if (commissionType === 4) {
    perSide = (rate / 1e8) * lots;
  } else {
    throw new Error("UNSUPPORTED_BROKER_COMMISSION_TYPE");
  }
  const minAsset = String(symbol.minCommissionAsset ?? "USD").toUpperCase();
  if (minAsset !== "USD") throw new Error("UNSUPPORTED_MINIMUM_COMMISSION_CURRENCY");
  const minimum = number(symbol.preciseMinCommission ?? 0) / 1e8;
  if (!Number.isFinite(perSide) || perSide < 0 || !Number.isFinite(minimum) || minimum < 0) {
    throw new Error("INVALID_BROKER_COMMISSION");
  }
  return 2 * Math.max(perSide, minimum);
}

function sizeVolume(
  symbol: RecordData,
  entryPrice: number,
  stopDistance: number,
  equity: number,
): { volume: number; riskAmount: number; commission: number } {
  const minVolume = number(symbol.minVolume);
  const maxVolume = number(symbol.maxVolume);
  const stepVolume = number(symbol.stepVolume);
  if (!(minVolume > 0) || !(maxVolume >= minVolume) || !(stepVolume > 0)) {
    throw new Error("BROKER_VOLUME_RULES_MISSING");
  }
  if (!(entryPrice > 0) || !(stopDistance > 0)) throw new Error("INVALID_TRADE_PRICES");
  const riskBudget = equity * MAX_RISK_PER_TRADE;
  const rawVolume = Math.floor((riskBudget / stopDistance) * 100);
  let volume = Math.min(maxVolume, Math.floor(rawVolume / stepVolume) * stepVolume);
  for (let attempts = 0; attempts < 10000 && volume >= minVolume; attempts++, volume -= stepVolume) {
    const riskAmount = (volume / 100) * stopDistance;
    const commission = estimateRoundTripCommission(symbol, volume, entryPrice);
    if (riskAmount + commission <= riskBudget + 1e-9) {
      return { volume, riskAmount, commission };
    }
  }
  throw new Error("BROKER_MINIMUM_VOLUME_EXCEEDS_RISK_BUDGET");
}

function buildCandidate(
  symbolName: string,
  lightSymbol: RecordData,
  symbol: RecordData,
  spot: RecordData,
  executionBars: RecordData[],
  contextBars: RecordData[],
  profile: StrategyProfile,
  scoreThreshold: number,
  now: Date,
): Candidate | null {
  const symbolId = number(lightSymbol.symbolId);
  const digits = number(symbol.digits);
  const bid = number(spot.bid) / 100000;
  const ask = number(spot.ask) / 100000;
  const quoteTimestamp = number(spot.timestamp);
  if (!(symbolId > 0) || !(digits >= 0) || !(bid > 0) || !(ask >= bid) ||
      !Number.isFinite(quoteTimestamp)) throw new Error("INVALID_CTRADER_SPOT");
  const quoteAge = (now.getTime() - quoteTimestamp) / 1000;
  if (quoteAge < 0 || quoteAge > MAX_QUOTE_AGE_SECONDS) throw new Error("STALE_CTRADER_QUOTE");
  const mid = (bid + ask) / 2;
  const spreadBps = ((ask - bid) / mid) * 10000;
  if (spreadBps > MAX_SPREAD_BPS) throw new Error("CTRADER_SPREAD_TOO_WIDE");
  if (number(symbol.tradingMode ?? 0) !== 0) throw new Error("CTRADER_SYMBOL_NOT_TRADABLE");
  const setup = evaluateConfluence(
    trendbarsToCandles(symbolName, symbolName.startsWith("XAU") ? "GOLD" : "FOREX",
      TIMEFRAME_PROFILES[profile].execution, executionBars,
      TIMEFRAME_PROFILES[profile].executionSeconds, now.getTime()),
    trendbarsToCandles(symbolName, symbolName.startsWith("XAU") ? "GOLD" : "FOREX",
      TIMEFRAME_PROFILES[profile].context, contextBars,
      TIMEFRAME_PROFILES[profile].contextSeconds, now.getTime()),
    profile, now, scoreThreshold,
  );
  if (!setup) return null;
  return { symbolName, symbolId, symbol, lightSymbol, setup, bid, ask, quoteTimestamp, spreadBps };
}

async function appendEvent(store: ReturnType<typeof getStore>, event: RecordData): Promise<void> {
  const previous = await store.get("account/engine-events", { type: "json" }) as RecordData[] | null;
  const events = Array.isArray(previous) ? previous : [];
  events.push({ ...event, recordedAt: new Date().toISOString() });
  await store.setJSON("account/engine-events", events.slice(-200));
}

async function saveStatus(store: ReturnType<typeof getStore>, status: RecordData): Promise<void> {
  await store.setJSON("account/engine-status", {
    ...status,
    updatedAt: new Date().toISOString(),
    environment: "demo",
    liveTradingEnabled: false,
  });
}

async function executeCycle(): Promise<RecordData> {
  const store = getStore({ name: "dominion-ctrader-oauth-prod", consistency: "strong" });
  const config = await store.get("account/engine-config", { type: "json" }) as RecordData | null;
  const enabled = config?.enabled === true;
  if (!enabled) {
    const paused = { status: "PAUSED", reason: "DEMO_AUTOMATION_DISABLED", mode: "DEMO_ONLY" };
    await saveStatus(store, paused);
    return paused;
  }

  const profile = String(config?.profile ?? "intraday") as StrategyProfile;
  if (!(profile in TIMEFRAME_PROFILES)) {
    const invalid = { status: "BLOCKED", reason: "INVALID_STRATEGY_PROFILE", mode: "DEMO_ONLY" };
    await saveStatus(store, invalid);
    return invalid;
  }
  const scoreThreshold = number(config?.scoreThreshold ?? 6);
  const requestedSymbols = Array.isArray(config?.symbols)
    ? config.symbols.map(normalizeSymbol).filter(Boolean)
    : DEFAULT_SYMBOLS;
  if (!requestedSymbols.length || requestedSymbols.length > 20) {
    const invalid = { status: "BLOCKED", reason: "INVALID_SYMBOL_WATCHLIST", mode: "DEMO_ONLY" };
    await saveStatus(store, invalid);
    return invalid;
  }

  const credentials = await loadTradingCredentials();
  const session = new CTraderDemoSession();
  const now = new Date();
  try {
    await session.connect();
    await session.authorize(
      credentials.accessToken, credentials.authorizedAccountId,
      credentials.clientId, credentials.clientSecret,
    );

    const [trader, accountState, symbols, assets] = await Promise.all([
      session.trader(),
      session.reconcile(),
      session.symbols(),
      session.assets(),
    ]);
    const moneyDigits = number(trader.moneyDigits);
    const balance = number(trader.balance);
    const assetById = new Map(assets.map((asset) => [String(asset.assetId), String(asset.name ?? "").toUpperCase()]));
    const depositAssetId = String(trader.depositAssetId ?? "");
    const depositAsset = assetById.get(depositAssetId);
    if (depositAsset !== "USD") throw new Error("USD_DEPOSIT_ACCOUNT_REQUIRED_FOR_INITIAL_RISK_MODEL");

    const dayStart = utcDayStart(now);
    const [deals, cashFlows] = await Promise.all([
      session.deals(dayStart, now.getTime()),
      session.cashFlows(dayStart, now.getTime()),
    ]);
    if (deals.hasMore) throw new Error("DAILY_DEAL_HISTORY_INCOMPLETE");
    const daily = calculateDailyRisk(balance, moneyDigits, deals.deals, cashFlows);
    const activePosition = await store.get("account/active-position", { type: "json" }) as RecordData | null;

    if (accountState.positions.length > 0) {
      const position = accountState.positions[0];
      if (accountState.positions.length > 1) throw new Error("MULTIPLE_OPEN_POSITIONS_DETECTED");
      const positionId = number(position.positionId);
      const tradeData = position.tradeData as RecordData | undefined;
      const volume = number(tradeData?.volume);
      const isDominionPosition = String(tradeData?.label ?? "") === "DOMINION_AI_DEMO" ||
        number(activePosition?.positionId) === positionId;
      const hasProtection = number(position.stopLoss) > 0 && number(position.takeProfit) > 0;
      if (!hasProtection) {
        if (!isDominionPosition) {
          const manualUnprotected = {
            status: "MANUAL_POSITION_UNPROTECTED_BLOCK",
            reason: "UNPROTECTED_MANUAL_POSITION_NOT_TOUCHED",
            positionId, mode: "DEMO_ONLY",
          };
          await saveStatus(store, manualUnprotected);
          return manualUnprotected;
        }
        if (!(positionId > 0) || !(volume > 0)) throw new Error("UNPROTECTED_POSITION_CANNOT_BE_CLOSED");
        await session.closePosition(positionId, volume);
        await store.delete("account/active-position");
        const emergency = { status: "EMERGENCY_CLOSE_SENT", reason: "OPEN_POSITION_MISSING_PROTECTIVE_SL_TP", positionId, mode: "DEMO_ONLY" };
        await saveStatus(store, emergency);
        await appendEvent(store, emergency);
        return emergency;
      }
      if (daily.dailyLossFraction >= MAX_DAILY_LOSS && isDominionPosition) {
        await session.closePosition(positionId, volume);
        await store.delete("account/active-position");
        const dailyClose = {
          status: "DAILY_STOP_POSITION_CLOSE_SENT",
          reason: "DAILY_LOSS_LIMIT_REACHED",
          positionId,
          dailyLossPct: daily.dailyLossFraction * 100,
          mode: "DEMO_ONLY",
        };
        await saveStatus(store, dailyClose);
        await appendEvent(store, dailyClose);
        return dailyClose;
      }
      const protectedState = {
        status: "POSITION_OPEN_PROTECTED",
        reason: "BROKER_SIDE_SL_TP_ACTIVE_NO_NEW_ENTRY",
        positionId,
        symbolId: number(tradeData?.symbolId),
        stopLoss: number(position.stopLoss),
        takeProfit: number(position.takeProfit),
        equity: daily.equity,
        dailyLossPct: daily.dailyLossFraction * 100,
        mode: "DEMO_ONLY",
      };
      await saveStatus(store, protectedState);
      return protectedState;
    }
    if (accountState.orders.length > 0) {
      const pending = { status: "PENDING_ORDER_BLOCK", reason: "EXISTING_PENDING_ORDER", pendingOrders: accountState.orders.length, mode: "DEMO_ONLY" };
      await saveStatus(store, pending);
      return pending;
    }
    if (daily.dailyLossFraction >= MAX_DAILY_LOSS) {
      const stopped = {
        status: "DAILY_STOP",
        reason: "DAILY_LOSS_LIMIT_REACHED",
        dailyLossPct: daily.dailyLossFraction * 100,
        equity: daily.equity,
        dailyNetPnl: daily.dailyNetPnl,
        mode: "DEMO_ONLY",
      };
      await saveStatus(store, stopped);
      return stopped;
    }

    const symbolByName = new Map(symbols.map((item) => [normalizeSymbol(item.symbolName), item]));
    const candidates: Candidate[] = [];
    const errors: Array<{ symbol: string; reason: string }> = [];
    const periods = TIMEFRAME_PROFILES[profile];
    for (const requested of requestedSymbols) {
      try {
        const light = symbolByName.get(requested);
        if (!light || light.enabled === false) throw new Error("SYMBOL_NOT_AVAILABLE_OR_DISABLED");
        const symbolId = number(light.symbolId);
        const quoteAssetId = String(light.quoteAssetId ?? "");
        if (quoteAssetId !== depositAssetId) throw new Error("QUOTE_ASSET_MUST_MATCH_DEPOSIT_CURRENCY");
        const symbol = await session.symbolDetails(symbolId);
        if (number(symbol.distanceSetIn ?? 1) !== 1) throw new Error("UNSUPPORTED_STOP_DISTANCE_UNIT");
        if (requested !== "XAUUSD" && symbol.enableShortSelling === false) {
          // Buy signals remain eligible; sell signals are filtered after strategy evaluation.
        }
        const [spot, executionBars, contextBars] = await Promise.all([
          session.spot(symbolId),
          session.trendbars(symbolId, periods.executionPeriod, 220),
          session.trendbars(symbolId, periods.contextPeriod, 220),
        ]);
        const candidate = buildCandidate(
          requested, light, symbol, spot, executionBars, contextBars,
          profile, scoreThreshold, now,
        );
        if (candidate) candidates.push(candidate);
      } catch (error) {
        errors.push({ symbol: requested, reason: error instanceof Error ? error.message : "UNKNOWN_SYMBOL_ERROR" });
      }
    }

    candidates.sort((a, b) => b.setup.score - a.setup.score);
    const best = candidates[0];
    if (!best) {
      const noSignal = {
        status: "NO_QUALIFYING_SIGNAL",
        profile, scoreThreshold, symbolsChecked: requestedSymbols,
        symbolErrors: errors.slice(0, 10),
        equity: daily.equity, dailyLossPct: daily.dailyLossFraction * 100,
        mode: "DEMO_ONLY",
      };
      await saveStatus(store, noSignal);
      return noSignal;
    }

    if (best.setup.side === "SELL" && best.symbol.enableShortSelling === false) {
      throw new Error("SHORT_SELLING_DISABLED_FOR_SYMBOL");
    }
    const entryPrice = best.setup.side === "BUY" ? best.ask : best.bid;
    const distance = best.setup.riskDistance;
    const digits = number(best.symbol.digits);
    const point = 10 ** -digits;
    const slippagePrice = entryPrice * MAX_SLIPPAGE_BPS / 10000;
    const riskDistanceForSizing = distance + slippagePrice;
    const target2Distance = 2 * distance + 3 * slippagePrice;
    const target3Distance = 3 * distance + 4 * slippagePrice;
    const stopLoss = Number((best.setup.side === "BUY" ? entryPrice - distance : entryPrice + distance).toFixed(digits));
    const target2R = Number((best.setup.side === "BUY" ? entryPrice + target2Distance : entryPrice - target2Distance).toFixed(digits));
    const takeProfit = Number((best.setup.side === "BUY" ? entryPrice + target3Distance : entryPrice - target3Distance).toFixed(digits));
    const minStopDistance = number(best.symbol.slDistance ?? 0) * point;
    const minTakeDistance = number(best.symbol.tpDistance ?? 0) * point;
    if (Math.abs(entryPrice - stopLoss) < minStopDistance ||
        Math.abs(takeProfit - entryPrice) < minTakeDistance) {
      throw new Error("BROKER_MINIMUM_PROTECTION_DISTANCE_NOT_MET");
    }
    if (best.setup.side === "BUY" ? !(stopLoss < best.bid && takeProfit > best.ask)
        : !(stopLoss > best.ask && takeProfit < best.bid)) {
      throw new Error("PROTECTIVE_PRICE_DIRECTION_INVALID");
    }

    const commissionPrice = entryPrice * (1 + MAX_SLIPPAGE_BPS / 10000);
    const sized = sizeVolume(best.symbol, commissionPrice, riskDistanceForSizing, daily.equity);
    const marginResponse = await session.expectedMargin(best.symbolId, sized.volume);
    const marginRow = marginResponse.margins.find((item) => number(item.volume) === sized.volume) ?? marginResponse.margins[0];
    if (!marginRow) throw new Error("EXPECTED_MARGIN_NOT_RETURNED");
    const marginDigits = marginResponse.moneyDigits || moneyDigits;
    const marginValue = number(best.setup.side === "BUY" ? marginRow.buyMargin : marginRow.sellMargin) /
      moneyScale(marginDigits);
    if (!Number.isFinite(marginValue) || marginValue <= 0 || marginValue > daily.equity * MAX_MARGIN_FRACTION) {
      throw new Error("MARGIN_GUARD_REJECTED");
    }
    const riskPct = ((sized.riskAmount + sized.commission) / daily.equity) * 100;
    if (riskPct > MAX_RISK_PER_TRADE * 100 + 1e-8) throw new Error("RISK_LIMIT_REJECTED");

    const slippageInPoints = Math.max(1, Math.floor((entryPrice * MAX_SLIPPAGE_BPS / 10000) / point));
    const clientOrderId = `dominion-${randomUUID()}`;
    const preview = {
      status: "ORDER_PRECHECK_PASSED",
      symbol: best.symbolName,
      side: best.setup.side,
      score: best.setup.score,
      scoreThreshold,
      profile,
      volume: sized.volume,
      entryPrice,
      stopLoss,
      takeProfit,
      target2R,
      target3R: takeProfit,
      riskAmount: sized.riskAmount,
      estimatedRoundTripCommission: sized.commission,
      riskPct,
      margin: marginValue,
      spreadBps: best.spreadBps,
      slippageCapBps: MAX_SLIPPAGE_BPS,
      mode: "DEMO_ONLY",
    };

    let execution: RecordData;
    try {
      execution = await session.newMarketRangeOrder({
        symbolId: best.symbolId,
        side: best.setup.side,
        volume: sized.volume,
        entryPrice: best.setup.side === "BUY" ? best.ask : best.bid,
        stopLoss,
        takeProfit,
        slippageInPoints,
        clientOrderId,
      });
    } catch (orderError) {
      const afterOrderError = await session.reconcile();
      const partialPosition = afterOrderError.positions.find((item) => {
        const tradeData = item.tradeData as RecordData | undefined;
        return number(tradeData?.symbolId) === best.symbolId &&
          String(tradeData?.label ?? "") === "DOMINION_AI_DEMO";
      });
      if (partialPosition) {
        const partialId = number(partialPosition.positionId);
        const partialVolume = number((partialPosition.tradeData as RecordData).volume);
        const protectedPartial = number(partialPosition.stopLoss) > 0 &&
          number(partialPosition.takeProfit) > 0;
        if (!protectedPartial && partialId > 0 && partialVolume > 0) {
          await session.closePosition(partialId, partialVolume);
          throw new Error("PARTIAL_FILL_UNPROTECTED_EMERGENCY_CLOSE_SENT");
        }
        if (protectedPartial) {
          const partialStatus = {
            status: "PARTIAL_FILL_PROTECTED",
            reason: "PARTIAL_FILL_RECEIVED_WITH_BROKER_SIDE_SL_TP",
            positionId: partialId,
            symbol: best.symbolName,
            side: best.setup.side,
            confirmedStopLoss: number(partialPosition.stopLoss),
            confirmedTakeProfit: number(partialPosition.takeProfit),
            clientOrderId,
            mode: "DEMO_ONLY",
          };
          await store.setJSON("account/active-position", {
            positionId: partialId, symbol: best.symbolName, symbolId: best.symbolId,
            side: best.setup.side, entryPrice: number(partialPosition.price ?? entryPrice),
            initialRiskDistance: riskDistanceForSizing, initialStopLoss: stopLoss,
            target2R, target3R: takeProfit, partialTaken: false, breakEvenSet: false,
            minVolume: number(best.symbol.minVolume), stepVolume: number(best.symbol.stepVolume),
            openedAt: new Date().toISOString(), clientOrderId,
          });
          await saveStatus(store, partialStatus);
          await appendEvent(store, partialStatus);
          return partialStatus;
        }
      }
      throw orderError;
    }
    let reconciled = await session.reconcile();
    let position = reconciled.positions.find((item) => {
      const tradeData = item.tradeData as RecordData | undefined;
      return number(tradeData?.symbolId) === best.symbolId &&
        String(tradeData?.label ?? "") === "DOMINION_AI_DEMO";
    });
    if (!position && execution.position && typeof execution.position === "object") {
      position = execution.position as RecordData;
    }
    if (!position) {
      const failed = { status: "ORDER_SENT_POSITION_NOT_CONFIRMED", ...preview };
      await saveStatus(store, failed);
      await appendEvent(store, failed);
      return failed;
    }

    let positionId = number(position.positionId);
    if (!(number(position.stopLoss) > 0) || !(number(position.takeProfit) > 0)) {
      if (!(positionId > 0)) throw new Error("FILLED_POSITION_ID_MISSING");
      await session.amendProtection(positionId, stopLoss, takeProfit);
      reconciled = await session.reconcile();
      position = reconciled.positions.find((item) => number(item.positionId) === positionId);
    }
    if (!position || !(number(position.stopLoss) > 0) || !(number(position.takeProfit) > 0)) {
      if (positionId > 0) {
        const remaining = reconciled.positions.find((item) => number(item.positionId) === positionId);
        if (remaining) await session.closePosition(positionId, number((remaining.tradeData as RecordData).volume));
      }
      throw new Error("PROTECTIVE_SL_TP_NOT_CONFIRMED_EMERGENCY_CLOSE_REQUESTED");
    }

    const completed = {
      status: "DEMO_ORDER_FILLED_PROTECTED",
      ...preview,
      positionId,
      confirmedStopLoss: number(position.stopLoss),
      confirmedTakeProfit: number(position.takeProfit),
      orderId: number((execution.order as RecordData | undefined)?.orderId ?? 0),
      clientOrderId,
      brokerConfirmed: true,
      mode: "DEMO_ONLY",
    };
    await store.setJSON("account/active-position", {
      positionId,
      symbol: best.symbolName,
      symbolId: best.symbolId,
      side: best.setup.side,
      entryPrice: number(position.price ?? entryPrice),
      initialRiskDistance: riskDistanceForSizing,
      initialStopLoss: stopLoss,
      target2R: preview.target2R,
      target3R: preview.target3R,
      partialTaken: false,
      breakEvenSet: false,
      minVolume: number(best.symbol.minVolume),
      stepVolume: number(best.symbol.stepVolume),
      openedAt: new Date().toISOString(),
      clientOrderId,
    });
    await saveStatus(store, completed);
    await appendEvent(store, completed);
    return completed;
  } finally {
    await session.close();
  }
}

export default async (request: Request) => {
  const store = getStore({ name: "dominion-ctrader-oauth-prod", consistency: "strong" });
  const now = Date.now();
  const lockId = randomUUID();
  const lockKey = "account/engine-lock";
  let acquired = false;
  try {
    const existing = await store.get(lockKey, { type: "json" }) as RecordData | null;
    if (existing && number(existing.expiresAt) > now) {
      return Response.json({ status: "SKIPPED_LOCKED", mode: "DEMO_ONLY" });
    }
    if (existing) await store.delete(lockKey);
    try {
      await store.setJSON(lockKey, { id: lockId, expiresAt: now + 45000 }, { onlyIfNew: true });
      acquired = true;
    } catch {
      return Response.json({ status: "SKIPPED_LOCKED", mode: "DEMO_ONLY" });
    }
    const result = await executeCycle();
    return Response.json(result);
  } catch (error) {
    const reason = error instanceof Error ? error.message : "UNKNOWN_ENGINE_ERROR";
    const failed = { status: "BLOCKED", reason, mode: "DEMO_ONLY", liveTradingEnabled: false };
    await saveStatus(store, failed);
    await appendEvent(store, failed);
    return Response.json(failed);
  } finally {
    if (acquired) {
      const current = await store.get(lockKey, { type: "json" }) as RecordData | null;
      if (current?.id === lockId) await store.delete(lockKey);
    }
  }
};

export const config = { schedule: "* * * * *" };
