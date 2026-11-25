import { getDeployStore, getStore } from "@netlify/blobs";
import { createCipheriv, randomBytes } from "node:crypto";

const REDIRECT_URI =
  "https://dominion-ai-trading-desk-p7cp.netlify.app/.netlify/functions/ctrader-callback";
const AUTHORIZE_URL =
  "https://id.ctrader.com/my/settings/openapi/grantingaccess/";
const TOKEN_URL = "https://openapi.ctrader.com/apps/token";
const STATE_COOKIE = "dominion_oauth_state";
const STATE_COOKIE_PATH = "/.netlify/functions/ctrader-callback";

function html(title: string, message: string, status = 200, headers: Record<string, string> = {}) {
  return new Response(
    `<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${title}</title><body style="font:16px system-ui;max-width:620px;margin:12vh auto;padding:24px;line-height:1.5"><h2>${title}</h2><p>${message}</p></body></html>`,
    { status, headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store", "x-content-type-options": "nosniff", "referrer-policy": "no-referrer", ...headers } },
  );
}

function cookieHeader(value: string, maxAge: number) {
  return `${STATE_COOKIE}=${value}; Max-Age=${maxAge}; Path=${STATE_COOKIE_PATH}; HttpOnly; Secure; SameSite=Lax`;
}

function readCookie(request: Request, name: string): string | null {
  const cookieHeaderValue = request.headers.get("cookie") ?? "";
  for (const part of cookieHeaderValue.split(";")) {
    const separator = part.indexOf("=");
    if (separator < 0) continue;
    if (part.slice(0, separator).trim() === name) {
      return part.slice(separator + 1).trim();
    }
  }
  return null;
}

function requiredEnv(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`Missing required Netlify environment variable: ${name}`);
  return value;
}

function stores(context: { deploy: { context: string } }) {
  if (context.deploy.context === "production") {
    return {
      state: getStore({ name: "dominion-ctrader-oauth-prod", consistency: "strong" }),
      tokens: getStore({ name: "dominion-ctrader-oauth-prod", consistency: "strong" }),
    };
  }
  return {
    state: getDeployStore({ name: "dominion-ctrader-oauth-preview", consistency: "strong" }),
    tokens: getDeployStore({ name: "dominion-ctrader-oauth-preview", consistency: "strong" }),
  };
}

function encryptTokens(payload: unknown, keyText: string) {
  const key = Buffer.from(keyText, "base64");
  if (key.length !== 32) throw new Error("CTRADER_TOKEN_ENCRYPTION_KEY must be a base64-encoded 32-byte key.");
  const iv = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", key, iv);
  const ciphertext = Buffer.concat([
    cipher.update(JSON.stringify(payload), "utf8"),
    cipher.final(),
  ]);
  return {
    version: 1,
    algorithm: "aes-256-gcm",
    iv: iv.toString("base64"),
    tag: cipher.getAuthTag().toString("base64"),
    ciphertext: ciphertext.toString("base64"),
    savedAt: new Date().toISOString(),
  };
}

async function verifyDemoAccounts(accessToken: string, clientId: string, clientSecret: string) {
  const socket = new WebSocket("wss://demo.ctraderapi.com:5036");
  const accounts = await new Promise<{ permissionScope?: number; accounts: Record<string, unknown>[]; authorizedAccountId?: string }>((resolve, reject) => {
    let stage: "connecting" | "app-auth" | "account-list" | "account-auth" = "connecting";
    let settled = false;
    const finish = (error?: Error, result?: { permissionScope?: number; accounts: Record<string, unknown>[]; authorizedAccountId?: string }) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      try { socket.close(); } catch { /* already closed */ }
      if (error) reject(error);
      else resolve(result ?? { accounts: [] });
    };
    const send = (payloadType: number, payload: Record<string, unknown>) => {
      socket.send(JSON.stringify({
        clientMsgId: randomBytes(12).toString("hex"),
        payloadType,
        payload,
      }));
    };
    const timeout = setTimeout(() => finish(new Error("cTrader demo account verification timed out.")), 18000);
    socket.addEventListener("open", () => {
      stage = "app-auth";
      send(2100, { clientId, clientSecret });
    });
    socket.addEventListener("message", (event) => {
      try {
        const message = JSON.parse(String(event.data)) as { payloadType?: number; payload?: Record<string, unknown> };
        if (message.payloadType === 2142) {
          const detail = String(message.payload?.description || message.payload?.errorCode || "cTrader Open API returned an error.");
          finish(new Error(detail));
          return;
        }
        if (stage === "app-auth" && message.payloadType === 2101) {
          stage = "account-list";
          send(2149, { accessToken });
          return;
        }
        if (stage === "account-list" && message.payloadType === 2150) {
          const payload = message.payload ?? {};
          const raw = Array.isArray(payload.ctidTraderAccount) ? payload.ctidTraderAccount as Record<string, unknown>[] : [];
          const demoAccounts = raw.filter((account) => account.isLive === false);
          if (payload.permissionScope !== 0) {
            finish(new Error("cTrader did not confirm view-only account permission."));
            return;
          }
          if (demoAccounts.length === 0) {
            finish(undefined, { permissionScope: Number(payload.permissionScope), accounts: [] });
            return;
          }
          const firstId = String(demoAccounts[0].ctidTraderAccountId ?? "");
          if (!firstId) {
            finish(new Error("cTrader returned a demo account without an account ID."));
            return;
          }
          stage = "account-auth";
          send(2102, { ctidTraderAccountId: firstId, accessToken });
          (socket as WebSocket & { __demoAccounts?: Record<string, unknown>[]; __scope?: number }).__demoAccounts = demoAccounts;
          (socket as WebSocket & { __scope?: number }).__scope = Number(payload.permissionScope);
          return;
        }
        if (stage === "account-auth" && message.payloadType === 2103) {
          const state = socket as WebSocket & { __demoAccounts?: Record<string, unknown>[]; __scope?: number };
          finish(undefined, {
            permissionScope: state.__scope,
            accounts: state.__demoAccounts ?? [],
            authorizedAccountId: String(message.payload?.ctidTraderAccountId ?? ""),
          });
        }
      } catch {
        finish(new Error("cTrader returned an unreadable account response."));
      }
    });
    socket.addEventListener("error", () => finish(new Error("Could not connect to the cTrader demo Open API.")));
    socket.addEventListener("close", () => {
      if (!settled) finish(new Error("cTrader closed the demo connection before account verification completed."));
    });
  });
  return accounts;
}

export default async (request: Request, context: { deploy: { context: string } }) => {
  if (request.method !== "GET") {
    return html("Method not allowed", "Use the cTrader authorization link with a browser.", 405);
  }

  const url = new URL(request.url);
  const code = url.searchParams.get("code");
  const oauthError = url.searchParams.get("error");
  const clearCookie = cookieHeader("", 0);

  if (oauthError) {
    return html("cTrader authorization not completed", "cTrader did not grant access. Return to Dominion AI Trading Desk and try again.", 400, { "set-cookie": clearCookie });
  }

  let stage = "checking configuration";
  try {
    const clientId = requiredEnv("CTRADER_CLIENT_ID");
    const clientSecret = requiredEnv("CTRADER_CLIENT_SECRET");
    stage = "opening secure storage";
    const storesForDeploy = stores(context);

    // cTrader's documented redirect response returns the authorization code;
    // it does not document an OAuth state parameter. Bind the browser session
    // with a short-lived, HttpOnly, Secure, SameSite=Lax cookie instead.
    if (!code) {
      const nonce = randomBytes(32).toString("base64url");
      stage = "creating authorization session";
      await storesForDeploy.state.setJSON(
        `state/${nonce}`,
        { createdAt: Date.now() },
        { onlyIfNew: true },
      );

      const authorize = new URL(AUTHORIZE_URL);
      authorize.search = new URLSearchParams({
        client_id: clientId,
        redirect_uri: REDIRECT_URI,
        scope: "accounts",
        product: "web",
      }).toString();

      return new Response(null, {
        status: 302,
        headers: {
          location: authorize.toString(),
          "cache-control": "no-store",
          "set-cookie": cookieHeader(nonce, 600),
          "referrer-policy": "no-referrer",
        },
      });
    }

    stage = "validating browser session";
    const nonce = readCookie(request, STATE_COOKIE);
    if (!nonce || !/^[A-Za-z0-9_-]{40,60}$/.test(nonce)) {
      return html("Authorization session missing", "The browser authorization session was not preserved. Start again from Dominion AI Trading Desk in the same browser.", 400, { "set-cookie": clearCookie });
    }

    const stateKey = `state/${nonce}`;
    stage = "reading authorization session";
    const stateRecord = await storesForDeploy.state.get(stateKey, { type: "json" }) as { createdAt?: number } | null;
    if (!stateRecord || typeof stateRecord.createdAt !== "number" || Date.now() - stateRecord.createdAt > 10 * 60 * 1000) {
      return html("Authorization session expired", "Please start cTrader authorization again from Dominion AI Trading Desk.", 400, { "set-cookie": clearCookie });
    }
    stage = "consuming authorization session";
    await storesForDeploy.state.delete(stateKey);

    const tokenParams = new URLSearchParams({
      grant_type: "authorization_code",
      code,
      redirect_uri: REDIRECT_URI,
      client_id: clientId,
      client_secret: clientSecret,
    });
    stage = "exchanging cTrader authorization code";
    const tokenResponse = await fetch(`${TOKEN_URL}?${tokenParams.toString()}`, {
      method: "GET",
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(20000),
    });
    if (!tokenResponse.ok) {
      return html("Token exchange failed", "cTrader did not accept the authorization code. Start again; no token was saved.", 502, { "set-cookie": clearCookie });
    }

    stage = "reading cTrader token response";
    const tokenData = await tokenResponse.json() as Record<string, unknown>;
    if (
      tokenData.errorCode ||
      typeof tokenData.accessToken !== "string" ||
      typeof tokenData.refreshToken !== "string" ||
      typeof tokenData.tokenType !== "string" ||
      !Number.isFinite(Number(tokenData.expiresIn)) ||
      Number(tokenData.expiresIn) <= 0
    ) {
      return html("Token exchange failed", "cTrader returned an incomplete authorization response. No token was saved.", 502, { "set-cookie": clearCookie });
    }

    stage = "verifying demo account access";
    const accountCheck = await verifyDemoAccounts(
      String(tokenData.accessToken),
      clientId,
      clientSecret,
    );
    stage = "encrypting cTrader tokens";
    const encrypted = encryptTokens(tokenData, requiredEnv("CTRADER_TOKEN_ENCRYPTION_KEY"));
    stage = "saving encrypted cTrader tokens";
    await storesForDeploy.tokens.setJSON("account/tokens", encrypted);

    const accountSummary = accountCheck.accounts.length
      ? ` Verified ${accountCheck.accounts.length} demo account(s); the first demo account was authenticated in read-only mode.`
      : " Authorization succeeded, but no demo account was included in the approved account list.";
    return html(
      "cTrader authorization received",
      `Your access is view-only. The cTrader demo connection check completed.${accountSummary} Tokens were encrypted before storage. No trade was placed.`,
      200,
      { "set-cookie": clearCookie },
    );
  } catch (error) {
    const detail = error instanceof Error ? error.message : "Unknown error";
    console.error("cTrader callback failed", { stage, error: detail });
    const safeMessage = error instanceof Error && error.message.startsWith("Missing required Netlify environment variable:")
      ? error.message
      : `The callback failed while ${stage}. Please start authorization again after the issue is fixed.`;
    return html("Callback setup incomplete", safeMessage, 500, { "set-cookie": clearCookie });
  }
};

// Deployment refresh: pick up the updated production encryption key.
