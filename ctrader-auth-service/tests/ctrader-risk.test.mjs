import test from "node:test";
import assert from "node:assert/strict";
import {
  calculateDailyRisk,
  estimateRoundTripCommission,
  moneyScale,
  sizeVolume,
} from "../lib/ctrader-risk.mjs";

test("moneyScale validates and scales broker money precision", () => {
  assert.equal(moneyScale(2), 100);
  assert.equal(moneyScale(8), 100000000);
  assert.throws(() => moneyScale(-1), /INVALID_MONEY_DIGITS/);
});

test("daily loss includes closed deals and non-capital cash flows, excluding deposits and withdrawals", () => {
  const result = calculateDailyRisk(
    10000,
    2,
    [{
      moneyDigits: 2,
      closePositionDetail: {
        moneyDigits: 2,
        grossProfit: -150,
        swap: -20,
        commission: -30,
        pnlConversionFee: 0,
      },
    }],
    [
      { operationType: 0, delta: 5000, moneyDigits: 2 },
      { operationType: 1, delta: -1000, moneyDigits: 2 },
      { operationType: 2, delta: -25, moneyDigits: 2 },
    ],
  );
  assert.equal(result.equity, 100);
  assert.equal(result.dailyNetPnl, -2.25);
  assert.equal(result.startingEquity, 62.25);
  assert.ok(Math.abs(result.dailyLossFraction - (2.25 / 62.25)) < 1e-12);
});

test("commission estimator supports all documented broker commission types", () => {
  const base = {
    lotSize: 10000000,
    minCommissionAsset: "USD",
    preciseMinCommission: 0,
  };
  assert.ok(Math.abs(estimateRoundTripCommission({
    ...base, commissionType: 1, preciseTradingCommissionRate: 5000000000,
  }, 1000000, 1.1) - 1.1) < 1e-9);
  assert.ok(Math.abs(estimateRoundTripCommission({
    ...base, commissionType: 2, preciseTradingCommissionRate: 700000000,
  }, 1000000, 1.1) - 1.4) < 1e-9);
  assert.ok(Math.abs(estimateRoundTripCommission({
    ...base, commissionType: 3, preciseTradingCommissionRate: 500,
  }, 1000000, 1.1) - 1.1) < 1e-9);
  assert.ok(Math.abs(estimateRoundTripCommission({
    ...base, commissionType: 4, preciseTradingCommissionRate: 500000000,
  }, 1000000, 1.1) - 1.0) < 1e-9);
});

test("minimum round-trip commission is applied twice", () => {
  assert.equal(estimateRoundTripCommission({
    lotSize: 10000000,
    commissionType: 1,
    preciseTradingCommissionRate: 0,
    preciseMinCommission: 200000000,
    minCommissionAsset: "USD",
  }, 1000000, 1.1), 4);
});

test("volume sizing never exceeds 0.5 percent risk including round-trip commission", () => {
  const symbol = {
    minVolume: 1000,
    maxVolume: 10000000,
    stepVolume: 1000,
    lotSize: 10000000,
    commissionType: 1,
    preciseTradingCommissionRate: 0,
    preciseMinCommission: 0,
    minCommissionAsset: "USD",
  };
  const result = sizeVolume(symbol, 1.1, 0.001, 1000);
  assert.equal(result.volume % symbol.stepVolume, 0);
  assert.ok(result.volume >= symbol.minVolume);
  assert.ok(result.volume <= symbol.maxVolume);
  assert.ok(result.riskAmount + result.commission <= 5 + 1e-9);
});

test("volume sizing blocks when broker minimum volume exceeds the risk budget", () => {
  const symbol = {
    minVolume: 1000000,
    maxVolume: 10000000,
    stepVolume: 1000,
    lotSize: 10000000,
    commissionType: 1,
    preciseTradingCommissionRate: 0,
    preciseMinCommission: 0,
    minCommissionAsset: "USD",
  };
  assert.throws(() => sizeVolume(symbol, 1.1, 0.001, 1000), /BROKER_MINIMUM_VOLUME_EXCEEDS_RISK_BUDGET/);
});

test("unknown commission metadata fails closed", () => {
  assert.throws(() => estimateRoundTripCommission({
    lotSize: 10000000,
    commissionType: 1,
    minCommissionAsset: "USD",
  }, 1000000, 1.1), /UNVERIFIED_BROKER_COMMISSION/);
});

test("user may lower risk below 0.5 percent but cannot raise the hard ceiling", () => {
  const symbol = {
    minVolume: 1000,
    maxVolume: 10000000,
    stepVolume: 1000,
    lotSize: 10000000,
    commissionType: 1,
    preciseTradingCommissionRate: 0,
    preciseMinCommission: 0,
    minCommissionAsset: "USD",
  };
  const reduced = sizeVolume(symbol, 1.1, 0.001, 1000, 0.0025);
  assert.ok(reduced.riskAmount + reduced.commission <= 2.5 + 1e-9);
  assert.throws(() => sizeVolume(symbol, 1.1, 0.001, 1000, 0.006), /RISK_FRACTION_EXCEEDS_HARD_LIMIT/);
});
