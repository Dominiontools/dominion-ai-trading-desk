import { consumeOAuthState, saveEncryptedCTraderToken } from "../../../../../src/cloudflare/ctrader-d1-store.js";
import { verifyCTraderDemoAccount } from "../../../../../src/cloudflare/ctrader-demo-verification.js";
import { buildCTraderAuthorizationUrl, validateCTraderTokenResponse } from "../../../../../src/cloudflare/ctrader-oauth.js";
import { encryptCTraderTokenRecord } from "../../../../../src/cloudflare/ctrader-token-crypto.js";
import { saveCTraderEngineStatus } from "../../../../../src/cloudflare/ctrader-engine-status-store.js";
import { getCTraderRuntimeEnv } from "../../../../../src/cloudflare/next-runtime";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const COOKIE_NAME = "dominion_ctrader_oauth_state";
const COOKIE_PATH = "/api/ctrader/oauth/callback";

function readStateCookie(request: Request): string | null {
  const cookie = request.headers.get("cookie") ?? "";
  for (const part of cookie.split(";")) {
    const separator = part.indexOf("=");
    if (separator >= 0 && part.slice(0, separator).trim() === COOKIE_NAME) {
      return part.slice(separator + 1).trim();
    }
  }
  return null;
}

function html(title: string, message: string, status = 200, clearCookie = false): Response {
  const escape = (value: string) => value.replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[character] ?? character);
  return new Response(
    `<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${escape(title)}</title><body style="font:16px system-ui;max-width:620px;margin:12vh auto;padding:24px;line-height:1.5"><h2>${escape(title)}</h2><p>${escape(message)}</p></body></html>`,
    {
      status,
      headers: {
        "content-type": "text/html; charset=utf-8",
        "cache-control": "no-store",
        "x-content-type-options": "nosniff",
        "referrer-policy": "no-referrer",
        ...(clearCookie ? { "set-cookie": `${COOKIE_NAME}=; Max-Age=0; Path=${COOKIE_PATH}; HttpOnly; Secure; SameSite=None` } : {})
      }
    }
  );
}

export async function GET(request: Request) {
  const url = new URL(request.url);
  const env = getCTraderRuntimeEnv();
  if (!env.CTRADER_DB) return html("Setup incomplete", "Secure cTrader storage is not configured.", 503, true);

  const code = url.searchParams.get("code");
  const returnedState = url.searchParams.get("state");
  if (url.searchParams.has("error")) {
    return html("Authorization not completed", "cTrader did not grant access. Return to the app and try again.", 400, true);
  }
  if (!code || code.length > 4096) {
    return html("Authorization details missing", "Start cTrader authorization again from the app.", 400, true);
  }

  const cookieState = readStateCookie(request);
  const state = returnedState
    ? (/^[A-Za-z0-9_-]{40,60}$/.test(returnedState) ? returnedState : null)
    : cookieState;
  if (!state || !/^[A-Za-z0-9_-]{40,60}$/.test(state)) {
    return html("Authorization session missing", "The browser authorization session was not preserved. Start again from Dominion AI Trading Desk in the same browser.", 400, true);
  }

  const clientId = env.CTRADER_CLIENT_ID?.trim() ?? "";
  const clientSecret = env.CTRADER_CLIENT_SECRET ?? "";
  const redirectUri = env.CTRADER_REDIRECT_URI?.trim() ?? "";
  const encryptionKey = env.CTRADER_TOKEN_ENCRYPTION_KEY ?? "";
  if (!clientId || !clientSecret || !redirectUri || !encryptionKey) {
    return html("Setup incomplete", "Required cTrader server settings are missing. No token was saved.", 503, true);
  }

  try {
    const callback = new URL(redirectUri);
    if (callback.protocol !== "https:" || callback.origin !== url.origin ||
        callback.pathname !== "/api/ctrader/oauth/callback" || callback.search || callback.hash) {
      return html("Setup incomplete", "The registered cTrader callback URL does not match this Cloudflare service.", 503, true);
    }

    const oauthState = await consumeOAuthState(env.CTRADER_DB, state);
    if (!oauthState) {
      return html("Authorization session expired", "The one-time authorization session is invalid or expired. Start again from the app.", 400, true);
    }

    const accessKind = oauthState.accessKind;
    const tokenParams = new URLSearchParams({
      grant_type: "authorization_code", code, redirect_uri: redirectUri,
      client_id: clientId, client_secret: clientSecret
    });
    const tokenResponse = await fetch(`https://openapi.ctrader.com/apps/token?${tokenParams.toString()}`, {
      method: "GET",
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(20_000)
    });
    if (!tokenResponse.ok) {
      return html("Token exchange failed", "cTrader did not accept the authorization code. No token was saved.", 502, true);
    }

    const tokenData = validateCTraderTokenResponse(await tokenResponse.json());
    const verified = await verifyCTraderDemoAccount({
      accessToken: tokenData.accessToken,
      clientId,
      clientSecret,
      expectedScope: accessKind === "trading" ? 1 : 0
    });
    const encrypted = await encryptCTraderTokenRecord({
      ...tokenData,
      issuedAt: Date.now(),
      environment: "demo",
      access: accessKind,
      accountId: verified.authorizedAccountId
    }, encryptionKey);

    await saveEncryptedCTraderToken(env.CTRADER_DB, accessKind, encrypted, verified.authorizedAccountId);
    await saveCTraderEngineStatus(env.CTRADER_DB, {
      status: "CONNECTED",
      reason: "ENGINE_DISABLED",
      connected: true,
      isLive: false,
      environment: "demo",
      access: accessKind,
      permissionScope: verified.permissionScope,
      demoAccountCount: verified.demoAccountCount,
      liveTradingEnabled: false
    });

    return html(
      "cTrader demo authorization received",
      `Your ${accessKind === "trading" ? "demo-trading" : "view-only"} permission was verified. The demo account was authenticated and tokens were encrypted before storage. No trade was placed.`,
      200,
      true
    );
  } catch {
    return html(
      "cTrader authorization could not be completed",
      "The callback failed during secure verification. No trade was placed. Start authorization again after the configuration issue is fixed.",
      502,
      true
    );
  }
}
