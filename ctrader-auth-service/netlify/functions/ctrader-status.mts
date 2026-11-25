import { getStore } from "@netlify/blobs";

const ALLOWED_ORIGINS = new Set([
  "https://dominion-ai-trading-desk-r30v.netlify.app",
  "https://feat-ctrader-auth-service--dominion-ai-trading-desk-r30v.netlify.app",
]);

export default async (request: Request) => {
  const origin = request.headers.get("origin") ?? "";
  if (!ALLOWED_ORIGINS.has(origin)) {
    return Response.json({ error: "ORIGIN_NOT_ALLOWED" }, {
      status: 403,
      headers: { "cache-control": "no-store", "x-content-type-options": "nosniff" },
    });
  }

  const headers = {
    "access-control-allow-origin": origin,
    "vary": "Origin",
    "cache-control": "no-store",
    "content-type": "application/json; charset=utf-8",
    "x-content-type-options": "nosniff",
  };

  if (request.method === "OPTIONS") {
    return new Response(null, {
      status: 204,
      headers: { ...headers, "access-control-allow-methods": "GET, OPTIONS", "access-control-max-age": "600" },
    });
  }
  if (request.method !== "GET") {
    return Response.json({ error: "METHOD_NOT_ALLOWED" }, { status: 405, headers });
  }

  try {
    const store = getStore({ name: "dominion-ctrader-oauth-prod", consistency: "strong" });
    const saved = await store.get("account/status", { type: "json" }) as {
      connected?: boolean;
      broker?: string;
      environment?: string;
      access?: string;
      demoAccountCount?: number;
      verifiedAt?: string;
    } | null;

    return Response.json({
      connected: saved?.connected === true,
      broker: saved?.broker === "Pepperstone" ? saved.broker : "Pepperstone",
      environment: saved?.environment === "demo" ? "demo" : null,
      access: saved?.access === "view-only" ? "view-only" : null,
      demoAccountCount: Number.isInteger(saved?.demoAccountCount) ? saved?.demoAccountCount : 0,
      verifiedAt: typeof saved?.verifiedAt === "string" ? saved.verifiedAt : null,
    }, { headers });
  } catch {
    return Response.json({ error: "STATUS_UNAVAILABLE" }, { status: 503, headers });
  }
};
