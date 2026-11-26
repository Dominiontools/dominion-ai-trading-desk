import { createHmac, randomUUID } from "node:crypto";

const BACKEND_ORIGIN = "https://dominion-ai-trading-desk-p7cp.netlify.app";

export default async () => {
  const secret = Netlify.env.get("DOMINION_CONTROL_API_SECRET")?.trim();
  if (!secret) {
    console.error("cTrader scheduler is missing DOMINION_CONTROL_API_SECRET.");
    return Response.json({ status: "BLOCKED", reason: "CONTROL_SECRET_NOT_CONFIGURED" }, { status: 503 });
  }

  const timestamp = Date.now().toString();
  const nonce = randomUUID();
  const body = JSON.stringify({ trigger: "scheduled", timestamp });
  const signature = createHmac("sha256", secret)
    .update(`${timestamp}.${nonce}.${body}`)
    .digest("hex");

  try {
    const worker = await fetch(
      `${BACKEND_ORIGIN}/.netlify/functions/ctrader-engine-worker`,
      {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "x-dominion-timestamp": timestamp,
          "x-dominion-nonce": nonce,
          "x-dominion-signature": signature,
        },
        body,
      },
    );
    const result = await worker.json().catch(() => ({ error: "INVALID_WORKER_RESPONSE" }));
    if (!worker.ok) {
      console.error("cTrader scheduled worker rejected its trigger.", {
        status: worker.status,
        result,
      });
      return Response.json({
        status: "WORKER_REJECTED",
        workerStatus: worker.status,
        result,
      }, { status: 502 });
    }
    return Response.json({ status: "WORKER_ACCEPTED", result });
  } catch (error) {
    const reason = error instanceof Error ? error.message : "SCHEDULER_REQUEST_FAILED";
    console.error("cTrader scheduled worker could not be reached.", { reason });
    return Response.json({ status: "WORKER_UNREACHABLE", reason }, { status: 502 });
  }
};

export const config = {
  schedule: "* * * * *",
};
