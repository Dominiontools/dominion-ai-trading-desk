const DEMO_WS_URL = "wss://demo.ctraderapi.com:5036";

function randomMessageId() {
  return crypto.randomUUID();
}

function messageText(data) {
  if (typeof data === "string") return data;
  if (data instanceof ArrayBuffer) return new TextDecoder().decode(data);
  if (ArrayBuffer.isView(data)) return new TextDecoder().decode(data);
  throw new Error("CTRADER_INVALID_MESSAGE");
}

/** Short-lived Cloudflare-compatible cTrader demo WebSocket client. */
export class CTraderDemoSession {
  socket = null;
  pending = new Map();
  eventWaiters = new Set();
  accountId = "";

  async connect(timeoutMs = 10_000) {
    if (this.socket) throw new Error("CTRADER_SESSION_ALREADY_CONNECTED");
    await new Promise((resolve, reject) => {
      const socket = new WebSocket(DEMO_WS_URL);
      this.socket = socket;
      let settled = false;
      const finish = (error) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        if (error) {
          try { socket.close(); } catch { /* already closed */ }
          this.socket = null;
          reject(error);
        } else resolve();
      };
      const timer = setTimeout(() => finish(new Error("CTRADER_WEBSOCKET_CONNECT_TIMEOUT")), timeoutMs);
      socket.addEventListener("open", () => finish());
      socket.addEventListener("error", () => finish(new Error("CTRADER_WEBSOCKET_CONNECT_FAILED")));
      socket.addEventListener("message", (event) => this.onMessage(event.data));
      socket.addEventListener("close", () => {
        this.failAll(new Error("CTRADER_WEBSOCKET_CLOSED"));
        this.socket = null;
        if (!settled) finish(new Error("CTRADER_WEBSOCKET_CLOSED"));
      });
    });
  }

  onMessage(data) {
    let message;
    try {
      message = JSON.parse(messageText(data));
    } catch {
      this.failAll(new Error("CTRADER_INVALID_MESSAGE"));
      return;
    }
    const payload = message.payload ?? {};
    const payloadType = Number(message.payloadType ?? 0);
    const clientMsgId = typeof message.clientMsgId === "string" ? message.clientMsgId : "";
    const entry = clientMsgId ? this.pending.get(clientMsgId) :
      [...this.pending.entries()].find(([, item]) => item.expectedPayloadType === payloadType);
    const pendingId = Array.isArray(entry) ? entry[0] : clientMsgId;
    const pending = Array.isArray(entry) ? entry[1] : entry;

    if (payloadType === 2142 || payloadType === 2132) {
      const error = new Error(String(payload.description ?? payload.errorCode ??
        (payloadType === 2132 ? "CTRADER_ORDER_ERROR" : "CTRADER_API_ERROR")));
      if (pending) this.rejectPending(pendingId, pending, error);
      else this.failAll(error);
      return;
    }

    if (pending && pending.expectedPayloadType === payloadType) {
      try {
        if (!pending.predicate || pending.predicate(payload)) {
          clearTimeout(pending.timer);
          this.pending.delete(pendingId);
          pending.resolve(payload);
        }
      } catch (error) {
        this.rejectPending(pendingId, pending, error instanceof Error ? error : new Error("CTRADER_REQUEST_REJECTED"));
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

  rejectPending(id, pending, error) {
    clearTimeout(pending.timer);
    this.pending.delete(id);
    pending.reject(error);
  }

  failAll(error) {
    for (const [id, pending] of this.pending) this.rejectPending(id, pending, error);
    for (const waiter of [...this.eventWaiters]) {
      waiter.reject(error);
      this.removeWaiter(waiter);
    }
  }

  removeWaiter(waiter) {
    clearTimeout(waiter.timer);
    this.eventWaiters.delete(waiter);
  }

  request(payloadType, expectedPayloadType, payload, predicate, timeoutMs = 9000) {
    const socket = this.socket;
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      return Promise.reject(new Error("CTRADER_WEBSOCKET_NOT_OPEN"));
    }
    const clientMsgId = randomMessageId();
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(clientMsgId);
        reject(new Error(`CTRADER_RESPONSE_TIMEOUT:${expectedPayloadType}`));
      }, timeoutMs);
      this.pending.set(clientMsgId, { expectedPayloadType, resolve, reject, predicate, timer });
      try {
        socket.send(JSON.stringify({ clientMsgId, payloadType, payload }));
      } catch {
        this.rejectPending(clientMsgId, this.pending.get(clientMsgId), new Error("CTRADER_SEND_FAILED"));
      }
    });
  }

  waitForEvent(payloadType, predicate, timeoutMs = 9000) {
    return new Promise((resolve, reject) => {
      const waiter = {
        payloadType, predicate, resolve, reject,
        timer: setTimeout(() => {
          this.eventWaiters.delete(waiter);
          reject(new Error(`CTRADER_EVENT_TIMEOUT:${payloadType}`));
        }, timeoutMs)
      };
      this.eventWaiters.add(waiter);
    });
  }

  async authorize(accessToken, authorizedAccountId, clientId, clientSecret) {
    if (!/^\d+$/.test(String(authorizedAccountId))) throw new Error("DEMO_ACCOUNT_ID_MISSING");
    await this.request(2100, 2101, { clientId, clientSecret });
    const list = await this.request(2149, 2150, { accessToken });
    if (Number(list.permissionScope) !== 1) throw new Error("CTRADER_TRADE_SCOPE_REQUIRED");
    const accounts = Array.isArray(list.ctidTraderAccount) ? list.ctidTraderAccount : [];
    const demo = accounts.find((account) =>
      account?.isLive === false && String(account.ctidTraderAccountId ?? "") === String(authorizedAccountId)
    );
    if (!demo) throw new Error("AUTHORIZED_DEMO_ACCOUNT_NOT_FOUND");
    await this.request(2102, 2103, {
      ctidTraderAccountId: Number(authorizedAccountId), accessToken
    }, (payload) => String(payload.ctidTraderAccountId ?? "") === String(authorizedAccountId));
    this.accountId = String(authorizedAccountId);
  }

  requireAccount() {
    if (!/^\d+$/.test(this.accountId)) throw new Error("CTRADER_ACCOUNT_NOT_AUTHORIZED");
    return Number(this.accountId);
  }

  async symbols() {
    const result = await this.request(2114, 2115, {
      ctidTraderAccountId: this.requireAccount(), includeArchivedSymbols: false
    });
    return Array.isArray(result.symbol) ? result.symbol : [];
  }

  async assets() {
    const result = await this.request(2112, 2113, { ctidTraderAccountId: this.requireAccount() });
    return Array.isArray(result.asset) ? result.asset : [];
  }

  async symbolDetails(symbolId) {
    const result = await this.request(2116, 2117, {
      ctidTraderAccountId: this.requireAccount(), symbolId: [symbolId]
    });
    const symbols = Array.isArray(result.symbol) ? result.symbol : [];
    const symbol = symbols.find((item) => Number(item.symbolId) === symbolId);
    if (!symbol) throw new Error("CTRADER_SYMBOL_DETAILS_MISSING");
    return symbol;
  }

  async trader() {
    const result = await this.request(2121, 2122, { ctidTraderAccountId: this.requireAccount() });
    if (!result.trader || typeof result.trader !== "object") throw new Error("CTRADER_TRADER_DETAILS_MISSING");
    return result.trader;
  }

  async reconcile() {
    const result = await this.request(2124, 2125, {
      ctidTraderAccountId: this.requireAccount(), returnProtectionOrders: true
    });
    return {
      positions: Array.isArray(result.position) ? result.position : [],
      orders: Array.isArray(result.order) ? result.order : []
    };
  }

  async deals(fromTimestamp, toTimestamp) {
    const result = await this.request(2133, 2134, {
      ctidTraderAccountId: this.requireAccount(), fromTimestamp, toTimestamp, maxRows: 1000
    });
    return { deals: Array.isArray(result.deal) ? result.deal : [], hasMore: result.hasMore === true };
  }

  async cashFlows(fromTimestamp, toTimestamp) {
    const result = await this.request(2143, 2144, {
      ctidTraderAccountId: this.requireAccount(), fromTimestamp, toTimestamp
    });
    return Array.isArray(result.depositWithdraw) ? result.depositWithdraw : [];
  }

  async trendbars(symbolId, period, count = 220) {
    const result = await this.request(2137, 2138, {
      ctidTraderAccountId: this.requireAccount(), symbolId, period, toTimestamp: Date.now(), count
    });
    return Array.isArray(result.trendbar) ? result.trendbar : [];
  }

  async spot(symbolId) {
    const event = this.waitForEvent(2131, (payload) => Number(payload.symbolId) === symbolId);
    try {
      await this.request(2127, 2128, {
        ctidTraderAccountId: this.requireAccount(), symbolId: [symbolId], subscribeToSpotTimestamp: true
      });
      return await event;
    } catch (error) {
      void event.catch(() => undefined);
      throw error;
    }
  }

  async expectedMargin(symbolId, volume) {
    const result = await this.request(2139, 2140, {
      ctidTraderAccountId: this.requireAccount(), symbolId, volume: [volume]
    });
    return { margins: Array.isArray(result.margin) ? result.margin : [], moneyDigits: Number(result.moneyDigits ?? 0) };
  }

  async newMarketRangeOrder(args) {
    return await this.request(2106, 2126, {
      ctidTraderAccountId: this.requireAccount(),
      symbolId: args.symbolId,
      orderType: 5,
      tradeSide: args.side === "BUY" ? 1 : 2,
      volume: args.volume,
      timeInForce: 4,
      baseSlippagePrice: args.entryPrice,
      slippageInPoints: args.slippageInPoints,
      stopLoss: args.stopLoss,
      takeProfit: args.takeProfit,
      clientOrderId: args.clientOrderId,
      label: "DOMINION_AI_DEMO",
      comment: "Automated demo order; protective SL/TP required."
    }, (payload) => {
      const executionType = Number(payload.executionType);
      if (executionType === 7) throw new Error(String(payload.errorCode ?? "CTRADER_ORDER_REJECTED"));
      if (executionType === 11) throw new Error("CTRADER_PARTIAL_FILL_BLOCKED");
      if ([4, 5, 6].includes(executionType)) throw new Error("CTRADER_ORDER_NOT_FILLED");
      return executionType === 3;
    }, 12_000);
  }

  async amendProtection(positionId, stopLoss, takeProfit) {
    return await this.request(2110, 2126, {
      ctidTraderAccountId: this.requireAccount(), positionId, stopLoss, takeProfit
    }, (payload) => {
      const executionType = Number(payload.executionType);
      if (executionType === 7) throw new Error(String(payload.errorCode ?? "CTRADER_PROTECTION_AMEND_REJECTED"));
      return executionType === 2 || executionType === 3;
    }, 9000);
  }

  async closePosition(positionId, volume) {
    return await this.request(2111, 2126, {
      ctidTraderAccountId: this.requireAccount(), positionId, volume
    }, (payload) => {
      const executionType = Number(payload.executionType);
      if (executionType === 7) throw new Error(String(payload.errorCode ?? "CTRADER_CLOSE_REJECTED"));
      return executionType === 3 || executionType === 8;
    }, 12_000);
  }

  async close() {
    const socket = this.socket;
    this.socket = null;
    if (!socket) return;
    this.failAll(new Error("CTRADER_SESSION_CLOSED"));
    try { socket.close(); } catch { /* ignore close race */ }
  }
}

export function trendbarsToCandles(symbol, market, timeframe, bars, timeframeSeconds, now = Date.now()) {
  if (!Array.isArray(bars) || !["FOREX", "GOLD"].includes(market) ||
      typeof symbol !== "string" || typeof timeframe !== "string" ||
      !Number.isFinite(timeframeSeconds) || timeframeSeconds <= 0 || !Number.isFinite(now)) {
    throw new Error("INVALID_TRENDBAR_CONVERSION_INPUT");
  }
  return bars.map((bar) => {
    const low = Number(bar.low) / 100000;
    return {
      symbol, market, timeframe,
      timestamp: new Date(Number(bar.utcTimestampInMinutes) * 60_000),
      open: (Number(bar.low) + Number(bar.deltaOpen ?? 0)) / 100000,
      high: (Number(bar.low) + Number(bar.deltaHigh ?? 0)) / 100000,
      low,
      close: (Number(bar.low) + Number(bar.deltaClose ?? 0)) / 100000,
      volume: Number(bar.volume ?? 0)
    };
  }).filter((bar) => Number.isFinite(bar.open) && Number.isFinite(bar.high) &&
    Number.isFinite(bar.low) && Number.isFinite(bar.close) &&
    Number.isFinite(bar.timestamp.getTime()) &&
    bar.timestamp.getTime() + timeframeSeconds * 1000 <= now)
    .sort((a, b) => a.timestamp.getTime() - b.timestamp.getTime());
}
