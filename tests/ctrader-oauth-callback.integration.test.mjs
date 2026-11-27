import test from "node:test";
import assert from "node:assert/strict";
import worker from "../src/worker.js";

class MockWebSocket {
  constructor(url) {
    assert.equal(url, "wss://demo.ctraderapi.com:5036");
    this.listeners = new Map();
    queueMicrotask(() => this.emit("open", {}));
  }
  addEventListener(type, callback) {
    const list = this.listeners.get(type) ?? [];
    list.push(callback);
    this.listeners.set(type, list);
  }
  emit(type, event) {
    for (const callback of this.listeners.get(type) ?? []) callback(event);
  }
  send(raw) {
    const request = JSON.parse(raw);
    let response = null;
    if (request.payloadType === 2100) response = { payloadType: 2101, payload: {} };
    if (request.payloadType === 2149) response = {
      payloadType: 2150,
      payload: {
        permissionScope: 1,
        ctidTraderAccount: [{ ctidTraderAccountId: 87654321, isLive: false }]
      }
    };
    if (request.payloadType === 2102) {
      assert.equal(request.payload.ctidTraderAccountId, 87654321);
      response = { payloadType: 2103, payload: { ctidTraderAccountId: 87654321 } };
    }
    if (response) queueMicrotask(() => this.emit("message", { data: JSON.stringify(response) }));
  }
  close() {}
}

test("OAuth callback consumes state, verifies demo trading access, encrypts tokens and never enables trading", async () => {
  const originalFetch = globalThis.fetch;
  const originalSocket = globalThis.WebSocket;
  const calls = [];
  const db = {
    prepare(sql) {
      return {
        bind(...values) {
          calls.push({ sql, values });
          return {
            async first() {
              if (sql.startsWith("UPDATE oauth_states")) {
                return { access_kind: "trading", expires_at: Math.floor(Date.now() / 1000) + 300 };
              }
              return null;
            },
            async run() { return { success: true, meta: { changes: 1 } }; }
          };
        }
      };
    }
  };
  globalThis.WebSocket = MockWebSocket;
  globalThis.fetch = async (url, options) => {
    assert.match(String(url), /^https:\/\/openapi\.ctrader\.com\/apps\/token\?/);
    assert.equal(options.method, "GET");
    return new Response(JSON.stringify({
      accessToken: "test-access-token",
      refreshToken: "test-refresh-token",
      tokenType: "Bearer",
      expiresIn: 3600
    }), { status: 200, headers: { "content-type": "application/json" } });
  };
  const encryptionKey = Buffer.alloc(32, 7).toString("base64");
  try {
    const response = await worker.fetch(
      new Request("https://desk.example/api/ctrader/oauth/callback?code=one-time-code&state=" + "A".repeat(43)),
      {
        CTRADER_DB: db,
        CTRADER_CLIENT_ID: "test-client",
        CTRADER_CLIENT_SECRET: "test-secret",
        CTRADER_REDIRECT_URI: "https://desk.example/api/ctrader/oauth/callback",
        CTRADER_TOKEN_ENCRYPTION_KEY: encryptionKey
      }
    );
    assert.equal(response.status, 200);
    assert.match(await response.text(), /demo-trading permission was verified/i);
    assert.match(response.headers.get("set-cookie"), /Max-Age=0/);
    const tokenWrite = calls.find((entry) => entry.sql.startsWith("INSERT INTO ctrader_tokens"));
    assert.ok(tokenWrite, "encrypted token row should be saved");
    assert.equal(tokenWrite.values[0], "trading");
    const encryptedRecord = JSON.parse(tokenWrite.values[1]);
    assert.equal(encryptedRecord.algorithm, "aes-256-gcm");
    assert.equal(JSON.stringify(encryptedRecord).includes("test-access-token"), false);
    assert.equal(JSON.stringify(encryptedRecord).includes("test-refresh-token"), false);
    const statusWrite = calls.find((entry) => entry.sql.startsWith("INSERT INTO engine_status"));
    assert.ok(statusWrite, "safe demo status should be saved");
    const status = JSON.parse(statusWrite.values[0]);
    assert.equal(status.connected, true);
    assert.equal(status.isLive, false);
    assert.equal(status.liveTradingEnabled, false);
    assert.equal(calls.some((entry) => /INSERT INTO oauth_states/.test(entry.sql)), false);
  } finally {
    globalThis.fetch = originalFetch;
    globalThis.WebSocket = originalSocket;
  }
});

test("OAuth callback rejects missing browser state before token exchange", async () => {
  const originalFetch = globalThis.fetch;
  let tokenRequestMade = false;
  globalThis.fetch = async () => {
    tokenRequestMade = true;
    throw new Error("Unexpected token request");
  };
  try {
    const response = await worker.fetch(
      new Request("https://desk.example/api/ctrader/oauth/callback?code=one-time-code"),
      { CTRADER_DB: { prepare() { throw new Error("Should not access D1"); } } }
    );
    assert.equal(response.status, 400);
    assert.equal(tokenRequestMade, false);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
