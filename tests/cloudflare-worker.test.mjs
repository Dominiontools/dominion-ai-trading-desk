import test from "node:test";
import assert from "node:assert/strict";
import worker from "../src/worker.js";

const env = {
  ASSETS: {
    fetch: async (request) => new Response(`asset:${new URL(request.url).pathname}`, {
      headers: { "content-type": "text/plain" },
    }),
  },
};

test("health endpoint reports service identity and keeps trading disabled", async () => {
  const response = await worker.fetch(new Request("https://desk.example/api/health"), env);
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("cache-control"), "no-store");
  assert.deepEqual(await response.json(), {
    ok: true,
    service: "dominion-ai-trading-desk",
    runtime: "cloudflare-workers",
    stage: "backend-migration-scaffold",
    trading_enabled: false,
    live_trading_enabled: false,
  });
});

test("health endpoint rejects non-GET requests", async () => {
  const response = await worker.fetch(new Request("https://desk.example/api/health", {
    method: "POST",
  }), env);
  assert.equal(response.status, 405);
});

test("unmigrated cTrader routes fail closed without broker actions", async () => {
  const response = await worker.fetch(new Request("https://desk.example/api/ctrader/status"), env);
  assert.equal(response.status, 503);
  const body = await response.json();
  assert.equal(body.status, "not_migrated");
  assert.equal(body.trading_enabled, false);
});

test("crypto routes do not pretend the phone engine is connected", async () => {
  const response = await worker.fetch(new Request("https://desk.example/api/crypto/status"), env);
  assert.equal(response.status, 503);
  const body = await response.json();
  assert.equal(body.status, "phone_engine_required");
  assert.equal(body.trading_enabled, false);
});

test("unknown API routes return JSON 404", async () => {
  const response = await worker.fetch(new Request("https://desk.example/api/unknown"), env);
  assert.equal(response.status, 404);
  assert.deepEqual(await response.json(), { ok: false, error: "not_found" });
});

test("non-API requests are passed to the static asset binding", async () => {
  const response = await worker.fetch(new Request("https://desk.example/dashboard"), env);
  assert.equal(response.status, 200);
  assert.equal(await response.text(), "asset:/dashboard");
});
