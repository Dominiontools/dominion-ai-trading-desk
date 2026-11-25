import { getStore } from "@netlify/blobs";
import { createDecipheriv, randomBytes } from "node:crypto";

const ALLOWED_DASHBOARD_ORIGINS = new Set([
  "https://dominion-ai-trading-desk-new.netlify.app",
  "https://dominion-ai-trading-desk-r30v.netlify.app",
]);

function corsHeaders(request: Request) {
  const origin = request.headers.get("origin") ?? "";
  const headers: Record<string, string> = {
    "access-control-allow-methods": "GET, OPTIONS",
    "access-control-max-age": "600",
    "cache-control": "no-store",
    "content-type": "application/json; charset=utf-8",
    "vary": "Origin",
    "x-content-type-options": "nosniff",
  };
  if (ALLOWED_DASHBOARD_ORIGINS.has(origin)) {
    headers["access-control-allow-origin"] = origin;
  }
  return headers;
}

function decryptTokens(encrypted: {
  iv?: string;
  tag?: string;
  ciphertext?: string;
}, keyText: string) {
  const key = Buffer.from(keyText, "base64");
  if (key.length !== 32 || !encrypted.iv || !encrypted.tag || !encrypted.ciphertext) {
    throw new Error("Stored cTrader token record is invalid.");
  }
  const decipher = createDecipheriv("aes-256-gcm", key, Buffer.from(encrypted.iv, "base64"));
  decipher.setAuthTag(Buffer.from(encrypted.tag, "base64"));
  const clear = Buffer.concat([
    decipher.update(Buffer.from(encrypted.ciphertext, "base64")),
    decipher.final(),
  ]).toString("utf8");
  return JSON.parse(clear) as Record<string, unknown>;
}

async function verifyDemoAccounts(accessToken: string, clientId: string, clientSecret: string, expectedScope: number) {
  const socket = new WebSocket("wss://demo.ctraderapi.com:5036");
  return await new Promise<{ permissionScope: number; accounts: Record<string, unknown>[]; authorizedAccountId: string }>((resolve, reject) => {
    let stage: "connecting" | "app-auth" | "account-list" | "account-auth" = "connecting";
    let settled = false;
    let demoAccounts: Record<string, unknown>[] = [];
    let permissionScope = -1;
    const finish = (error?: Error, result?: { permissionScope: number; accounts: Record<string, unknown>[]; authorizedAccountId: string }) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      try { socket.close(); } catch { /* already closed */ }
      if (error) reject(error);
      else if (result) resolve(result);
      else reject(new Error("cTrader demo verification returned no result."));
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
          finish(new Error(String(message.payload?.description || message.payload?.errorCode || "cTrader returned an API error.")));
          return;
        }
        if (stage === "app-auth" && message.payloadType === 2101) {
          stage = "account-list";
          send(2149, { accessToken });
          return;
        }
        if (stage === "account-list" && message.payloadType === 2150) {
          const payload = message.payload ?? {};
          permissionScope = Number(payload.permissionScope);
          if (permissionScope !== expectedScope) {
            finish(new Error(expectedScope === 1
              ? "cTrader did not confirm trading permission."
              : "cTrader did not confirm view-only permission."));
            return;
          }
          const raw = Array.isArray(payload.ctidTraderAccount) ? payload.ctidTraderAccount as Record<string, unknown>[] : [];
          demoAccounts = raw.filter(account => account.isLive === false);
          if (demoAccounts.length === 0) {
            finish(new Error("No demo account was found in the authorized account list."));
            return;
          }
          const accountId = Number(demoAccounts[0].ctidTraderAccountId);
          if (!Number.isSafeInteger(accountId) || accountId <= 0) {
            finish(new Error("cTrader returned an invalid demo account ID."));
            return;
          }
          stage = "account-auth";
          send(2102, { ctidTraderAccountId: accountId, accessToken });
          return;
        }
        if (stage === "account-auth" && message.payloadType === 2103) {
          finish(undefined, {
            permissionScope,
            accounts: demoAccounts,
            authorizedAccountId: String(message.payload?.ctidTraderAccountId ?? ""),
          });
        }
      } catch {
        finish(new Error("cTrader returned an unreadable account response."));
      }
    });
    socket.addEventListener("error", () => finish(new Error("Could not connect to cTrader demo Open API.")));
    socket.addEventListener("close", () => {
      if (!settled) finish(new Error("cTrader closed the connection before verification completed."));
    });
  });
}

export default async (request: Request) => {
  const headers = corsHeaders(request);
  const mode = new URL(request.url).searchParams.get("mode") === "trading" ? "trading" : "view-only";
  const expectedScope = mode === "trading" ? 1 : 0;
  const statusKey = mode === "trading" ? "account/trading-status" : "account/status";
  const tokenKey = mode === "trading" ? "account/trading-tokens" : "account/tokens";
  if (request.method === "OPTIONS") return new Response(null, { status: 204, headers });
  if (request.method !== "GET") return Response.json({ error: "METHOD_NOT_ALLOWED" }, { status: 405, headers });

  try {
    const store = getStore({ name: "dominion-ctrader-oauth-prod", consistency: "strong" });
    let saved = await store.get(statusKey, { type: "json" }) as {
      connected?: boolean;
      broker?: string;
      environment?: string;
      access?: string;
      demoAccountCount?: number;
      authorizedAccountId?: string;
      verifiedAt?: string;
    } | null;

    // Older successful authorizations stored encrypted tokens before the dashboard
    // status record existed. Verify those saved tokens once; never expose them.
    if (!saved) {
      const encrypted = await store.get(tokenKey, { type: "json" }) as {
        iv?: string; tag?: string; ciphertext?: string;
      } | null;
      if (!encrypted) {
        return Response.json({
          connected: false, broker: "Pepperstone", environment: null,
          access: null, demoAccountCount: 0, verifiedAt: null,
        }, { headers });
      }

      const key = Netlify.env.get("CTRADER_TOKEN_ENCRYPTION_KEY")?.trim();
      const clientId = Netlify.env.get("CTRADER_CLIENT_ID")?.trim();
      const clientSecret = Netlify.env.get("CTRADER_CLIENT_SECRET")?.trim();
      if (!key || !clientId || !clientSecret) throw new Error("Required cTrader verification configuration is missing.");

      const tokenData = decryptTokens(encrypted, key);
      if (typeof tokenData.accessToken !== "string") throw new Error("Saved cTrader access token is missing.");
      const verified = await verifyDemoAccounts(tokenData.accessToken, clientId, clientSecret, expectedScope);
      saved = {
        connected: verified.permissionScope === expectedScope && verified.accounts.length > 0 && Boolean(verified.authorizedAccountId),
        broker: "Pepperstone",
        environment: "demo",
        access: mode,
        demoAccountCount: verified.accounts.length,
        authorizedAccountId: verified.authorizedAccountId,
        verifiedAt: new Date().toISOString(),
      };
      await store.setJSON(statusKey, saved);
    }

    return Response.json({
      connected: saved.connected === true,
      broker: "Pepperstone",
      environment: saved.environment === "demo" ? "demo" : null,
      access: saved.access === "view-only" || saved.access === "trading" ? saved.access : null,
      demoAccountCount: Number.isInteger(saved.demoAccountCount) ? saved.demoAccountCount : 0,
      verifiedAt: typeof saved.verifiedAt === "string" ? saved.verifiedAt : null,
    }, { headers });
  } catch (error) {
    console.error("cTrader status verification failed", error instanceof Error ? error.message : "Unknown error");
    return Response.json({ error: "STATUS_VERIFICATION_FAILED" }, { status: 503, headers });
  }
};
