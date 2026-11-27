import test from "node:test";
import assert from "node:assert/strict";
import { CTraderDemoSession, trendbarsToCandles } from "../src/cloudflare/ctrader-demo-session.js";

class MockWebSocket {
  static OPEN = 1;
  static instances = [];
  constructor(url) {
    this.url = url;
    this.readyState = 1;
    this.listeners = new Map();
    this.sent = [];
    MockWebSocket.instances.push(this);
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
    this.sent.push(JSON.parse(raw));
    const request = JSON.parse(raw);
    const payloads = {
      2100: [2101, {}],
      2149: [2150, {
        permissionScope: 1,
        ctidTraderAccount: [
          { ctidTraderAccountId: 123, isLive: true },
          { ctidTraderAccountId: 456, isLive: false }
        ]
      }],
      2102: [2103, { ctidTraderAccountId: 456 }],
      2114: [2115, { symbol: [{ symbolId: 10, symbolName: "EURUSD" }] }],
      2116: [2117, { symbol: [{ symbolId: 10, digits: 5 }] }],
      2124: [2125, { position: [], order: [] }],
      2106: [2126, { executionType: 3, position: { positionId: 88 } }]
    };
    const pair = payloads[request.payloadType];
    if (pair) queueMicrotask(() => this.emit("message", {
      data: JSON.stringify({ clientMsgId: request.clientMsgId, payloadType: pair[0], payload: pair[1] })
    }));
  }
  close() {
    this.readyState = 3;
    this.emit("close", {});
  }
}

async function withWebSocket(callback) {
  const original = globalThis.WebSocket;
  globalThis.WebSocket = MockWebSocket;
  try { await callback(); }
  finally { globalThis.WebSocket = original; }
}

test("session connects to demo endpoint and authorizes only the selected demo account", async () => {
  await withWebSocket(async () => {
    const session = new CTraderDemoSession();
    await session.connect();
    assert.equal(session.socket.url, "wss://demo.ctraderapi.com:5036");
    await session.authorize("access", "456", "client", "secret");
    assert.equal(session.requireAccount(), 456);
    session.sendHeartbeat();
    assert.equal(MockWebSocket.instances.at(-1).sent.at(-1).payloadType, 51);
    const symbols = await session.symbols();
    assert.equal(symbols[0].symbolName, "EURUSD");
    const details = await session.symbolDetails(10);
    assert.equal(details.digits, 5);
    const snapshot = await session.reconcile();
    assert.deepEqual(snapshot, { positions: [], orders: [] });
    const order = await session.newMarketRangeOrder({
      symbolId: 10, side: "BUY", volume: 1000, entryPrice: 1.1,
      stopLoss: 1.09, takeProfit: 1.12, slippageInPoints: 2, clientOrderId: "demo-order-1"
    });
    assert.equal(order.executionType, 3);
    await session.close();
    assert.equal(session.socket, null);
  });
});

test("session refuses account operations before demo authorization", async () => {
  await withWebSocket(async () => {
    const session = new CTraderDemoSession();
    await session.connect();
    assert.throws(() => session.requireAccount(), /NOT_AUTHORIZED/);
    await session.close();
  });
});

test("session rejects live account IDs and malformed account IDs", async () => {
  await withWebSocket(async () => {
    const session = new CTraderDemoSession();
    await session.connect();
    await assert.rejects(session.authorize("access", "123", "client", "secret"), /NOT_FOUND/);
    await assert.rejects(session.authorize("access", "not-an-id", "client", "secret"), /ACCOUNT_ID_MISSING/);
    await session.close();
  });
});

test("trendbar conversion removes incomplete candles and sorts valid history", () => {
  const now = Date.UTC(2026, 0, 1, 1, 0, 0);
  const bars = [
    { utcTimestampInMinutes: Date.UTC(2026, 0, 1, 0, 30) / 60_000, low: 100_000, deltaOpen: 100, deltaHigh: 300, deltaClose: 200, volume: 5 },
    { utcTimestampInMinutes: Date.UTC(2026, 0, 1, 0, 0) / 60_000, low: 99_000, deltaOpen: 100, deltaHigh: 300, deltaClose: 200, volume: 4 },
    { utcTimestampInMinutes: Date.UTC(2026, 0, 1, 1, 0) / 60_000, low: 101_000, deltaOpen: 100, deltaHigh: 300, deltaClose: 200, volume: 6 }
  ];
  const candles = trendbarsToCandles("EURUSD", "FOREX", "30m", bars, 1800, now);
  assert.equal(candles.length, 2);
  assert.ok(candles[0].timestamp < candles[1].timestamp);
  assert.equal(candles[1].close, 1.002);
});
