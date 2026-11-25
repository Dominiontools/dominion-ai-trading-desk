import { getStore } from "@netlify/blobs";
import { createHmac, randomUUID, timingSafeEqual } from "node:crypto";
import { executeCycle } from "./ctrader-engine-cycle.mts";

type RecordData = Record<string, unknown>;

function number(value: unknown): number {
  return Number(value);
}

function response(status: number, body: RecordData): Response {
  return Response.json(body, {
    status,
    headers: { "cache-control": "no-store", "x-content-type-options": "nosniff" },
  });
}

export default async (request: Request) => {
  if (request.method !== "POST") return response(405, { error: "METHOD_NOT_ALLOWED" });
  const secret = Netlify.env.get("DOMINION_CONTROL_API_SECRET")?.trim();
  if (!secret) return response(503, { error: "CONTROL_SECRET_NOT_CONFIGURED" });

  const timestampText = request.headers.get("x-dominion-timestamp") ?? "";
  const nonce = request.headers.get("x-dominion-nonce") ?? "";
  const suppliedSignature = request.headers.get("x-dominion-signature") ?? "";
  const timestamp = Number(timestampText);
  if (!Number.isFinite(timestamp) || Math.abs(Date.now() - timestamp) > 60_000 ||
      !/^[0-9a-f-]{36}$/i.test(nonce) || !/^[0-9a-f]{64}$/i.test(suppliedSignature)) {
    return response(401, { error: "INVALID_WORKER_AUTHENTICATION" });
  }

  const rawBody = await request.text();
  if (rawBody.length > 4096) return response(413, { error: "WORKER_BODY_TOO_LARGE" });
  const expected = createHmac("sha256", secret)
    .update(`${timestampText}.${nonce}.${rawBody}`)
    .digest();
  const supplied = Buffer.from(suppliedSignature, "hex");
  if (supplied.length !== expected.length || !timingSafeEqual(supplied, expected)) {
    return response(401, { error: "INVALID_WORKER_SIGNATURE" });
  }

  let payload: RecordData;
  try {
    payload = JSON.parse(rawBody) as RecordData;
  } catch {
    return response(400, { error: "INVALID_JSON" });
  }
  if (payload.trigger !== "scheduled" || String(payload.timestamp ?? "") !== timestampText) {
    return response(400, { error: "INVALID_SCHEDULED_TRIGGER" });
  }

  const store = getStore({ name: "dominion-ctrader-oauth-prod", consistency: "strong" });
  try {
    await store.setJSON(`account/worker-nonces/${nonce}`, {
      acceptedAt: Date.now(),
      expiresAt: Date.now() + 120_000,
    }, { onlyIfNew: true });
  } catch {
    return response(409, { error: "WORKER_REQUEST_REPLAYED" });
  }

  const now = Date.now();
  const lockId = randomUUID();
  const lockKey = "account/engine-lock";
  let acquired = false;
  try {
    const existing = await store.get(lockKey, { type: "json" }) as RecordData | null;
    if (existing && number(existing.expiresAt) > now) {
      console.log("cTrader engine cycle skipped; another worker owns the lock.");
      return response(202, { status: "SKIPPED_LOCKED", mode: "DEMO_ONLY" });
    }
    if (existing) await store.delete(lockKey);
    try {
      await store.setJSON(lockKey, {
        id: lockId,
        expiresAt: now + 16 * 60 * 1000,
      }, { onlyIfNew: true });
      acquired = true;
    } catch {
      return response(202, { status: "SKIPPED_LOCKED", mode: "DEMO_ONLY" });
    }

    const result = await executeCycle();
    console.log("cTrader background cycle completed.", {
      status: String(result.status ?? "UNKNOWN"),
      reason: String(result.reason ?? ""),
      mode: "DEMO_ONLY",
    });
    return response(202, { status: String(result.status ?? "COMPLETED"), mode: "DEMO_ONLY" });
  } catch (error) {
    const reason = error instanceof Error ? error.message : "UNKNOWN_ENGINE_ERROR";
    const failed = {
      status: "BLOCKED",
      reason,
      mode: "DEMO_ONLY",
      liveTradingEnabled: false,
      updatedAt: new Date().toISOString(),
      environment: "demo",
    };
    await store.setJSON("account/engine-status", failed);
    const previous = await store.get("account/engine-events", { type: "json" }) as RecordData[] | null;
    const events = Array.isArray(previous) ? previous : [];
    events.push({ ...failed, recordedAt: new Date().toISOString() });
    await store.setJSON("account/engine-events", events.slice(-200));
    console.error("cTrader background cycle failed.", { reason });
    return response(202, { status: "BLOCKED", mode: "DEMO_ONLY" });
  } finally {
    if (acquired) {
      const current = await store.get(lockKey, { type: "json" }) as RecordData | null;
      if (current?.id === lockId) await store.delete(lockKey);
    }
  }
};

export const config = { background: true };
