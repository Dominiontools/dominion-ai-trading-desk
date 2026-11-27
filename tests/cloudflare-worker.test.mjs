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

test("cTrader status endpoint is read-only and requires its D1 binding", async () => {
  const missing = await worker.fetch(new Request("https://desk.example/api/ctrader/status"), env);
  assert.equal(missing.status, 503);
  assert.equal((await missing.json()).error, "ctrader_storage_unavailable");

  const wrongMethod = await worker.fetch(new Request("https://desk.example/api/ctrader/status", {
    method: "POST"
  }), { ...env, CTRADER_DB: {} });
  assert.equal(wrongMethod.status, 405);
});

test("cTrader status endpoint returns safe disconnected defaults from D1", async () => {
  const db = {
    prepare() {
      return {
        async first() { return null; }
      };
    }
  };
  const response = await worker.fetch(
    new Request("https://desk.example/api/ctrader/status"),
    { ...env, CTRADER_DB: db }
  );
  assert.equal(response.status, 200);
  const body = await response.json();
  assert.equal(body.ok, true);
  assert.equal(body.status.connected, false);
  assert.equal(body.status.environment, "demo");
  assert.equal(body.trading_enabled, false);
  assert.equal(body.live_trading_enabled, false);
  assert.equal(body.config, null);
});

test("unmigrated cTrader routes fail closed without broker actions", async () => {
  const response = await worker.fetch(new Request("https://desk.example/api/ctrader/engine-control"), env);
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


test("cTrader OAuth start creates one-time state and redirects with trading scope", async () => {
  let inserted;
  const db = {
    prepare(sql) {
      return {
        bind(...values) {
          inserted = { sql, values };
          return { async run() { return { success: true }; } };
        }
      };
    }
  };
  const response = await worker.fetch(
    new Request("https://desk.example/api/ctrader/oauth/start?mode=trading"),
    { ...env, CTRADER_DB: db, CTRADER_CLIENT_ID: "client-123",
      CTRADER_REDIRECT_URI: "https://desk.example/api/ctrader/oauth/callback" }
  );
  assert.equal(response.status, 302);
  assert.match(response.headers.get("location"), /scope=trading/);
  assert.match(response.headers.get("location"), /state=[A-Za-z0-9_-]{43}/);
  assert.match(response.headers.get("cache-control"), /no-store/);
  assert.match(response.headers.get("set-cookie"), /HttpOnly; Secure; SameSite=None/);
  assert.ok(response.headers.get("set-cookie").includes("Path=/api/ctrader/oauth/callback"));
  assert.match(inserted.sql, /INSERT INTO oauth_states/);
  assert.equal(inserted.values[3], "trading");
});

test("cTrader OAuth start rejects invalid modes and missing configuration", async () => {
  const db = { prepare() { return { bind() { return { async run() {} }; } }; } };
  const invalid = await worker.fetch(
    new Request("https://desk.example/api/ctrader/oauth/start?mode=live"),
    { ...env, CTRADER_DB: db, CTRADER_CLIENT_ID: "client",
      CTRADER_REDIRECT_URI: "https://desk.example/api/ctrader/oauth/callback" }
  );
  assert.equal(invalid.status, 400);
  assert.equal((await invalid.json()).error, "invalid_access_mode");

  const missing = await worker.fetch(
    new Request("https://desk.example/api/ctrader/oauth/start"),
    { ...env, CTRADER_DB: db }
  );
  assert.equal(missing.status, 503);
  assert.equal((await missing.json()).error, "ctrader_oauth_not_configured");
});


test("cTrader OAuth callback rejects missing setup and incomplete authorization", async () => {
  const missingStorage = await worker.fetch(
    new Request("https://desk.example/api/ctrader/oauth/callback?code=abc&state=abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMN"),
    env
  );
  assert.equal(missingStorage.status, 503);

  const noCode = await worker.fetch(
    new Request("https://desk.example/api/ctrader/oauth/callback"),
    { ...env, CTRADER_DB: {} }
  );
  assert.equal(noCode.status, 400);

  const wrongMethod = await worker.fetch(
    new Request("https://desk.example/api/ctrader/oauth/callback", { method: "POST" }),
    { ...env, CTRADER_DB: {} }
  );
  assert.equal(wrongMethod.status, 405);
});


test("cTrader OAuth callback accepts the secure browser cookie when provider omits state", async () => {
  const db = {
    prepare(sql) {
      return {
        bind() { return this; },
        async first() { return null; },
        async run() { return { success: true }; }
      };
    }
  };
  const response = await worker.fetch(
    new Request("https://desk.example/api/ctrader/oauth/callback?code=auth-code", {
      headers: { cookie: "dominion_ctrader_oauth_state=" + "s".repeat(43) }
    }),
    { ...env, CTRADER_DB: db, CTRADER_CLIENT_ID: "client",
      CTRADER_CLIENT_SECRET: "secret",
      CTRADER_REDIRECT_URI: "https://desk.example/api/ctrader/oauth/callback",
      CTRADER_TOKEN_ENCRYPTION_KEY: "a".repeat(44) }
  );
  assert.equal(response.status, 400);
  assert.match(response.headers.get("set-cookie"), /Max-Age=0/);
  assert.match(await response.text(), /session expired/i);
});
