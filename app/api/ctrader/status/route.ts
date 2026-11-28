import { readCTraderEngineConfig } from "../../../../src/cloudflare/ctrader-engine-config-store.js";
import { readCTraderEngineStatus } from "../../../../src/cloudflare/ctrader-engine-status-store.js";
import { getCTraderRuntimeEnv } from "../../../../src/cloudflare/next-runtime";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  const env = getCTraderRuntimeEnv();
  if (!env.CTRADER_DB) {
    return Response.json({
      error: "CTRADER_STORAGE_UNAVAILABLE",
      status: "NOT_CONFIGURED",
      reason: "ENGINE_HAS_NOT_RUN",
      enabled: false,
      tradingAuthorized: false,
      environment: "demo",
      liveTradingEnabled: false
    }, { status: 503, headers: { "cache-control": "no-store" } });
  }

  try {
    const [brokerStatus, saved] = await Promise.all([
      readCTraderEngineStatus(env.CTRADER_DB),
      readCTraderEngineConfig(env.CTRADER_DB)
    ]);
    const config = saved?.config ?? null;
    return Response.json({
      status: brokerStatus.status,
      reason: brokerStatus.reason,
      connected: brokerStatus.connected === true,
      access: brokerStatus.access,
      demoAccountCount: brokerStatus.demoAccountCount,
      enabled: config?.enabled === true,
      profile: config?.profile ?? "intraday",
      scoreThreshold: config?.scoreThreshold ?? 6,
      useSessionFilter: config?.useSessionFilter !== false,
      riskPerTradePct: config?.riskPerTradePct ?? 0.5,
      dailyLossLimitPct: config?.dailyLossLimitPct ?? 2,
      symbols: config?.symbols ?? ["XAUUSD", "EURUSD", "GBPUSD"],
      tradingAuthorized: brokerStatus.connected === true &&
        brokerStatus.environment === "demo" &&
        brokerStatus.access === "trading" &&
        brokerStatus.permissionScope === 1,
      tradingAccountCount: brokerStatus.demoAccountCount ?? 0,
      environment: "demo",
      liveTradingEnabled: false,
      lastUpdatedAt: brokerStatus.updatedAt == null
        ? null
        : new Date(brokerStatus.updatedAt * 1000).toISOString()
    }, { headers: { "cache-control": "no-store", "x-content-type-options": "nosniff" } });
  } catch {
    return Response.json({
      error: "CTRADER_STATUS_UNAVAILABLE",
      status: "ERROR",
      enabled: false,
      tradingAuthorized: false,
      environment: "demo",
      liveTradingEnabled: false
    }, { status: 503, headers: { "cache-control": "no-store" } });
  }
}
