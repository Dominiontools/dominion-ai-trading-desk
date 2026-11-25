import { getStore } from "@netlify/blobs";

const ALLOWED_ORIGINS = new Set([
  "https://dominion-ai-trading-desk-new.netlify.app",
  "https://dominion-ai-trading-desk-r30v.netlify.app",
]);

function headers(request: Request): Record<string, string> {
  const origin = request.headers.get("origin") ?? "";
  const result: Record<string, string> = {
    "access-control-allow-methods": "GET, OPTIONS",
    "access-control-max-age": "600",
    "cache-control": "no-store",
    "content-type": "application/json; charset=utf-8",
    "vary": "Origin",
    "x-content-type-options": "nosniff",
  };
  if (ALLOWED_ORIGINS.has(origin)) result["access-control-allow-origin"] = origin;
  return result;
}

export default async (request: Request) => {
  const responseHeaders = headers(request);
  if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: responseHeaders });
  if (request.method !== "GET") {
    return Response.json({ error: "METHOD_NOT_ALLOWED" }, { status: 405, headers: responseHeaders });
  }
  try {
    const store = getStore({ name: "dominion-ctrader-oauth-prod", consistency: "strong" });
    const [engineStatus, engineConfig, tradingStatus] = await Promise.all([
      store.get("account/engine-status", { type: "json" }) as Promise<Record<string, unknown> | null>,
      store.get("account/engine-config", { type: "json" }) as Promise<Record<string, unknown> | null>,
      store.get("account/trading-status", { type: "json" }) as Promise<Record<string, unknown> | null>,
    ]);
    return Response.json({
      status: String(engineStatus?.status ?? "NOT_CONFIGURED"),
      reason: String(engineStatus?.reason ?? "ENGINE_HAS_NOT_RUN"),
      enabled: engineConfig?.enabled === true,
      profile: String(engineConfig?.profile ?? "intraday"),
      scoreThreshold: Number(engineConfig?.scoreThreshold ?? 6),
      symbols: Array.isArray(engineConfig?.symbols) ? engineConfig?.symbols : ["XAUUSD", "EURUSD", "GBPUSD"],
      tradingAuthorized: tradingStatus?.connected === true &&
        tradingStatus?.environment === "demo" &&
        tradingStatus?.access === "trading" &&
        Number(tradingStatus?.permissionScope) === 1,
      tradingAccountCount: Number(tradingStatus?.demoAccountCount ?? 0),
      environment: "demo",
      liveTradingEnabled: false,
      lastUpdatedAt: engineStatus?.updatedAt ?? null,
    }, { headers: responseHeaders });
  } catch {
    return Response.json({ error: "ENGINE_STATUS_UNAVAILABLE" }, { status: 503, headers: responseHeaders });
  }
};
