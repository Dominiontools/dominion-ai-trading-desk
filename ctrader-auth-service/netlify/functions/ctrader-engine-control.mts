import { getStore } from "@netlify/blobs";
import { createHmac, timingSafeEqual } from "node:crypto";

const SECRET_NAME = "DOMINION_CONTROL_API_SECRET";
const DEFAULT_CONFIG = {
  enabled: false,
  profile: "intraday",
  scoreThreshold: 6,
  useSessionFilter: true,
  riskPerTradePct: 0.5,
  dailyLossLimitPct: 2,
  symbols: ["XAUUSD", "EURUSD", "GBPUSD"],
  maxRiskPerTradePct: 0.5,
  maxDailyLossPct: 2,
  maxOpenPositions: 1,
};

function response(status: number, body: Record<string, unknown>): Response {
  return Response.json(body, {
    status,
    headers: { "cache-control": "no-store", "x-content-type-options": "nosniff" },
  });
}

export default async (request: Request) => {
  if (request.method !== "POST") return response(405, { error: "METHOD_NOT_ALLOWED" });
  const secret = Netlify.env.get(SECRET_NAME)?.trim();
  if (!secret) return response(503, { error: "CONTROL_SECRET_NOT_CONFIGURED" });

  const timestampText = request.headers.get("x-dominion-timestamp") ?? "";
  const nonce = request.headers.get("x-dominion-nonce") ?? "";
  const suppliedSignature = request.headers.get("x-dominion-signature") ?? "";
  const timestamp = Number(timestampText);
  if (!Number.isFinite(timestamp) || Math.abs(Date.now() - timestamp) > 60_000 ||
      !/^[0-9a-f-]{36}$/i.test(nonce) || !/^[0-9a-f]{64}$/i.test(suppliedSignature)) {
    return response(401, { error: "INVALID_CONTROL_AUTHENTICATION" });
  }

  const rawBody = await request.text();
  if (rawBody.length > 16_384) return response(413, { error: "CONTROL_BODY_TOO_LARGE" });
  const expected = createHmac("sha256", secret)
    .update(`${timestampText}.${nonce}.${rawBody}`)
    .digest();
  const supplied = Buffer.from(suppliedSignature, "hex");
  if (supplied.length !== expected.length || !timingSafeEqual(supplied, expected)) {
    return response(401, { error: "INVALID_CONTROL_SIGNATURE" });
  }

  const store = getStore({ name: "dominion-ctrader-oauth-prod", consistency: "strong" });
  try {
    await store.setJSON(`account/control-nonces/${nonce}`, {
      acceptedAt: Date.now(),
      expiresAt: Date.now() + 120_000,
    }, { onlyIfNew: true });
  } catch {
    return response(409, { error: "CONTROL_REQUEST_REPLAYED" });
  }

  let body: Record<string, unknown>;
  try {
    body = JSON.parse(rawBody) as Record<string, unknown>;
  } catch {
    return response(400, { error: "INVALID_JSON" });
  }
  if (typeof body.enabled !== "boolean") {
    return response(400, { error: "ENABLED_FLAG_REQUIRED" });
  }
  if (body.enabled && body.confirmDemoAutomation !== true) {
    return response(400, { error: "EXPLICIT_DEMO_AUTOMATION_CONFIRMATION_REQUIRED" });
  }

  const previous = await store.get("account/engine-config", { type: "json" }) as Record<string, unknown> | null;
  const profile = String(body.profile ?? previous?.profile ?? DEFAULT_CONFIG.profile);
  if (!["scalp", "intraday", "swing"].includes(profile)) {
    return response(400, { error: "INVALID_STRATEGY_PROFILE" });
  }
  const scoreThreshold = Number(body.scoreThreshold ?? previous?.scoreThreshold ?? DEFAULT_CONFIG.scoreThreshold);
  if (!Number.isInteger(scoreThreshold) || scoreThreshold < 1 || scoreThreshold > 15) {
    return response(400, { error: "INVALID_SCORE_THRESHOLD" });
  }
  const useSessionFilter = body.useSessionFilter ?? previous?.useSessionFilter ?? DEFAULT_CONFIG.useSessionFilter;
  if (typeof useSessionFilter !== "boolean") {
    return response(400, { error: "INVALID_SESSION_FILTER_SETTING" });
  }
  const riskPerTradePct = Number(body.riskPerTradePct ?? previous?.riskPerTradePct ?? DEFAULT_CONFIG.riskPerTradePct);
  const dailyLossLimitPct = Number(body.dailyLossLimitPct ?? previous?.dailyLossLimitPct ?? DEFAULT_CONFIG.dailyLossLimitPct);
  if (!Number.isFinite(riskPerTradePct) || riskPerTradePct < 0.05 || riskPerTradePct > 0.5) {
    return response(400, { error: "RISK_PER_TRADE_MUST_BE_BETWEEN_0_05_AND_0_5_PERCENT" });
  }
  if (!Number.isFinite(dailyLossLimitPct) || dailyLossLimitPct < 0.5 || dailyLossLimitPct > 2) {
    return response(400, { error: "DAILY_LOSS_LIMIT_MUST_BE_BETWEEN_0_5_AND_2_PERCENT" });
  }
  const rawSymbols = body.symbols ?? previous?.symbols ?? DEFAULT_CONFIG.symbols;
  if (!Array.isArray(rawSymbols) || rawSymbols.length < 1 || rawSymbols.length > 20) {
    return response(400, { error: "INVALID_SYMBOL_WATCHLIST" });
  }
  const symbols = rawSymbols.map((item) =>
    String(item).replace(/[\s/_.-]/g, "").toUpperCase()
  );
  if (symbols.some((item) => !/^[A-Z0-9]{3,20}$/.test(item)) || new Set(symbols).size !== symbols.length) {
    return response(400, { error: "INVALID_OR_DUPLICATE_SYMBOL" });
  }

  if (body.enabled) {
    const tradingStatus = await store.get("account/trading-status", { type: "json" }) as Record<string, unknown> | null;
    if (!tradingStatus || tradingStatus.connected !== true ||
        tradingStatus.environment !== "demo" || tradingStatus.access !== "trading" ||
        Number(tradingStatus.permissionScope) !== 1) {
      return response(409, { error: "CTRADER_DEMO_TRADING_AUTHORIZATION_REQUIRED" });
    }
  }

  const config = {
    ...DEFAULT_CONFIG,
    ...previous,
    enabled: body.enabled,
    profile,
    scoreThreshold,
    useSessionFilter,
    riskPerTradePct,
    dailyLossLimitPct,
    symbols,
    updatedAt: new Date().toISOString(),
    updatedBy: "authenticated-new-dashboard-proxy",
    environment: "demo",
  };
  await store.setJSON("account/engine-config", config);
  return response(200, {
    ok: true,
    enabled: config.enabled,
    profile: config.profile,
    scoreThreshold: config.scoreThreshold,
    useSessionFilter: config.useSessionFilter,
    riskPerTradePct: config.riskPerTradePct,
    dailyLossLimitPct: config.dailyLossLimitPct,
    symbols: config.symbols,
    environment: "demo",
    liveTradingEnabled: false,
  });
};
