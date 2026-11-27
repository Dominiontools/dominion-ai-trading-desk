import { readCTraderEngineConfig } from "./cloudflare/ctrader-engine-config-store.js";
import { readCTraderEngineStatus } from "./cloudflare/ctrader-engine-status-store.js";
import { createOAuthState } from "./cloudflare/ctrader-d1-store.js";
import { buildCTraderAuthorizationUrl, validateCTraderTokenResponse } from "./cloudflare/ctrader-oauth.js";
import { consumeOAuthState, saveEncryptedCTraderToken } from "./cloudflare/ctrader-d1-store.js";
import { encryptCTraderTokenRecord } from "./cloudflare/ctrader-token-crypto.js";
import { verifyCTraderDemoAccount } from "./cloudflare/ctrader-demo-verification.js";
import { saveCTraderEngineStatus } from "./cloudflare/ctrader-engine-status-store.js";

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


    if (url.pathname === "/api/ctrader/oauth/callback") {
      const html = (title, message, status = 200) => new Response(
        `<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${title}</title><body style="font:16px system-ui;max-width:620px;margin:12vh auto;padding:24px;line-height:1.5"><h2>${title}</h2><p>${message}</p></body></html>`,
        { status, headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store", "x-content-type-options": "nosniff", "referrer-policy": "no-referrer" } }
      );
      if (request.method !== "GET") return html("Method not allowed", "Start cTrader authorization from Dominion AI Trading Desk.", 405);
      if (!env.CTRADER_DB) return html("Setup incomplete", "Secure cTrader storage is not configured.", 503);
      const code = url.searchParams.get("code");
      const state = url.searchParams.get("state");
      if (url.searchParams.has("error")) return html("Authorization not completed", "cTrader did not grant access. Return to the app and try again.", 400);
      if (!code || code.length > 4096 || !state) return html("Authorization details missing", "Start cTrader authorization again from the app.", 400);
      const clientId = typeof env.CTRADER_CLIENT_ID === "string" ? env.CTRADER_CLIENT_ID.trim() : "";
      const clientSecret = typeof env.CTRADER_CLIENT_SECRET === "string" ? env.CTRADER_CLIENT_SECRET : "";
      const redirectUri = typeof env.CTRADER_REDIRECT_URI === "string" ? env.CTRADER_REDIRECT_URI.trim() : "";
      const encryptionKey = typeof env.CTRADER_TOKEN_ENCRYPTION_KEY === "string" ? env.CTRADER_TOKEN_ENCRYPTION_KEY : "";
      if (!clientId || !clientSecret || !redirectUri || !encryptionKey) {
        return html("Setup incomplete", "Required cTrader server settings are missing. No token was saved.", 503);
      }
      try {
        const callback = new URL(redirectUri);
        if (callback.protocol !== "https:" || callback.origin !== url.origin ||
            callback.pathname !== "/api/ctrader/oauth/callback" || callback.search || callback.hash) {
          return html("Setup incomplete", "The registered cTrader callback URL does not match this Cloudflare service.", 503);
        }
        const oauthState = await consumeOAuthState(env.CTRADER_DB, state);
        if (!oauthState) return html("Authorization session expired", "The one-time authorization session is invalid or expired. Start again from the app.", 400);
        const accessKind = oauthState.accessKind;
        const tokenParams = new URLSearchParams({
          grant_type: "authorization_code", code, redirect_uri: redirectUri,
          client_id: clientId, client_secret: clientSecret
        });
        const tokenResponse = await fetch(`https://openapi.ctrader.com/apps/token?${tokenParams.toString()}`, {
          method: "GET", headers: { Accept: "application/json" }, signal: AbortSignal.timeout(20_000)
        });
        if (!tokenResponse.ok) return html("Token exchange failed", "cTrader did not accept the authorization code. No token was saved.", 502);
        const tokenData = validateCTraderTokenResponse(await tokenResponse.json());
        const verified = await verifyCTraderDemoAccount({
          accessToken: tokenData.accessToken, clientId, clientSecret,
          expectedScope: accessKind === "trading" ? 1 : 0
        });
        const encrypted = await encryptCTraderTokenRecord(
          { ...tokenData, issuedAt: Date.now(), environment: "demo", access: accessKind,
            accountId: verified.authorizedAccountId },
          encryptionKey
        );
        await saveEncryptedCTraderToken(env.CTRADER_DB, accessKind, encrypted, verified.authorizedAccountId);
        await saveCTraderEngineStatus(env.CTRADER_DB, {
          status: "CONNECTED", reason: "ENGINE_DISABLED", connected: true, isLive: false,
          environment: "demo", access: accessKind, permissionScope: verified.permissionScope,
          demoAccountCount: verified.demoAccountCount, liveTradingEnabled: false
        });
        return html("cTrader demo authorization received",
          `Your ${accessKind === "trading" ? "demo-trading" : "view-only"} permission was verified. The demo account was authenticated and tokens were encrypted before storage. No trade was placed.`);
      } catch {
        return html("cTrader authorization could not be completed",
          "The callback failed during secure verification. No trade was placed. Start authorization again after the configuration issue is fixed.", 502);
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
