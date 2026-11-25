import { createHmac, randomUUID } from "node:crypto";

const BACKEND_CONTROL_URL = "https://dominion-ai-trading-desk-p7cp.netlify.app/.netlify/functions/ctrader-engine-control";
const DASHBOARD_ORIGIN = "https://dominion-ai-trading-desk-new.netlify.app";

export default async (request: Request, context: { user?: unknown }) => {
  if (request.method !== "POST") {
    return Response.json({ error: "METHOD_NOT_ALLOWED" }, { status: 405 });
  }
  if (!context.user) {
    return Response.json({ error: "NETLIFY_TEAM_LOGIN_REQUIRED" }, { status: 401 });
  }
  const origin = request.headers.get("origin");
  if (origin !== DASHBOARD_ORIGIN) {
    return Response.json({ error: "UNAPPROVED_DASHBOARD_ORIGIN" }, { status: 403 });
  }
  const secret = Netlify.env.get("DOMINION_CONTROL_API_SECRET")?.trim();
  if (!secret) {
    return Response.json({ error: "CONTROL_SECRET_NOT_CONFIGURED" }, { status: 503 });
  }

  const rawBody = await request.text();
  if (rawBody.length > 16_384) {
    return Response.json({ error: "CONTROL_BODY_TOO_LARGE" }, { status: 413 });
  }
  const timestamp = Date.now().toString();
  const nonce = randomUUID();
  const signature = createHmac("sha256", secret)
    .update(`${timestamp}.${nonce}.${rawBody}`)
    .digest("hex");

  try {
    const response = await fetch(BACKEND_CONTROL_URL, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-dominion-timestamp": timestamp,
        "x-dominion-nonce": nonce,
        "x-dominion-signature": signature,
      },
      body: rawBody,
    });
    const result = await response.json().catch(() => ({ error: "INVALID_BACKEND_RESPONSE" }));
    return Response.json(result, {
      status: response.status,
      headers: { "cache-control": "no-store" },
    });
  } catch {
    return Response.json({ error: "TRADING_BACKEND_UNAVAILABLE" }, { status: 502 });
  }
};
