import test from "node:test";
import assert from "node:assert/strict";
import {
  DEFAULT_CTRADER_ENGINE_CONFIG,
  validateCTraderEngineConfig,
} from "../src/cloudflare/ctrader-control-config.js";

test("uses safe defaults while remaining disabled", () => {
  const result = validateCTraderEngineConfig({ enabled: false });
  assert.equal(result.ok, true);
  assert.equal(result.config.enabled, false);
  assert.equal(result.config.profile, "intraday");
  assert.deepEqual(result.config.symbols, ["XAUUSD", "EURUSD", "GBPUSD"]);
  assert.equal(result.config.riskPerTradePct, 0.5);
  assert.equal(result.config.dailyLossLimitPct, 2);
  assert.equal(result.config.environment, "demo");
});

test("requires explicit confirmation before enabling", () => {
  assert.equal(
    validateCTraderEngineConfig({ enabled: true }).error,
    "EXPLICIT_DEMO_AUTOMATION_CONFIRMATION_REQUIRED",
  );
  const result = validateCTraderEngineConfig({ enabled: true, confirmDemoAutomation: true });
  assert.equal(result.ok, true);
  assert.equal(result.config.enabled, true);
});

test("requires an explicit enabled boolean", () => {
  assert.equal(validateCTraderEngineConfig({}).error, "ENABLED_FLAG_REQUIRED");
  assert.equal(validateCTraderEngineConfig(null).error, "INVALID_CONTROL_BODY");
});

test("accepts only supported profiles and score thresholds", () => {
  for (const profile of ["scalp", "intraday", "swing"]) {
    assert.equal(validateCTraderEngineConfig({ enabled: false, profile }).ok, true);
  }
  assert.equal(validateCTraderEngineConfig({ enabled: false, profile: "unknown" }).error, "INVALID_STRATEGY_PROFILE");
  for (const scoreThreshold of [0, 16, 2.5, "bad"]) {
    assert.equal(validateCTraderEngineConfig({ enabled: false, scoreThreshold }).error, "INVALID_SCORE_THRESHOLD");
  }
});

test("validates session filter and risk limits", () => {
  assert.equal(validateCTraderEngineConfig({ enabled: false, useSessionFilter: "yes" }).error, "INVALID_SESSION_FILTER_SETTING");
  assert.equal(validateCTraderEngineConfig({ enabled: false, riskPerTradePct: 0.051 }).ok, true);
  assert.equal(validateCTraderEngineConfig({ enabled: false, riskPerTradePct: 0.501 }).error, "RISK_PER_TRADE_MUST_BE_BETWEEN_0_05_AND_0_5_PERCENT");
  assert.equal(validateCTraderEngineConfig({ enabled: false, dailyLossLimitPct: 2.01 }).error, "DAILY_LOSS_LIMIT_MUST_BE_BETWEEN_0_5_AND_2_PERCENT");
});

test("normalizes symbols and rejects invalid, duplicate, or oversized lists", () => {
  const result = validateCTraderEngineConfig({ enabled: false, symbols: ["xau/usd", "EUR_USD", "gbp-usd"] });
  assert.equal(result.ok, true);
  assert.deepEqual(result.config.symbols, ["XAUUSD", "EURUSD", "GBPUSD"]);
  assert.equal(validateCTraderEngineConfig({ enabled: false, symbols: ["EUR/USD", "eurusd"] }).error, "INVALID_OR_DUPLICATE_SYMBOL");
  assert.equal(validateCTraderEngineConfig({ enabled: false, symbols: ["bad!"] }).error, "INVALID_OR_DUPLICATE_SYMBOL");
  assert.equal(validateCTraderEngineConfig({ enabled: false, symbols: Array(21).fill("EURUSD") }).error, "INVALID_SYMBOL_WATCHLIST");
});

test("preserves omitted settings from previous config", () => {
  const previous = {
    ...DEFAULT_CTRADER_ENGINE_CONFIG,
    profile: "swing",
    scoreThreshold: 9,
    symbols: ["XAUUSD"],
    riskPerTradePct: 0.25,
  };
  const result = validateCTraderEngineConfig({ enabled: false }, previous);
  assert.equal(result.ok, true);
  assert.equal(result.config.profile, "swing");
  assert.equal(result.config.scoreThreshold, 9);
  assert.deepEqual(result.config.symbols, ["XAUUSD"]);
  assert.equal(result.config.riskPerTradePct, 0.25);
});
