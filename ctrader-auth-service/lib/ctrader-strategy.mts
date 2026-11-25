export type Market = "FOREX" | "GOLD";
export type Side = "BUY" | "SELL";
export type Candle = {
  symbol: string;
  market: Market;
  timeframe: string;
  timestamp: Date;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
};

export const TIMEFRAME_PROFILES = {
  scalp: { execution: "5m", context: "1h", executionPeriod: 5, contextPeriod: 9, executionSeconds: 300, contextSeconds: 3600 },
  intraday: { execution: "15m", context: "4h", executionPeriod: 7, contextPeriod: 10, executionSeconds: 900, contextSeconds: 14400 },
  swing: { execution: "4h", context: "1d", executionPeriod: 10, contextPeriod: 12, executionSeconds: 14400, contextSeconds: 86400 },
} as const;

export type StrategyProfile = keyof typeof TIMEFRAME_PROFILES;

export type TradeSetup = {
  symbol: string;
  market: Market;
  side: Side;
  strategy: "MTF_CONFLUENCE_SMC";
  entryPrice: number;
  stopLoss: number;
  target2R: number;
  target3R: number;
  liquidityTarget: number;
  riskDistance: number;
  score: number;
  scoreThreshold: number;
  executionTimeframe: string;
  contextTimeframe: string;
  reasons: string[];
};

function ema(values: number[], period: number): number[] {
  if (values.length < period) throw new Error("INSUFFICIENT_EMA_DATA");
  const alpha = 2 / (period + 1);
  let current = values.slice(0, period).reduce((a, b) => a + b, 0) / period;
  const output = [current];
  for (const value of values.slice(period)) {
    current = value * alpha + current * (1 - alpha);
    output.push(current);
  }
  return output;
}

function rsi(values: number[], period = 14): number {
  if (values.length <= period) throw new Error("INSUFFICIENT_RSI_DATA");
  const changes = values.slice(1).map((value, index) => value - values[index]);
  let gain = changes.slice(0, period).reduce((sum, value) => sum + Math.max(value, 0), 0) / period;
  let loss = changes.slice(0, period).reduce((sum, value) => sum + Math.max(-value, 0), 0) / period;
  for (const change of changes.slice(period)) {
    gain = (gain * (period - 1) + Math.max(change, 0)) / period;
    loss = (loss * (period - 1) + Math.max(-change, 0)) / period;
  }
  if (loss === 0) return gain > 0 ? 100 : 50;
  const rs = gain / loss;
  return 100 - 100 / (1 + rs);
}

function atr(candles: Candle[], period = 14): number {
  if (candles.length <= period) throw new Error("INSUFFICIENT_ATR_DATA");
  const ranges = candles.slice(1).map((current, index) => {
    const previous = candles[index];
    return Math.max(
      current.high - current.low,
      Math.abs(current.high - previous.close),
      Math.abs(current.low - previous.close),
    );
  });
  return ranges.slice(-period).reduce((sum, value) => sum + value, 0) / period;
}

function macdDirection(closes: number[]): Side | null {
  if (closes.length < 35) return null;
  const fast = ema(closes, 12);
  const slow = ema(closes, 26);
  const macd = fast.slice(-slow.length).map((value, index) => value - slow[index]);
  const signal = ema(macd, 9);
  const aligned = macd.slice(-signal.length);
  const previousMacd = aligned[aligned.length - 2];
  const currentMacd = aligned[aligned.length - 1];
  const previousSignal = signal[signal.length - 2];
  const currentSignal = signal[signal.length - 1];
  if (previousMacd <= previousSignal && currentMacd > currentSignal) return "BUY";
  if (previousMacd >= previousSignal && currentMacd < currentSignal) return "SELL";
  if (currentMacd > currentSignal) return "BUY";
  if (currentMacd < currentSignal) return "SELL";
  return null;
}

function inMajorSession(now: Date): boolean {
  const minutes = now.getUTCHours() * 60 + now.getUTCMinutes();
  return (minutes >= 7 * 60 && minutes < 11 * 60) ||
    (minutes >= 12 * 60 && minutes < 16 * 60);
}

function validateCandles(candles: Candle[], symbol: string, timeframe: string): void {
  if (candles.length < 200) throw new Error("INSUFFICIENT_CANDLE_HISTORY");
  for (let index = 0; index < candles.length; index++) {
    const candle = candles[index];
    if (candle.symbol !== symbol || candle.timeframe !== timeframe ||
        !(candle.timestamp instanceof Date) || !Number.isFinite(candle.timestamp.getTime()) ||
        ![candle.open, candle.high, candle.low, candle.close, candle.volume].every(Number.isFinite) ||
        candle.open <= 0 || candle.high <= 0 || candle.low <= 0 || candle.close <= 0 ||
        candle.volume < 0 || candle.high < Math.max(candle.open, candle.close, candle.low) ||
        candle.low > Math.min(candle.open, candle.close, candle.high) ||
        (index > 0 && candles[index - 1].timestamp.getTime() >= candle.timestamp.getTime())) {
      throw new Error("INVALID_CANDLE_SERIES");
    }
  }
}

export function evaluateConfluence(
  execution: Candle[],
  context: Candle[],
  profile: StrategyProfile,
  now = new Date(),
  scoreThreshold = 6,
  useSessionFilter = false,
): TradeSetup | null {
  const timeframes = TIMEFRAME_PROFILES[profile];
  if (!timeframes) throw new Error("INVALID_STRATEGY_PROFILE");
  if (!Number.isInteger(scoreThreshold) || scoreThreshold < 1 || scoreThreshold > 15) {
    throw new Error("INVALID_SCORE_THRESHOLD");
  }
  if (!execution.length || !context.length || !Number.isFinite(now.getTime())) return null;
  const symbol = execution[execution.length - 1].symbol;
  const market = execution[execution.length - 1].market;
  validateCandles(execution, symbol, timeframes.execution);
  validateCandles(context, symbol, timeframes.context);
  if (context.some((candle) => candle.market !== market)) throw new Error("MARKET_MISMATCH");

  if (useSessionFilter && !inMajorSession(now)) return null;
  const last = execution[execution.length - 1];
  const closes = execution.map((candle) => candle.close);
  const contextCloses = context.map((candle) => candle.close);
  const htfFast = ema(contextCloses, 50).at(-1)!;
  const htfSlow = ema(contextCloses, 200).at(-1)!;
  const execFast = ema(closes, 20).at(-1)!;
  const execSlow = ema(closes, 50).at(-1)!;
  const momentum = macdDirection(closes);
  const strength = rsi(closes, 14);
  const volatility = atr(execution, 14);
  if (!(volatility > 0) || !Number.isFinite(volatility)) return null;

  const prior = execution.slice(-(20 + 1), -1);
  const swingHigh = Math.max(...prior.map((candle) => candle.high));
  const swingLow = Math.min(...prior.map((candle) => candle.low));
  const impulseRange = swingHigh - swingLow;
  if (!(impulseRange > 0)) return null;

  const bullishSweep = last.low < swingLow && last.close > swingLow;
  const bearishSweep = last.high > swingHigh && last.close < swingHigh;
  const bullishBos = last.close > swingHigh;
  const bearishBos = last.close < swingLow;
  const internal = execution.slice(-6, -1);
  const internalHigh = Math.max(...internal.map((candle) => candle.high));
  const internalLow = Math.min(...internal.map((candle) => candle.low));
  const bullishChoch = htfFast <= htfSlow && last.close > internalHigh;
  const bearishChoch = htfFast >= htfSlow && last.close < internalLow;
  const oppositeBull = execution.slice(-7, -1).reverse().find((candle) => candle.close < candle.open);
  const oppositeBear = execution.slice(-7, -1).reverse().find((candle) => candle.close > candle.open);
  const bullishObRetest = Boolean(oppositeBull && last.low <= oppositeBull.high &&
    last.close >= oppositeBull.low && last.close > last.open);
  const bearishObRetest = Boolean(oppositeBear && last.high >= oppositeBear.low &&
    last.close <= oppositeBear.high && last.close < last.open);
  const bullishFvg = last.low > execution[execution.length - 3].high;
  const bearishFvg = last.high < execution[execution.length - 3].low;
  const fibBullDiscount = last.close >= swingHigh - 0.786 * impulseRange &&
    last.close <= swingHigh - 0.5 * impulseRange;
  const fibBearPremium = last.close >= swingLow + 0.5 * impulseRange &&
    last.close <= swingLow + 0.786 * impulseRange;

  let buyScore = 0;
  let sellScore = 0;
  const buyReasons: string[] = [];
  const sellReasons: string[] = [];
  if (htfFast > htfSlow) { buyScore += 2; buyReasons.push("Higher-timeframe EMA50 above EMA200."); }
  else if (htfFast < htfSlow) { sellScore += 2; sellReasons.push("Higher-timeframe EMA50 below EMA200."); }
  if (execFast > execSlow) { buyScore += 1; buyReasons.push("Execution EMA20 above EMA50."); }
  else if (execFast < execSlow) { sellScore += 1; sellReasons.push("Execution EMA20 below EMA50."); }
  if (momentum === "BUY") { buyScore += 1; buyReasons.push("MACD momentum bullish."); }
  else if (momentum === "SELL") { sellScore += 1; sellReasons.push("MACD momentum bearish."); }
  if (strength >= 50 && strength < 70) { buyScore += 1; buyReasons.push("RSI confirms bullish strength."); }
  else if (strength > 30 && strength <= 50) { sellScore += 1; sellReasons.push("RSI confirms bearish strength."); }
  if (bullishBos) { buyScore += 2; buyReasons.push("Recent swing high broken (BOS)."); }
  if (bearishBos) { sellScore += 2; sellReasons.push("Recent swing low broken (BOS)."); }
  if (bullishChoch) { buyScore += 2; buyReasons.push("Internal structure shifted bullish (CHoCH)."); }
  if (bearishChoch) { sellScore += 2; sellReasons.push("Internal structure shifted bearish (CHoCH)."); }
  if (bullishObRetest) { buyScore += 1; buyReasons.push("Recent bearish-candle order-block retest."); }
  if (bearishObRetest) { sellScore += 1; sellReasons.push("Recent bullish-candle order-block retest."); }
  if (bullishSweep) { buyScore += 2; buyReasons.push("Liquidity sweep below swing low and reclaim."); }
  if (bearishSweep) { sellScore += 2; sellReasons.push("Liquidity sweep above swing high and rejection."); }
  if (bullishFvg) { buyScore += 1; buyReasons.push("Bullish fair-value gap."); }
  if (bearishFvg) { sellScore += 1; sellReasons.push("Bearish fair-value gap."); }
  if (fibBullDiscount) { buyScore += 1; buyReasons.push("Price in 50–78.6% discount retracement."); }
  if (fibBearPremium) { sellScore += 1; sellReasons.push("Price in 50–78.6% premium retracement."); }
  if (inMajorSession(now)) {
    if (buyScore) { buyScore += 1; buyReasons.push("London/New York session filter passed."); }
    if (sellScore) { sellScore += 1; sellReasons.push("London/New York session filter passed."); }
  }

  let side: Side;
  let score: number;
  let reasons: string[];
  let stopLoss: number;
  let riskDistance: number;
  let liquidityTarget: number;
  if (buyScore >= scoreThreshold && buyScore >= sellScore + 2) {
    side = "BUY"; score = buyScore; reasons = buyReasons;
    stopLoss = Math.min(...execution.slice(-5).map((candle) => candle.low)) - 0.8 * volatility;
    riskDistance = last.close - stopLoss;
    liquidityTarget = swingHigh;
    if (!(riskDistance > 0) || riskDistance / volatility > 2.5) return null;
    if (liquidityTarget < last.close + 2 * riskDistance) liquidityTarget = last.close + 2 * riskDistance;
  } else if (sellScore >= scoreThreshold && sellScore >= buyScore + 2) {
    side = "SELL"; score = sellScore; reasons = sellReasons;
    stopLoss = Math.max(...execution.slice(-5).map((candle) => candle.high)) + 0.8 * volatility;
    riskDistance = stopLoss - last.close;
    liquidityTarget = swingLow;
    if (!(riskDistance > 0) || riskDistance / volatility > 2.5) return null;
    if (liquidityTarget > last.close - 2 * riskDistance) liquidityTarget = last.close - 2 * riskDistance;
  } else {
    return null;
  }

  return {
    symbol, market, side, strategy: "MTF_CONFLUENCE_SMC",
    entryPrice: last.close, stopLoss,
    target2R: side === "BUY" ? last.close + 2 * riskDistance : last.close - 2 * riskDistance,
    target3R: side === "BUY" ? last.close + 3 * riskDistance : last.close - 3 * riskDistance,
    liquidityTarget, riskDistance, score, scoreThreshold,
    executionTimeframe: timeframes.execution, contextTimeframe: timeframes.context,
    reasons,
  };
}
