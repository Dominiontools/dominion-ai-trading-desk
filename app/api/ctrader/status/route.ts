import { readCTraderEngineConfig } from "../../../../src/cloudflare/ctrader-engine-config-store.js";
import { readCTraderEngineStatus } from "../../../../src/cloudflare/ctrader-engine-status-store.js";
import { getCTraderRuntimeEnv } from "../../../../src/cloudflare/next-runtime";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  const env = getCTraderRuntimeEnv();
  if (!env.CTRADER_DB) {
    return Response.json({
      ok: false,
      error: "ctrader_storage_unavailable",
      trading_enabled: false,
      live_trading_enabled: false
    }, { status: 503, headers: { "cache-control": "no-store" } });
  }

  try {
    const [status, savedConfig] = await Promise.all([
      readCTraderEngineStatus(env.CTRADER_DB),
      readCTraderEngineConfig(env.CTRADER_DB)
    ]);
    return Response.json({
      ok: true,
      service: "ctrader",
      status,
      config: savedConfig?.config ?? null,
      trading_enabled: false,
      live_trading_enabled: false
    }, { headers: { "cache-control": "no-store", "x-content-type-options": "nosniff" } });
  } catch {
    return Response.json({
      ok: false,
      error: "ctrader_status_unavailable",
      trading_enabled: false,
      live_trading_enabled: false
    }, { status: 503, headers: { "cache-control": "no-store" } });
  }
}
