import { getStore } from "@netlify/blobs";
import { createCipheriv, randomBytes } from "node:crypto";

const REDIRECT_URI =
  "https://dominion-ai-trading-desk.netlify.app/.netlify/functions/ctrader-callback";
const AUTHORIZE_URL =
  "https://id.ctrader.com/my/settings/openapi/grantingaccess/";
const TOKEN_URL = "https://openapi.ctrader.com/apps/token";

function html(title: string, message: string, status = 200) {
  return new Response(
    `<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${title}</title><body style="font:16px system-ui;max-width:620px;margin:12vh auto;padding:24px;line-height:1.5"><h2>${title}</h2><p>${message}</p></body></html>`,
    { status, headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" } },
  );
}

function requiredEnv(name: string): string {
  const value = Netlify.env.get(name)?.trim();
  if (!value) throw new Error(`Missing required Netlify environment variable: ${name}`);
  return value;
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

export default async (request: Request) => {
  if (request.method !== "GET") {
    return html("Method not allowed", "Use the cTrader authorization link with a browser.", 405);
  }

  const url = new URL(request.url);
  const code = url.searchParams.get("code");
  const returnedState = url.searchParams.get("state");
  const oauthError = url.searchParams.get("error");

  if (oauthError) {
    return html("cTrader authorization not completed", "cTrader did not grant access. Return to Dominion AI Trading Desk and try again.", 400);
  }

  try {
    const clientId = requiredEnv("CTRADER_CLIENT_ID");
    const clientSecret = requiredEnv("CTRADER_CLIENT_SECRET");

    // Opening the callback URL without a code starts the OAuth authorization.
    if (!code && !returnedState) {
      const nonce = randomBytes(32).toString("base64url");
      const states = getStore({ name: "dominion-ctrader-oauth", consistency: "strong" });
      await states.setJSON(`state/${nonce}`, { createdAt: Date.now() }, { onlyIfNew: true });

      const authorize = new URL(AUTHORIZE_URL);
      authorize.search = new URLSearchParams({
        client_id: clientId,
        redirect_uri: REDIRECT_URI,
        scope: "trading",
        product: "web",
        state: nonce,
      }).toString();

      return Response.redirect(authorize.toString(), 302);
    }

    if (!code || !returnedState || !/^[A-Za-z0-9_-]{40,60}$/.test(returnedState)) {
      return html("Invalid callback", "The authorization response is incomplete. Start again from the Dominion app.", 400);
    }

    const states = getStore({ name: "dominion-ctrader-oauth", consistency: "strong" });
    const stateKey = `state/${returnedState}`;
    const stateRecord = await states.get(stateKey, { type: "json" }) as { createdAt?: number } | null;
    if (!stateRecord || typeof stateRecord.createdAt !== "number" || Date.now() - stateRecord.createdAt > 10 * 60 * 1000) {
      return html("Authorization session expired", "Please start cTrader authorization again from the Dominion app.", 400);
    }
    await states.delete(stateKey);

    const tokenParams = new URLSearchParams({
      grant_type: "authorization_code",
      code,
      redirect_uri: REDIRECT_URI,
      client_id: clientId,
      client_secret: clientSecret,
    });
    const tokenResponse = await fetch(`${TOKEN_URL}?${tokenParams.toString()}`, {
      method: "GET",
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(20000),
    });
    if (!tokenResponse.ok) {
      return html("Token exchange failed", "cTrader did not accept the authorization code. Start again; no token was saved.", 502);
    }

    const tokenData = await tokenResponse.json() as Record<string, unknown>;
    if (
      tokenData.errorCode ||
      typeof tokenData.accessToken !== "string" ||
      typeof tokenData.refreshToken !== "string" ||
      typeof tokenData.tokenType !== "string" ||
      !Number.isFinite(Number(tokenData.expiresIn)) ||
      Number(tokenData.expiresIn) <= 0
    ) {
      return html("Token exchange failed", "cTrader returned an incomplete authorization response. No token was saved.", 502);
    }

    const encrypted = encryptTokens(tokenData, requiredEnv("CTRADER_TOKEN_ENCRYPTION_KEY"));
    const tokenStore = getStore({ name: "dominion-ctrader-oauth", consistency: "strong" });
    await tokenStore.setJSON("account/tokens", encrypted);

    return html(
      "cTrader authorization received",
      "Your cTrader authorization code was exchanged and the tokens were encrypted before storage. You can close this page and return to Dominion AI Trading Desk. No trade was placed.",
    );
  } catch (error) {
    const safeMessage = error instanceof Error && error.message.startsWith("Missing required Netlify environment variable:")
      ? error.message
      : "The callback could not complete securely. Check the Netlify function logs and configuration.";
    return html("Callback setup incomplete", safeMessage, 500);
  }
};
