import test from "node:test";
import assert from "node:assert/strict";
import { evaluateConfluence, TIMEFRAME_PROFILES } from "../src/cloudflare/ctrader-strategy.js";

function candles(symbol, timeframe, count = 200, market = "FOREX") {
  return Array.from({ length: count }, (_, index) => {
    const close = 1 + index * 0.0001;
    return {
      symbol, market, timeframe,
      timestamp: new Date(Date.UTC(2026, 0, 1) + index * 60_000),
      open: close - 0.00002,
      high: close + 0.00005,
      low: close - 0.00005,
      close,
      volume: 100
    };
  });
}

test("ported strategy retains the three existing timeframe profiles", () => {
  assert.deepEqual(
    Object.keys(TIMEFRAME_PROFILES),
    ["scalp", "intraday", "swing"]
  );
  assert.equal(TIMEFRAME_PROFILES.intraday.execution, "15m");
  assert.equal(TIMEFRAME_PROFILES.intraday.context, "4h");
});

test("strategy requires sufficient candle history and exact profile timeframes", () => {
  assert.throws(() => evaluateConfluence(
    candles("EURUSD", "15m", 199), candles("EURUSD", "4h"), "intraday"
  ), /INSUFFICIENT_CANDLE_HISTORY/);
  assert.throws(() => evaluateConfluence(
    candles("EURUSD", "1m"), candles("EURUSD", "4h"), "intraday"
  ), /INVALID_CANDLE_SERIES/);
});

test("strategy rejects invalid score thresholds and mixed markets", () => {
  assert.throws(() => evaluateConfluence(
    candles("EURUSD", "15m"), candles("EURUSD", "4h"), "intraday", new Date(), 16
  ), /INVALID_SCORE_THRESHOLD/);
  assert.throws(() => evaluateConfluence(
    candles("EURUSD", "15m"), candles("EURUSD", "4h", 200, "GOLD"), "intraday"
  ), /MARKET_MISMATCH/);
});

test("strategy fails closed on flat price history with zero volatility", () => {
  const flat = (symbol, timeframe) => Array.from({ length: 200 }, (_, index) => ({
    symbol, market: "FOREX", timeframe,
    timestamp: new Date(Date.UTC(2026, 0, 1) + index * 60_000),
    open: 1, high: 1, low: 1, close: 1, volume: 0
  }));
  assert.equal(evaluateConfluence(flat("EURUSD", "15m"), flat("EURUSD", "4h"), "intraday"), null);
});
