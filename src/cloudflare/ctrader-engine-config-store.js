/**
 * D1 persistence for the validated cTrader demo engine configuration.
 * This module does not authenticate requests or enable execution.
 */
function requireDatabase(db) {
  if (!db || typeof db.prepare !== "function") {
    throw new Error("Cloudflare D1 binding is required.");
  }
}

function validateStoredConfig(config) {
  if (!config || typeof config !== "object" || Array.isArray(config) ||
      config.environment !== "demo" || typeof config.enabled !== "boolean" ||
      !["scalp", "intraday", "swing"].includes(config.profile) ||
      !Number.isInteger(config.scoreThreshold) || config.scoreThreshold < 1 || config.scoreThreshold > 15 ||
      typeof config.useSessionFilter !== "boolean" ||
      !Number.isFinite(config.riskPerTradePct) || config.riskPerTradePct < 0.05 || config.riskPerTradePct > 0.5 ||
      !Number.isFinite(config.dailyLossLimitPct) || config.dailyLossLimitPct < 0.5 || config.dailyLossLimitPct > 2 ||
      !Array.isArray(config.symbols) || config.symbols.length < 1 || config.symbols.length > 20 ||
      config.symbols.some((symbol) => typeof symbol !== "string" || !/^[A-Z0-9]{3,20}$/.test(symbol)) ||
      new Set(config.symbols).size !== config.symbols.length ||
      config.maxRiskPerTradePct !== 0.5 || config.maxDailyLossPct !== 2 ||
      config.maxOpenPositions !== 1) {
    throw new Error("A validated demo-only cTrader engine config is required.");
  }
}

/** Read the singleton engine configuration; absent rows return null. */
export async function readCTraderEngineConfig(db) {
  requireDatabase(db);
  const row = await db.prepare(
    "SELECT config_json, updated_at FROM engine_config WHERE id = 1",
  ).first();
  if (!row) return null;
  let config;
  try {
    config = JSON.parse(row.config_json);
  } catch {
    throw new Error("Stored cTrader engine config is invalid.");
  }
  validateStoredConfig(config);
  return { config, updatedAt: row.updated_at };
}

/**
 * Persist a fully validated config using a singleton upsert.
 * Enabling remains guarded by the separate authenticated control route,
 * explicit confirmation, verified demo account and replay protection.
 */
export async function saveCTraderEngineConfig(db, config, nowMs = Date.now()) {
  requireDatabase(db);
  if (!Number.isSafeInteger(nowMs)) throw new Error("Invalid update time.");
  validateStoredConfig(config);
  const updatedAt = Math.floor(nowMs / 1000);
  await db.prepare(
    "INSERT INTO engine_config (id, config_json, updated_at) VALUES (1, ?, ?) ON CONFLICT(id) DO UPDATE SET config_json = excluded.config_json, updated_at = excluded.updated_at",
  ).bind(JSON.stringify(config), updatedAt).run();
  return { updatedAt };
}
