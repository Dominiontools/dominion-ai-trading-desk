import { getStore } from "@netlify/blobs";
import { randomUUID } from "node:crypto";
import {
  CTraderDemoSession,
  loadTradingCredentials,
  trendbarsToCandles,
} from "../../lib/ctrader-demo-session.mts";
import {
  evaluateConfluence,
  TIMEFRAME_PROFILES,
  type StrategyProfile,
} from "../../lib/ctrader-strategy.mts";
import {
  calculateDailyRisk,
  moneyScale,
  sizeVolume,
  MAX_RISK_PER_TRADE,
} from "../../lib/ctrader-risk.mjs";

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

async function mapWithConcurrency<T, R>(
  items: T[],
  concurrency: number,
  worker: (item: T, index: number) => Promise<R>,
): Promise<R[]> {
  const results = new Array<R>(items.length);
  let nextIndex = 0;
  const workers = Array.from({ length: Math.min(concurrency, items.length) }, async () => {
    while (true) {
      const index = nextIndex++;
      if (index >= items.length) return;
      results[index] = await worker(items[index], index);
    }
  });
  await Promise.all(workers);
  return results;
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
  useSessionFilter: boolean,
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
    profile, now, scoreThreshold, useSessionFilter,
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

async function manageBotPosition(
  session: CTraderDemoSession,
  store: ReturnType<typeof getStore>,
  position: RecordData,
  activePosition: RecordData,
  symbols: RecordData[],
  profile: StrategyProfile,
  scoreThreshold: number,
  useSessionFilter: boolean,
  daily: { startingEquity: number; dailyNetPnl: number; dailyLossFraction: number },
  dailyLossLimitFraction: number,
  now: Date,
): Promise<RecordData> {
  const positionId = number(position.positionId);
  const tradeData = position.tradeData as RecordData | undefined;
  const volume = number(tradeData?.volume);
  const symbolId = number(activePosition.symbolId ?? tradeData?.symbolId);
  const side = String(activePosition.side ?? (number(tradeData?.tradeSide) === 1 ? "BUY" : "SELL"));
  const entryPrice = number(activePosition.entryPrice ?? position.price);
  const initialRiskDistance = number(activePosition.initialRiskDistance);
  const target2R = number(activePosition.target2R);
  const target3R = number(activePosition.target3R);
  if (!(positionId > 0) || !(symbolId > 0) || !(volume > 0) ||
      !["BUY", "SELL"].includes(side) || !(entryPrice > 0) ||
      !(initialRiskDistance > 0) || !(target2R > 0) || !(target3R > 0)) {
    return { status: "BOT_POSITION_STATE_INCOMPLETE", reason: "BROKER_POSITION_REMAINS_PROTECTED_NO_NEW_ENTRY", positionId, mode: "DEMO_ONLY" };
  }

  const light = symbols.find((item) => number(item.symbolId) === symbolId);
  if (!light) return { status: "BOT_POSITION_SYMBOL_MISSING", positionId, mode: "DEMO_ONLY" };
  const symbolName = normalizeSymbol(light.symbolName);
  const symbol = await session.symbolDetails(symbolId);
  const spot = await session.spot(symbolId);
  const bid = number(spot.bid) / 100000;
  const ask = number(spot.ask) / 100000;
  const quoteTimestamp = number(spot.timestamp);
  const quoteAge = (now.getTime() - quoteTimestamp) / 1000;
  if (!(bid > 0) || !(ask >= bid) || quoteAge < 0 || quoteAge > MAX_QUOTE_AGE_SECONDS) {
    return { status: "POSITION_OPEN_PROTECTED_STALE_QUOTE", reason: "BROKER_SIDE_SL_TP_REMAINS_ACTIVE", positionId, quoteAgeSeconds: quoteAge, mode: "DEMO_ONLY" };
  }
  const currentPrice = side === "BUY" ? bid : ask;
  const unrealizedPnl = (side === "BUY" ? currentPrice - entryPrice : entryPrice - currentPrice) *
    (volume / 100) - number(activePosition.estimatedRoundTripCommission ?? 0);
  const markToMarketDailyPnl = daily.dailyNetPnl + unrealizedPnl;
  const markToMarketLossFraction = Math.max(0, -markToMarketDailyPnl / daily.startingEquity);
  if (markToMarketLossFraction >= dailyLossLimitFraction) {
    await session.closePosition(positionId, volume);
    await store.delete("account/active-position");
    const dailyClose = {
      status: "DAILY_STOP_UNREALIZED_CLOSE_SENT",
      reason: "REALIZED_PLUS_UNREALIZED_DAILY_LOSS_LIMIT_REACHED",
      positionId, markToMarketDailyLossPct: markToMarketLossFraction * 100,
      mode: "DEMO_ONLY",
    };
    await appendEvent(store, dailyClose);
    return dailyClose;
  }
  const periods = TIMEFRAME_PROFILES[profile];
  const [executionBars, contextBars] = await Promise.all([
    session.trendbars(symbolId, periods.executionPeriod, 220),
    session.trendbars(symbolId, periods.contextPeriod, 220),
  ]);
  let oppositeSetup: ReturnType<typeof evaluateConfluence> = null;
  try {
    const market = symbolName.startsWith("XAU") ? "GOLD" : "FOREX";
    oppositeSetup = evaluateConfluence(
      trendbarsToCandles(symbolName, market, periods.execution, executionBars, periods.executionSeconds, now.getTime()),
      trendbarsToCandles(symbolName, market, periods.context, contextBars, periods.contextSeconds, now.getTime()),
      profile, now, scoreThreshold, useSessionFilter,
    );
  } catch {
    // Keep broker-side protection active if strategy data is temporarily unavailable.
  }
  if (oppositeSetup && oppositeSetup.side !== side) {
    await session.closePosition(positionId, volume);
    await store.delete("account/active-position");
    const exit = {
      status: "STRATEGY_INVALIDATION_EXIT_SENT",
      reason: "OPPOSITE_CONFLUENCE_SIGNAL",
      positionId, symbol: symbolName, side, oppositeSignal: oppositeSetup.side,
      oppositeScore: oppositeSetup.score, mode: "DEMO_ONLY",
    };
    await appendEvent(store, exit);
    return exit;
  }

  const partialTaken = activePosition.partialTaken === true;
  const reached2R = side === "BUY" ? currentPrice >= target2R : currentPrice <= target2R;
  const reached3R = side === "BUY" ? currentPrice >= target3R : currentPrice <= target3R;
  if (reached3R) {
    await session.closePosition(positionId, volume);
    await store.delete("account/active-position");
    const exit = { status: "TAKE_PROFIT_3R_EXIT_SENT", reason: "THREE_R_TARGET_REACHED", positionId, symbol: symbolName, mode: "DEMO_ONLY" };
    await appendEvent(store, exit);
    return exit;
  }

  if (!partialTaken && reached2R) {
    const minVolume = number(activePosition.minVolume ?? symbol.minVolume);
    const stepVolume = number(activePosition.stepVolume ?? symbol.stepVolume);
    if (!(minVolume > 0) || !(stepVolume > 0)) throw new Error("PARTIAL_CLOSE_VOLUME_RULES_MISSING");
    const partialVolume = Math.floor((volume / 2) / stepVolume) * stepVolume;
    if (partialVolume >= minVolume && volume - partialVolume >= minVolume) {
      await session.closePosition(positionId, partialVolume);
      let afterPartial = await session.reconcile();
      let remaining = afterPartial.positions.find((item) => number(item.positionId) === positionId);
      if (!remaining) {
        await store.delete("account/active-position");
        const closed = { status: "POSITION_CLOSED_AT_2R", reason: "PARTIAL_VOLUME_NOT_REMAINING", positionId, mode: "DEMO_ONLY" };
        await appendEvent(store, closed);
        return closed;
      }
      if (!(number(remaining.stopLoss) > 0) || !(number(remaining.takeProfit) > 0)) {
        await session.closePosition(positionId, number((remaining.tradeData as RecordData).volume));
        await store.delete("account/active-position");
        throw new Error("PARTIAL_CLOSE_LEFT_POSITION_UNPROTECTED_EMERGENCY_CLOSE_SENT");
      }
      const breakEven = Number(entryPrice.toFixed(number(symbol.digits)));
      try {
        await session.amendProtection(positionId, breakEven, target3R);
        afterPartial = await session.reconcile();
        remaining = afterPartial.positions.find((item) => number(item.positionId) === positionId);
      } catch {
        // The previous broker-side SL/TP is still checked below; do not assume the amend succeeded.
      }
      const verified = Boolean(remaining && number(remaining.stopLoss) > 0 &&
        number(remaining.takeProfit) > 0 && Math.abs(number(remaining.stopLoss) - breakEven) <= 10 ** -number(symbol.digits));
      const updated = {
        ...activePosition,
        partialTaken: true,
        breakEvenSet: verified,
        remainingVolume: remaining ? number((remaining.tradeData as RecordData).volume) : null,
        partialClosedAt: new Date().toISOString(),
      };
      await store.setJSON("account/active-position", updated);
      const status = {
        status: verified ? "PARTIAL_TAKE_PROFIT_2R_AND_BREAKEVEN_CONFIRMED" : "PARTIAL_TAKE_PROFIT_2R_CONFIRMED",
        reason: verified ? "HALF_CLOSED_AND_REMAINDER_PROTECTED_AT_BREAKEVEN_WITH_3R_TARGET" : "HALF_CLOSED_REMAINDER_RETAINS_BROKER_PROTECTION",
        positionId, symbol: symbolName, partialVolume,
        remainingVolume: updated.remainingVolume, mode: "DEMO_ONLY",
      };
      await appendEvent(store, status);
      return status;
    }
    await session.closePosition(positionId, volume);
    await store.delete("account/active-position");
    const fullExit = { status: "FULL_TAKE_PROFIT_2R_EXIT_SENT", reason: "BROKER_MINIMUM_VOLUME_PREVENTED_SCALE_OUT", positionId, mode: "DEMO_ONLY" };
    await appendEvent(store, fullExit);
    return fullExit;
  }

  const favorableMove = side === "BUY" ? currentPrice - entryPrice : entryPrice - currentPrice;
  if (activePosition.breakEvenSet !== true && favorableMove >= initialRiskDistance) {
    const breakEven = Number(entryPrice.toFixed(number(symbol.digits)));
    await session.amendProtection(positionId, breakEven, target3R);
    const afterAmend = await session.reconcile();
    const verified = afterAmend.positions.find((item) => number(item.positionId) === positionId);
    if (verified && Math.abs(number(verified.stopLoss) - breakEven) <= 10 ** -number(symbol.digits) &&
        number(verified.takeProfit) > 0) {
      await store.setJSON("account/active-position", { ...activePosition, breakEvenSet: true });
      const status = { status: "BREAKEVEN_STOP_CONFIRMED", reason: "ONE_R_REACHED", positionId, symbol: symbolName, mode: "DEMO_ONLY" };
      await appendEvent(store, status);
      return status;
    }
    return { status: "BREAKEVEN_UPDATE_PENDING", reason: "ORIGINAL_BROKER_PROTECTION_REMAINS", positionId, mode: "DEMO_ONLY" };
  }

  return {
    status: "POSITION_OPEN_PROTECTED",
    reason: partialTaken ? "RUNNER_PROTECTED_WITH_3R_TARGET" : "BROKER_SIDE_SL_AND_3R_TP_ACTIVE",
    positionId, symbol: symbolName, side, currentPrice,
    stopLoss: number(position.stopLoss), takeProfit: number(position.takeProfit),
    partialTaken, breakEvenSet: activePosition.breakEvenSet === true,
    mode: "DEMO_ONLY",
  };
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
  const useSessionFilter = config?.useSessionFilter !== false;
  const riskPerTradePct = number(config?.riskPerTradePct ?? 0.5);
  const dailyLossLimitPct = number(config?.dailyLossLimitPct ?? 2);
  if (!Number.isFinite(riskPerTradePct) || riskPerTradePct < 0.05 || riskPerTradePct > MAX_RISK_PER_TRADE * 100 ||
      !Number.isFinite(dailyLossLimitPct) || dailyLossLimitPct < 0.5 || dailyLossLimitPct > 2) {
    const invalidRisk = { status: "BLOCKED", reason: "INVALID_USER_RISK_SETTINGS", mode: "DEMO_ONLY" };
    await saveStatus(store, invalidRisk);
    return invalidRisk;
  }
  const riskFraction = riskPerTradePct / 100;
  const dailyLossLimitFraction = dailyLossLimitPct / 100;
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
      if (daily.dailyLossFraction >= dailyLossLimitFraction && isDominionPosition) {
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
      if (isDominionPosition && number(activePosition?.positionId) === positionId) {
        const managed = await manageBotPosition(
          session, store, position, activePosition as RecordData,
          symbols, profile, scoreThreshold, useSessionFilter, daily, dailyLossLimitFraction, now,
        );
        await saveStatus(store, managed);
        return managed;
      }
      const protectedState = {
        status: isDominionPosition ? "BOT_POSITION_STATE_MISSING" : "POSITION_OPEN_PROTECTED",
        reason: isDominionPosition
          ? "BROKER_SIDE_SL_TP_ACTIVE_BUT_LOCAL_MANAGEMENT_STATE_MISSING"
          : "MANUAL_POSITION_PROTECTED_NO_NEW_ENTRY",
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
    if (accountState.positions.length === 0 && activePosition) {
      await store.delete("account/active-position");
      await appendEvent(store, {
        status: "BROKER_POSITION_CLOSED",
        reason: "POSITION_NO_LONGER_PRESENT_IN_BROKER_RECONCILIATION",
        previousPositionId: activePosition.positionId,
        symbol: activePosition.symbol,
        mode: "DEMO_ONLY",
      });
    }
    if (accountState.orders.length > 0) {
      const pending = { status: "PENDING_ORDER_BLOCK", reason: "EXISTING_PENDING_ORDER", pendingOrders: accountState.orders.length, mode: "DEMO_ONLY" };
      await saveStatus(store, pending);
      return pending;
    }
    if (daily.dailyLossFraction >= dailyLossLimitFraction) {
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
    const candidateResults = await mapWithConcurrency(requestedSymbols, 4, async (requested) => {
      try {
        const light = symbolByName.get(requested);
        if (!light || light.enabled === false) throw new Error("SYMBOL_NOT_AVAILABLE_OR_DISABLED");
        const symbolId = number(light.symbolId);
        const quoteAssetId = String(light.quoteAssetId ?? "");
        if (quoteAssetId !== depositAssetId) throw new Error("QUOTE_ASSET_MUST_MATCH_DEPOSIT_CURRENCY");
        const symbol = await session.symbolDetails(symbolId);
        if (number(symbol.distanceSetIn ?? 1) !== 1) throw new Error("UNSUPPORTED_STOP_DISTANCE_UNIT");
        const [spot, executionBars, contextBars] = await Promise.all([
          session.spot(symbolId),
          session.trendbars(symbolId, periods.executionPeriod, 220),
          session.trendbars(symbolId, periods.contextPeriod, 220),
        ]);
        return buildCandidate(
          requested, light, symbol, spot, executionBars, contextBars,
          profile, scoreThreshold, useSessionFilter, now,
        );
      } catch (error) {
        errors.push({ symbol: requested, reason: error instanceof Error ? error.message : "UNKNOWN_SYMBOL_ERROR" });
        return null;
      }
    });
    candidates.push(...candidateResults.filter((candidate): candidate is Candidate => candidate !== null));

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
    const sized = sizeVolume(best.symbol, commissionPrice, riskDistanceForSizing, daily.equity, riskFraction);
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
    if (riskPct > riskPerTradePct + 1e-8) throw new Error("RISK_LIMIT_REJECTED");

    const slippageInPoints = Math.max(1, Math.floor((entryPrice * MAX_SLIPPAGE_BPS / 10000) / point));
    const clientOrderId = `dominion-${randomUUID()}`;
    const preview = {
      status: "ORDER_PRECHECK_PASSED",
      symbol: best.symbolName,
      side: best.setup.side,
      score: best.setup.score,
      scoreThreshold,
      profile,
      riskPerTradePct,
      dailyLossLimitPct,
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
            estimatedRoundTripCommission: sized.commission,
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
      estimatedRoundTripCommission: sized.commission,
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
