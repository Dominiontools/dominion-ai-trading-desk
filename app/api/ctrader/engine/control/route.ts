import { consumeRequestNonce } from "../../../../../src/cloudflare/ctrader-d1-store.js";
import { validateCTraderEngineConfig } from "../../../../../src/cloudflare/ctrader-control-config.js";
import { readCTraderEngineConfig, saveCTraderEngineConfig } from "../../../../../src/cloudflare/ctrader-engine-config-store.js";
import { verifyCloudflareAccessRequest } from "../../../../../src/cloudflare/cloudflare-access-auth.js";
import { getCTraderRuntimeEnv } from "../../../../../src/cloudflare/next-runtime";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  const url = new URL(request.url);
  const origin = request.headers.get("origin");
  if (!origin || origin !== url.origin) {
    return Response.json({ ok: false, error: "SAME_ORIGIN_REQUEST_REQUIRED" }, { status: 403 });
  }

  const env = getCTraderRuntimeEnv();
  if (!env.CTRADER_DB) {
    return Response.json({ ok: false, error: "CTRADER_STORAGE_UNAVAILABLE" }, { status: 503 });
  }

  const auth = await verifyCloudflareAccessRequest({
    request,
    issuer: env.CF_ACCESS_ISSUER ?? "",
    audience: env.CF_ACCESS_AUD ?? "",
    allowedEmail: env.CTRADER_CONTROL_EMAIL ?? ""
  });
  if (!auth.ok) {
    return Response.json({ ok: false, error: auth.error }, {
      status: auth.error === "ACCESS_AUTH_REQUIRED" ? 401 : 403,
      headers: { "cache-control": "no-store" }
    });
  }

  const nonce = request.headers.get("x-dominion-nonce") ?? "";
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(nonce)) {
    return Response.json({ ok: false, error: "REQUEST_NONCE_REQUIRED" }, { status: 400 });
  }

  let rawBody;
  try {
    rawBody = await request.text();
  } catch {
    return Response.json({ ok: false, error: "INVALID_CONTROL_BODY" }, { status: 400 });
  }
  if (rawBody.length > 16_384) {
    return Response.json({ ok: false, error: "CONTROL_BODY_TOO_LARGE" }, { status: 413 });
  }

  let body;
  try {
    body = JSON.parse(rawBody);
  } catch {
    return Response.json({ ok: false, error: "INVALID_CONTROL_BODY" }, { status: 400 });
  }

  try {
    const accepted = await consumeRequestNonce(env.CTRADER_DB, nonce, "dashboard-control");
    if (!accepted) {
      return Response.json({ ok: false, error: "REQUEST_REPLAY_REJECTED" }, { status: 409 });
    }

    // The Next.js cTrader execution cycle is not connected yet. Saving paused
    // strategy preferences is safe; enabling any order-capable loop is not.
    if (body?.enabled === true) {
      return Response.json({
        ok: false,
        error: "CTRADER_EXECUTION_RUNTIME_NOT_READY",
        enabled: false,
        trading_enabled: false,
        live_trading_enabled: false
      }, { status: 409, headers: { "cache-control": "no-store" } });
    }

    const saved = await readCTraderEngineConfig(env.CTRADER_DB);
    const validated = validateCTraderEngineConfig(body, saved?.config ?? null);
    if (!validated.ok) {
      return Response.json({ ok: false, error: validated.error }, { status: 400 });
    }
    const pausedConfig = { ...validated.config, enabled: false };
    const result = await saveCTraderEngineConfig(env.CTRADER_DB, pausedConfig);
    return Response.json({
      ok: true,
      enabled: false,
      config: pausedConfig,
      updatedAt: result.updatedAt,
      trading_enabled: false,
      live_trading_enabled: false
    }, { headers: { "cache-control": "no-store", "x-content-type-options": "nosniff" } });
  } catch {
    return Response.json({ ok: false, error: "CTRADER_CONTROL_SAVE_FAILED" }, {
      status: 503, headers: { "cache-control": "no-store" }
    });
  }
}
