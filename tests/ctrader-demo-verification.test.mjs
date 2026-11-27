import test from "node:test";
import assert from "node:assert/strict";
import { verifyCTraderDemoAccount } from "../src/cloudflare/ctrader-demo-verification.js";

class MockWebSocket {
  static responder;
  constructor(url) {
    this.url = url;
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
    const response = MockWebSocket.responder(request);
    if (response) queueMicrotask(() => this.emit("message", { data: JSON.stringify(response) }));
  }
  close() { this.closed = true; }
}

async function withSocket(responder, callback) {
  const original = globalThis.WebSocket;
  MockWebSocket.responder = responder;
  globalThis.WebSocket = MockWebSocket;
  try { await callback(); }
  finally { globalThis.WebSocket = original; }
}

const input = {
  accessToken: "access-token",
  clientId: "client-id",
  clientSecret: "client-secret",
  expectedScope: 1,
  timeoutMs: 500
};

test("demo verification authenticates a demo account with the requested trading scope", async () => {
  await withSocket((request) => {
    if (request.payloadType === 2100) return { payloadType: 2101, payload: {} };
    if (request.payloadType === 2149) return {
      payloadType: 2150,
      payload: {
        permissionScope: 1,
        ctidTraderAccount: [
          { ctidTraderAccountId: 12345, isLive: true },
          { ctidTraderAccountId: 67890, isLive: false }
        ]
      }
    };
    if (request.payloadType === 2102) {
      assert.equal(request.payload.ctidTraderAccountId, 67890);
      assert.equal(typeof request.payload.ctidTraderAccountId, "number");
      return { payloadType: 2103, payload: { ctidTraderAccountId: 67890 } };
    }
    return null;
  }, async () => {
    const result = await verifyCTraderDemoAccount(input);
    assert.deepEqual(result, {
      permissionScope: 1,
      demoAccountCount: 1,
      authorizedAccountId: "67890"
    });
  });
});

test("demo verification rejects a permission scope mismatch", async () => {
  await withSocket((request) => {
    if (request.payloadType === 2100) return { payloadType: 2101 };
    if (request.payloadType === 2149) return {
      payloadType: 2150,
      payload: { permissionScope: 0, ctidTraderAccount: [{ ctidTraderAccountId: 123, isLive: false }] }
    };
    return null;
  }, async () => {
    await assert.rejects(verifyCTraderDemoAccount(input), /permission scope/);
  });
});

test("demo verification rejects an account-auth response for a different account", async () => {
  await withSocket((request) => {
    if (request.payloadType === 2100) return { payloadType: 2101 };
    if (request.payloadType === 2149) return {
      payloadType: 2150,
      payload: { permissionScope: 1, ctidTraderAccount: [{ ctidTraderAccountId: 456, isLive: false }] }
    };
    if (request.payloadType === 2102) return { payloadType: 2103, payload: { ctidTraderAccountId: 999 } };
    return null;
  }, async () => {
    await assert.rejects(verifyCTraderDemoAccount(input), /different account/);
  });
});

test("demo verification rejects live-only account lists", async () => {
  await withSocket((request) => {
    if (request.payloadType === 2100) return { payloadType: 2101 };
    if (request.payloadType === 2149) return {
      payloadType: 2150,
      payload: { permissionScope: 1, ctidTraderAccount: [{ ctidTraderAccountId: 456, isLive: true }] }
    };
    return null;
  }, async () => {
    await assert.rejects(verifyCTraderDemoAccount(input), /No cTrader demo account/);
  });
});
