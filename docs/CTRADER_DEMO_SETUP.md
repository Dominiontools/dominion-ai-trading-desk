# cTrader demo market-data connection

This integration is intentionally **read-only** and demo-only.

## Why this route
The project uses Spotware's official Python Open API SDK. cTrader Open API supports market-data requests and a demo environment. The connector hard-codes the demo host and refuses an account whose API account record is marked live. It exposes no order-placement methods.

## One-time cTrader setup
1. Register an Open API application in the cTrader Open API portal and wait for approval.
2. Add the exact redirect URI that the application will use.
3. Authorize with the **accounts / view-only** scope, not the trading scope.
4. Exchange the authorization code for an access token using cTrader's OAuth flow.
5. Identify the cTrader demo account ID from the authorized account list.
6. Store the values as server-side environment variables. Never commit them or paste secrets into source files.

Required environment variables:
- `CTRADER_CLIENT_ID`
- `CTRADER_CLIENT_SECRET`
- `CTRADER_ACCESS_TOKEN`
- `CTRADER_ACCOUNT_ID` (must be a demo account)

Install runtime dependency with `pip install -r requirements.txt`.

## Connector behavior
- Connects only to cTrader's demo Open API host.
- Authenticates the application, checks the selected account exists in the granted account list, and refuses accounts marked live.
- Loads enabled symbol names and IDs for that account.
- Requests historical trend bars for a selected symbol and timeframe using a bounded time window.
- Subscribes to timestamped live bid/ask updates for selected enabled symbols and rejects missing-timestamp, partial, or crossed quotes.
- Maintains a reverse symbol-ID lookup so incoming spot events are associated with the correct instrument.
- Provides a separate fail-closed quote freshness validator; stale, timezone-naive, incomplete, crossed, or materially future-dated quotes are not considered fresh.
- Converts cTrader's 1/100000 price representation and low-plus-delta OHLC format into the project's Candle model.
- Emits candle lists through a callback. It does not send any trade, close, amend, or cancel requests.

## Important limitations
The connector is callback-based because Spotware's Python SDK uses Twisted. It is a connection module, not yet a running background worker or dashboard connection. The app still needs a secure OAuth callback/token-refresh service, a supervised worker process, wiring the quote freshness validator into the running worker/risk boundary, reconnect supervision, and tests against an actual Pepperstone demo account before this can be called connected. The official SDK handles protocol heartbeats internally; this module does not yet supervise reconnects or worker health. The SDK and credentials are not exercised by CI against a broker.
