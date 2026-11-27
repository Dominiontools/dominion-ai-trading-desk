import { readCTraderEngineConfig } from "./cloudflare/ctrader-engine-config-store.js";
import { readCTraderEngineStatus } from "./cloudflare/ctrader-engine-status-store.js";
import { createOAuthState } from "./cloudflare/ctrader-d1-store.js";
import { buildCTraderAuthorizationUrl } from "./cloudflare/ctrader-oauth.js";

const json = (body, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      "x-content-type-options": "nosniff"
    }
  });

function randomOAuthState() {
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === "/api/health") {
      if (request.method !== "GET") return json({ ok: false, error: "method_not_allowed" }, 405);
      return json({
        ok: true,
        service: "dominion-ai-trading-desk",
        runtime: "cloudflare-workers",
        stage: "backend-migration-scaffold",
        trading_enabled: false,
        live_trading_enabled: false
      });
    }

    if (url.pathname === "/api/ctrader/oauth/start") {
      if (request.method !== "GET") return json({ ok: false, error: "method_not_allowed" }, 405);
      if (!env.CTRADER_DB) return json({ ok: false, error: "ctrader_storage_unavailable" }, 503);
      const accessKind = url.searchParams.get("mode") ?? "view-only";
      if (accessKind !== "view-only" && accessKind !== "trading") {
        return json({ ok: false, error: "invalid_access_mode" }, 400);
      }
      const clientId = typeof env.CTRADER_CLIENT_ID === "string" ? env.CTRADER_CLIENT_ID.trim() : "";
      const redirectUri = typeof env.CTRADER_REDIRECT_URI === "string" ? env.CTRADER_REDIRECT_URI.trim() : "";
      if (!clientId || !redirectUri) return json({ ok: false, error: "ctrader_oauth_not_configured" }, 503);
      try {
        const state = randomOAuthState();
        await createOAuthState(env.CTRADER_DB, state, accessKind);
        const authorizationUrl = buildCTraderAuthorizationUrl({
          clientId, redirectUri, requestOrigin: url.origin, accessKind, state
        });
        return new Response(null, {
          status: 302,
          headers: {
            location: authorizationUrl,
            "cache-control": "no-store",
            "referrer-policy": "no-referrer",
            "x-content-type-options": "nosniff"
          }
        });
      } catch {
        return json({ ok: false, error: "ctrader_oauth_start_failed" }, 503);
      }
    }

    if (url.pathname === "/api/ctrader/status") {
      if (request.method !== "GET") return json({ ok: false, error: "method_not_allowed" }, 405);
      if (!env.CTRADER_DB) return json({ ok: false, error: "ctrader_storage_unavailable", trading_enabled: false }, 503);
      try {
        const [status, savedConfig] = await Promise.all([
          readCTraderEngineStatus(env.CTRADER_DB),
          readCTraderEngineConfig(env.CTRADER_DB)
        ]);
        return json({
          ok: true, service: "ctrader", status, config: savedConfig?.config ?? null,
          trading_enabled: false, live_trading_enabled: false
        });
      } catch {
        return json({ ok: false, error: "ctrader_status_unavailable", trading_enabled: false }, 503);
      }
    }

    if (url.pathname.startsWith("/api/ctrader/")) {
      return json({
        ok: false, service: "ctrader", status: "not_migrated", trading_enabled: false,
        message: "The cTrader demo service is not connected to this Worker yet."
      }, 503);
    }

    if (url.pathname.startsWith("/api/crypto/")) {
      return json({
        ok: false, service: "crypto", status: "phone_engine_required", trading_enabled: false,
        message: "Crypto market monitoring still requires the Android phone engine. No exchange orders are routed by this Worker."
      }, 503);
    }

    if (url.pathname.startsWith("/api/")) return json({ ok: false, error: "not_found" }, 404);
    return env.ASSETS.fetch(request);
  }
};
