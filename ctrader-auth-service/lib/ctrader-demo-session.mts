import { getStore } from "@netlify/blobs";
import { createCipheriv, createDecipheriv, randomBytes } from "node:crypto";

type JsonRecord = Record<string, unknown>;
type CTraderMessage = {
  clientMsgId?: string;
  payloadType?: number;
  payload?: JsonRecord;
};
type Pending = {
  expectedPayloadType: number;
  resolve: (payload: JsonRecord) => void;
  reject: (error: Error) => void;
  predicate?: (payload: JsonRecord) => boolean;
  timer: ReturnType<typeof setTimeout>;
};
type EventWaiter = {
  payloadType: number;
  predicate: (payload: JsonRecord) => boolean;
  resolve: (payload: JsonRecord) => void;
  reject: (error: Error) => void;
  timer: ReturnType<typeof setTimeout>;
};

const STORE_NAME = "dominion-ctrader-oauth-prod";
const TOKEN_URL = "https://openapi.ctrader.com/apps/token";
const DEMO_WS_URL = "wss://demo.ctraderapi.com:5036";

function requiredEnv(name: string): string {
  const value = Netlify.env.get(name)?.trim();
  if (!value) throw new Error(`MISSING_ENV:${name}`);
  return value;
}

function decryptTokens(payload: JsonRecord, keyText: string): JsonRecord {
  const key = Buffer.from(keyText, "base64");
  if (key.length !== 32) throw new Error("INVALID_TOKEN_ENCRYPTION_KEY");
  if (payload.algorithm !== "aes-256-gcm" || payload.version !== 1) {
    throw new Error("UNSUPPORTED_ENCRYPTED_TOKEN_FORMAT");
  }
  const decipher = createDecipheriv(
    "aes-256-gcm",
    key,
    Buffer.from(String(payload.iv ?? ""), "base64"),
  );
  decipher.setAuthTag(Buffer.from(String(payload.tag ?? ""), "base64"));
  const plaintext = Buffer.concat([
    decipher.update(Buffer.from(String(payload.ciphertext ?? ""), "base64")),
    decipher.final(),
  ]);
  return JSON.parse(plaintext.toString("utf8")) as JsonRecord;
}

function encryptTokens(payload: JsonRecord, keyText: string): JsonRecord {
  const key = Buffer.from(keyText, "base64");
  if (key.length !== 32) throw new Error("INVALID_TOKEN_ENCRYPTION_KEY");
  const iv = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", key, iv);
  const ciphertext = Buffer.concat([
    cipher.update(JSON.stringify(payload), "utf8"),
    cipher.final(),
  ]);
  return {
    version: 1,
    algorithm: "aes-256-gcm",
    iv: iv.toString("base64"),
    tag: cipher.getAuthTag().toString("base64"),
    ciphertext: ciphertext.toString("base64"),
    savedAt: new Date().toISOString(),
  };
}

export async function loadTradingCredentials(): Promise<{
  accessToken: string;
  authorizedAccountId: string;
  clientId: string;
  clientSecret: string;
}> {
  const store = getStore({ name: STORE_NAME, consistency: "strong" });
  const [encrypted, status] = await Promise.all([
    store.get("account/trading-tokens", { type: "json" }) as Promise<JsonRecord | null>,
    store.get("account/trading-status", { type: "json" }) as Promise<JsonRecord | null>,
  ]);
  if (!encrypted || !status || status.connected !== true ||
      status.environment !== "demo" || status.access !== "trading" ||
      Number(status.permissionScope) !== 1) {
    throw new Error("TRADING_AUTH_REQUIRED");
  }
  const keyText = requiredEnv("CTRADER_TOKEN_ENCRYPTION_KEY");
  const clientId = requiredEnv("CTRADER_CLIENT_ID");
  const clientSecret = requiredEnv("CTRADER_CLIENT_SECRET");
  let tokenData = decryptTokens(encrypted, keyText);
  let accessToken = String(tokenData.accessToken ?? "");
  if (!accessToken) throw new Error("TRADING_ACCESS_TOKEN_MISSING");

  const expiresIn = Number(tokenData.expiresIn ?? 0);
  const issuedAt = Number(tokenData.issuedAt ?? 0);
  const refreshToken = String(tokenData.refreshToken ?? "");
  const refreshDue = expiresIn > 0 && issuedAt > 0 &&
    Date.now() >= issuedAt + Math.max(0, expiresIn - 300) * 1000;

  if (refreshDue) {
    if (!refreshToken) throw new Error("TRADING_REFRESH_TOKEN_MISSING");
    const body = new URLSearchParams({
      grant_type: "refresh_token",
      refresh_token: refreshToken,
      client_id: clientId,
      client_secret: clientSecret,
    });
    const response = await fetch(TOKEN_URL, {
      method: "POST",
      headers: { "content-type": "application/x-www-form-urlencoded" },
      body,
    });
    const refreshed = await response.json() as JsonRecord;
    if (!response.ok || typeof refreshed.accessToken !== "string" ||
        typeof refreshed.refreshToken !== "string") {
      throw new Error("CTRADER_TOKEN_REFRESH_FAILED");
    }
    tokenData = { ...refreshed, issuedAt: Date.now() };
    await store.setJSON("account/trading-tokens", encryptTokens(tokenData, keyText));
    accessToken = String(tokenData.accessToken);
  }

  const authorizedAccountId = String(status.authorizedAccountId ?? "");
  if (!/^\d+$/.test(authorizedAccountId)) throw new Error("DEMO_ACCOUNT_ID_MISSING");
  return { accessToken, authorizedAccountId, clientId, clientSecret };
}

export class CTraderDemoSession {
  private socket: WebSocket | null = null;
  private readonly pending = new Map<string, Pending>();
  private readonly eventWaiters = new Set<EventWaiter>();
  private accountId = "";

  async connect(): Promise<void> {
    if (this.socket) throw new Error("CTRADER_SESSION_ALREADY_CONNECTED");
    await new Promise<void>((resolve, reject) => {
      const socket = new WebSocket(DEMO_WS_URL);
      this.socket = socket;
      const timer = setTimeout(() => {
        try { socket.close(); } catch { /* close may already be in progress */ }
        reject(new Error("CTRADER_WEBSOCKET_CONNECT_TIMEOUT"));
      }, 10000);
      socket.addEventListener("open", () => {
        clearTimeout(timer);
        resolve();
      }, { once: true });
      socket.addEventListener("error", () => {
        clearTimeout(timer);
        reject(new Error("CTRADER_WEBSOCKET_CONNECT_FAILED"));
      }, { once: true });
      socket.addEventListener("message", (event) => this.onMessage(event.data));
      socket.addEventListener("close", () => {
        this.failAll(new Error("CTRADER_WEBSOCKET_CLOSED"));
        this.socket = null;
      });
    });
  }

  private onMessage(data: unknown): void {
    let message: CTraderMessage;
    try {
      const raw = typeof data === "string"
        ? data
        : Buffer.isBuffer(data) ? data.toString("utf8") : String(data);
      message = JSON.parse(raw) as CTraderMessage;
    } catch {
      this.failAll(new Error("CTRADER_INVALID_MESSAGE"));
      return;
    }
    const payload = message.payload ?? {};
    const payloadType = Number(message.payloadType ?? 0);
    const clientMsgId = typeof message.clientMsgId === "string" ? message.clientMsgId : "";
    const pending = clientMsgId
      ? this.pending.get(clientMsgId)
      : [...this.pending.entries()].find(([, item]) => item.expectedPayloadType === payloadType)?.[1];

    if (payloadType === 2142) {
      const error = new Error(String(payload.description ?? payload.errorCode ?? "CTRADER_API_ERROR"));
      if (pending) this.rejectPending(clientMsgId, pending, error);
      else this.failAll(error);
      return;
    }
    if (payloadType === 2132) {
      const error = new Error(String(payload.description ?? payload.errorCode ?? "CTRADER_ORDER_ERROR"));
      this.failAll(error);
      return;
    }

    if (pending && pending.expectedPayloadType === payloadType) {
      try {
        if (!pending.predicate || pending.predicate(payload)) {
          clearTimeout(pending.timer);
          const key = clientMsgId || [...this.pending.entries()].find(([, item]) => item === pending)?.[0];
          if (key) this.pending.delete(key);
          pending.resolve(payload);
        }
      } catch (error) {
        this.rejectPending(clientMsgId, pending, error instanceof Error ? error : new Error("CTRADER_REQUEST_REJECTED"));
      }
    }

    for (const waiter of [...this.eventWaiters]) {
      if (waiter.payloadType !== payloadType) continue;
      try {
        if (waiter.predicate(payload)) {
          waiter.resolve(payload);
          this.removeWaiter(waiter);
        }
      } catch (error) {
        waiter.reject(error instanceof Error ? error : new Error("CTRADER_EVENT_REJECTED"));
        this.removeWaiter(waiter);
      }
    }
  }

  private rejectPending(id: string, pending: Pending, error: Error): void {
    clearTimeout(pending.timer);
    const key = id || [...this.pending.entries()].find(([, item]) => item === pending)?.[0] || "";
    if (key) this.pending.delete(key);
    pending.reject(error);
  }

  private failAll(error: Error): void {
    for (const [id, pending] of this.pending) this.rejectPending(id, pending, error);
    for (const waiter of [...this.eventWaiters]) {
      waiter.reject(error);
      this.removeWaiter(waiter);
    }
  }

  private removeWaiter(waiter: EventWaiter): void {
    clearTimeout(waiter.timer);
    this.eventWaiters.delete(waiter);
  }

  request(
    payloadType: number,
    expectedPayloadType: number,
    payload: JsonRecord,
    predicate?: (payload: JsonRecord) => boolean,
    timeoutMs = 9000,
  ): Promise<JsonRecord> {
    const socket = this.socket;
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      return Promise.reject(new Error("CTRADER_WEBSOCKET_NOT_OPEN"));
    }
    const clientMsgId = randomBytes(12).toString("hex");
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(clientMsgId);
        reject(new Error(`CTRADER_RESPONSE_TIMEOUT:${expectedPayloadType}`));
      }, timeoutMs);
      this.pending.set(clientMsgId, { expectedPayloadType, resolve, reject, predicate, timer });
      try {
        socket.send(JSON.stringify({ clientMsgId, payloadType, payload }));
      } catch {
        this.rejectPending(clientMsgId, this.pending.get(clientMsgId)!, new Error("CTRADER_SEND_FAILED"));
      }
    });
  }

  waitForEvent(
    payloadType: number,
    predicate: (payload: JsonRecord) => boolean,
    timeoutMs = 9000,
  ): Promise<JsonRecord> {
    return new Promise((resolve, reject) => {
      const waiter: EventWaiter = {
        payloadType, predicate, resolve, reject,
        timer: setTimeout(() => {
          this.eventWaiters.delete(waiter);
          reject(new Error(`CTRADER_EVENT_TIMEOUT:${payloadType}`));
        }, timeoutMs),
      };
      this.eventWaiters.add(waiter);
    });
  }

  async authorize(accessToken: string, authorizedAccountId: string, clientId: string, clientSecret: string): Promise<void> {
    await this.request(2100, 2101, { clientId, clientSecret });
    const list = await this.request(2149, 2150, { accessToken });
    if (Number(list.permissionScope) !== 1) throw new Error("CTRADER_TRADE_SCOPE_REQUIRED");
    const accounts = Array.isArray(list.ctidTraderAccount) ? list.ctidTraderAccount as JsonRecord[] : [];
    const demo = accounts.find((account) =>
      account.isLive === false && String(account.ctidTraderAccountId ?? "") === authorizedAccountId
    );
    if (!demo) throw new Error("AUTHORIZED_DEMO_ACCOUNT_NOT_FOUND");
    await this.request(2102, 2103, {
      ctidTraderAccountId: Number(authorizedAccountId),
      accessToken,
    });
    this.accountId = authorizedAccountId;
  }

  private requireAccount(): number {
    if (!/^\d+$/.test(this.accountId)) throw new Error("CTRADER_ACCOUNT_NOT_AUTHORIZED");
    return Number(this.accountId);
  }

  async symbols(): Promise<JsonRecord[]> {
    const result = await this.request(2114, 2115, {
      ctidTraderAccountId: this.requireAccount(),
      includeArchivedSymbols: false,
    });
    return Array.isArray(result.symbol) ? result.symbol as JsonRecord[] : [];
  }

  async assets(): Promise<JsonRecord[]> {
    const result = await this.request(2112, 2113, {
      ctidTraderAccountId: this.requireAccount(),
    });
    return Array.isArray(result.asset) ? result.asset as JsonRecord[] : [];
  }

  async symbolDetails(symbolId: number): Promise<JsonRecord> {
    const result = await this.request(2116, 2117, {
      ctidTraderAccountId: this.requireAccount(),
      symbolId: [symbolId],
    });
    const symbols = Array.isArray(result.symbol) ? result.symbol as JsonRecord[] : [];
    const symbol = symbols.find((item) => Number(item.symbolId) === symbolId);
    if (!symbol) throw new Error("CTRADER_SYMBOL_DETAILS_MISSING");
    return symbol;
  }

  async trader(): Promise<JsonRecord> {
    const result = await this.request(2121, 2122, {
      ctidTraderAccountId: this.requireAccount(),
    });
    if (!result.trader || typeof result.trader !== "object") throw new Error("CTRADER_TRADER_DETAILS_MISSING");
    return result.trader as JsonRecord;
  }

  async reconcile(): Promise<{ positions: JsonRecord[]; orders: JsonRecord[] }> {
    const result = await this.request(2124, 2125, {
      ctidTraderAccountId: this.requireAccount(),
      returnProtectionOrders: true,
    });
    return {
      positions: Array.isArray(result.position) ? result.position as JsonRecord[] : [],
      orders: Array.isArray(result.order) ? result.order as JsonRecord[] : [],
    };
  }

  async deals(fromTimestamp: number, toTimestamp: number): Promise<{ deals: JsonRecord[]; hasMore: boolean }> {
    const result = await this.request(2133, 2134, {
      ctidTraderAccountId: this.requireAccount(),
      fromTimestamp,
      toTimestamp,
      maxRows: 1000,
    });
    return {
      deals: Array.isArray(result.deal) ? result.deal as JsonRecord[] : [],
      hasMore: result.hasMore === true,
    };
  }

  async cashFlows(fromTimestamp: number, toTimestamp: number): Promise<JsonRecord[]> {
    const result = await this.request(2143, 2144, {
      ctidTraderAccountId: this.requireAccount(),
      fromTimestamp,
      toTimestamp,
    });
    return Array.isArray(result.depositWithdraw) ? result.depositWithdraw as JsonRecord[] : [];
  }

  async trendbars(symbolId: number, period: number, count = 220): Promise<JsonRecord[]> {
    const result = await this.request(2137, 2138, {
      ctidTraderAccountId: this.requireAccount(),
      symbolId,
      period,
      toTimestamp: Date.now(),
      count,
    });
    return Array.isArray(result.trendbar) ? result.trendbar as JsonRecord[] : [];
  }

  async spot(symbolId: number): Promise<JsonRecord> {
    const event = this.waitForEvent(2131, (payload) => Number(payload.symbolId) === symbolId);
    try {
      await this.request(2127, 2128, {
        ctidTraderAccountId: this.requireAccount(),
        symbolId: [symbolId],
        subscribeToSpotTimestamp: true,
      });
      return await event;
    } catch (error) {
      void event.catch(() => undefined);
      throw error;
    }
  }

  async expectedMargin(symbolId: number, volume: number): Promise<JsonRecord[]> {
    const result = await this.request(2139, 2140, {
      ctidTraderAccountId: this.requireAccount(),
      symbolId,
      volume: [volume],
    });
    return Array.isArray(result.margin) ? result.margin as JsonRecord[] : [];
  }

  async newMarketRangeOrder(args: {
    symbolId: number;
    side: "BUY" | "SELL";
    volume: number;
    entryPrice: number;
    stopLoss: number;
    takeProfit: number;
    slippageInPoints: number;
    clientOrderId: string;
  }): Promise<JsonRecord> {
    const side = args.side === "BUY" ? 1 : 2;
    return await this.request(
      2106,
      2126,
      {
        ctidTraderAccountId: this.requireAccount(),
        symbolId: args.symbolId,
        orderType: 5,
        tradeSide: side,
        volume: args.volume,
        timeInForce: 4,
        baseSlippagePrice: args.entryPrice,
        slippageInPoints: args.slippageInPoints,
        stopLoss: args.stopLoss,
        takeProfit: args.takeProfit,
        clientOrderId: args.clientOrderId,
        label: "DOMINION_AI_DEMO",
        comment: "Automated demo order; protective SL/TP required.",
      },
      (payload) => {
        const executionType = Number(payload.executionType);
        if (executionType === 7) throw new Error(String(payload.errorCode ?? "CTRADER_ORDER_REJECTED"));
        if (executionType === 11) throw new Error("CTRADER_PARTIAL_FILL_BLOCKED");
        return executionType === 3;
      },
      12000,
    );
  }

  async amendProtection(positionId: number, stopLoss: number, takeProfit: number): Promise<JsonRecord> {
    return await this.request(
      2110,
      2126,
      {
        ctidTraderAccountId: this.requireAccount(),
        positionId,
        stopLoss,
        takeProfit,
      },
      (payload) => {
        const executionType = Number(payload.executionType);
        if (executionType === 7) throw new Error(String(payload.errorCode ?? "CTRADER_PROTECTION_AMEND_REJECTED"));
        return executionType === 2 || executionType === 3;
      },
      9000,
    );
  }

  async closePosition(positionId: number, volume: number): Promise<JsonRecord> {
    return await this.request(
      2111,
      2126,
      {
        ctidTraderAccountId: this.requireAccount(),
        positionId,
        volume,
      },
      (payload) => {
        const executionType = Number(payload.executionType);
        if (executionType === 7) throw new Error(String(payload.errorCode ?? "CTRADER_CLOSE_REJECTED"));
        return executionType === 3;
      },
      12000,
    );
  }

  async close(): Promise<void> {
    const socket = this.socket;
    this.socket = null;
    if (!socket) return;
    this.failAll(new Error("CTRADER_SESSION_CLOSED"));
    try { socket.close(); } catch { /* ignore close race */ }
  }
}

export function trendbarsToCandles(
  symbol: string,
  market: "FOREX" | "GOLD",
  timeframe: string,
  bars: JsonRecord[],
  timeframeSeconds: number,
  now = Date.now(),
): Array<{ symbol: string; market: "FOREX" | "GOLD"; timeframe: string; timestamp: Date; open: number; high: number; low: number; close: number; volume: number }> {
  const result = bars.map((bar) => {
    const low = Number(bar.low) / 100000;
    const open = (Number(bar.low) + Number(bar.deltaOpen ?? 0)) / 100000;
    const close = (Number(bar.low) + Number(bar.deltaClose ?? 0)) / 100000;
    const high = (Number(bar.low) + Number(bar.deltaHigh ?? 0)) / 100000;
    return {
      symbol, market, timeframe,
      timestamp: new Date(Number(bar.utcTimestampInMinutes) * 60000),
      open, high, low, close, volume: Number(bar.volume ?? 0),
    };
  }).filter((bar) => Number.isFinite(bar.open) && Number.isFinite(bar.high) &&
    Number.isFinite(bar.low) && Number.isFinite(bar.close) &&
    Number.isFinite(bar.timestamp.getTime()) &&
    bar.timestamp.getTime() + timeframeSeconds * 1000 <= now);
  return result.sort((a, b) => a.timestamp.getTime() - b.timestamp.getTime());
}
