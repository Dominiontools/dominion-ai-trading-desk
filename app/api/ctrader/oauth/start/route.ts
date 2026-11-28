import { createOAuthState } from "../../../../../src/cloudflare/ctrader-d1-store.js";
import { buildCTraderAuthorizationUrl } from "../../../../../src/cloudflare/ctrader-oauth.js";
import { getCTraderRuntimeEnv } from "../../../../../src/cloudflare/next-runtime";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const COOKIE_NAME = "dominion_ctrader_oauth_state";
const COOKIE_PATH = "/api/ctrader/oauth/callback";

function makeState(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

export async function GET(request: Request) {
  const url = new URL(request.url);
  const env = getCTraderRuntimeEnv();
  if (!env.CTRADER_DB) {
    return Response.json({ ok: false, error: "ctrader_storage_unavailable" }, { status: 503 });
  }

  const accessKind = url.searchParams.get("mode") ?? "view-only";
  if (accessKind !== "view-only" && accessKind !== "trading") {
    return Response.json({ ok: false, error: "invalid_access_mode" }, { status: 400 });
  }

  const clientId = env.CTRADER_CLIENT_ID?.trim() ?? "";
  const redirectUri = env.CTRADER_REDIRECT_URI?.trim() ?? "";
  if (!clientId || !redirectUri) {
    return Response.json({ ok: false, error: "ctrader_oauth_not_configured" }, { status: 503 });
  }

  try {
    const state = makeState();
    await createOAuthState(env.CTRADER_DB, state, accessKind);
    const authorizationUrl = buildCTraderAuthorizationUrl({
      clientId,
      redirectUri,
      requestOrigin: url.origin,
      accessKind,
      state
    });
    return new Response(null, {
      status: 302,
      headers: {
        location: authorizationUrl,
        "cache-control": "no-store",
        "referrer-policy": "no-referrer",
        "set-cookie": `${COOKIE_NAME}=${state}; Max-Age=600; Path=${COOKIE_PATH}; HttpOnly; Secure; SameSite=None`,
        "x-content-type-options": "nosniff"
      }
    });
  } catch {
    return Response.json({ ok: false, error: "ctrader_oauth_start_failed" }, { status: 503 });
  }
}
