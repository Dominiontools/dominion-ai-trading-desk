export const DEFAULT_CTRADER_ENGINE_CONFIG = Object.freeze({
  enabled: false,
  profile: "intraday",
  scoreThreshold: 6,
  useSessionFilter: true,
  riskPerTradePct: 0.5,
  dailyLossLimitPct: 2,
  symbols: Object.freeze(["XAUUSD", "EURUSD", "GBPUSD"]),
  maxRiskPerTradePct: 0.5,
  maxDailyLossPct: 2,
  maxOpenPositions: 1,
});

const PROFILES = new Set(["scalp", "intraday", "swing"]);

function invalid(error) {
  return { ok: false, error };
}

/**
 * Pure configuration validation. The caller must separately authenticate,
 * consume the replay nonce, verify the connected demo trading account, and persist.
 */
export function validateCTraderEngineConfig(body, previous = null) {
  if (!body || typeof body !== "object" || Array.isArray(body)) return invalid("INVALID_CONTROL_BODY");
  if (!previous || typeof previous !== "object" || Array.isArray(previous)) previous = {};
  if (typeof body.enabled !== "boolean") return invalid("ENABLED_FLAG_REQUIRED");
  if (body.enabled && body.confirmDemoAutomation !== true) {
    return invalid("EXPLICIT_DEMO_AUTOMATION_CONFIRMATION_REQUIRED");
  }

  const prior = { ...DEFAULT_CTRADER_ENGINE_CONFIG, ...previous };
  const profile = String(body.profile ?? prior.profile);
  if (!PROFILES.has(profile)) return invalid("INVALID_STRATEGY_PROFILE");

  const scoreThreshold = Number(body.scoreThreshold ?? prior.scoreThreshold);
  if (!Number.isInteger(scoreThreshold) || scoreThreshold < 1 || scoreThreshold > 15) {
    return invalid("INVALID_SCORE_THRESHOLD");
  }

  const useSessionFilter = body.useSessionFilter ?? prior.useSessionFilter;
  if (typeof useSessionFilter !== "boolean") return invalid("INVALID_SESSION_FILTER_SETTING");

  const riskPerTradePct = Number(body.riskPerTradePct ?? prior.riskPerTradePct);
  if (!Number.isFinite(riskPerTradePct) || riskPerTradePct < 0.05 || riskPerTradePct > 0.5) {
    return invalid("RISK_PER_TRADE_MUST_BE_BETWEEN_0_05_AND_0_5_PERCENT");
  }

  const dailyLossLimitPct = Number(body.dailyLossLimitPct ?? prior.dailyLossLimitPct);
  if (!Number.isFinite(dailyLossLimitPct) || dailyLossLimitPct < 0.5 || dailyLossLimitPct > 2) {
    return invalid("DAILY_LOSS_LIMIT_MUST_BE_BETWEEN_0_5_AND_2_PERCENT");
  }

  const rawSymbols = body.symbols ?? prior.symbols;
  if (!Array.isArray(rawSymbols) || rawSymbols.length < 1 || rawSymbols.length > 20) {
    return invalid("INVALID_SYMBOL_WATCHLIST");
  }
  // Strip separators only; preserve every letter, including the D in USD.
  const symbols = rawSymbols.map((item) => {
    const raw = String(item);
    if (!/^[A-Za-z0-9]+(?:[\/_-][A-Za-z0-9]+)*$/.test(raw)) return "";
    return raw.replace(/[\/_-]/g, "").toUpperCase();
  });
  if (symbols.some((item) => !/^[A-Z0-9]{3,20}$/.test(item)) ||
      new Set(symbols).size !== symbols.length) {
    return invalid("INVALID_OR_DUPLICATE_SYMBOL");
  }

  return {
    ok: true,
    config: {
      ...prior,
      enabled: body.enabled,
      profile,
      scoreThreshold,
      useSessionFilter,
      riskPerTradePct,
      dailyLossLimitPct,
      symbols,
      environment: "demo",
    },
  };
}
