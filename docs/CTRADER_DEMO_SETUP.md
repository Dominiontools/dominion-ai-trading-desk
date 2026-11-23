# cTrader demo market-data connection

This integration is intentionally **read-only** and demo-only.

## Why this route
The project uses Spotware's official Python Open API SDK. cTrader Open API supports market-data requests and a demo environment. The connector hard-codes the demo host and refuses an account whose API account record is marked live. It exposes no order-placement methods.

## One-time cTrader setup
1. Register an Open API application in the cTrader Open API portal and wait for approval.
2. Add the exact redirect URI that the application will use.
3. Authorize with the **accounts / view-only** scope, not the trading scope.
4. Set `CTRADER_REDIRECT_URI` to the exact loopback URI registered in the cTrader app (default: `http://127.0.0.1:8765/callback`).
5. Run `python -m engine.ctrader_oauth authorize` from the repository root. Approve **accounts / view-only** access in the browser; the helper exchanges the short-lived code and saves tokens to `.ctrader_tokens.json` with owner-only file permissions. Never commit or share this file.
6. Identify the cTrader demo account ID from the authorized account list.
7. Set `CTRADER_CLIENT_ID`, `CTRADER_CLIENT_SECRET`, and `CTRADER_ACCOUNT_ID` in your local environment. The worker loads the access token from the private token file and automatically refreshes/rotates it shortly before expiry. Never commit credentials or token files.

Required environment variables:
- `CTRADER_CLIENT_ID`
- `CTRADER_CLIENT_SECRET`
- `CTRADER_ACCESS_TOKEN` (optional override; normally loaded from the private token file)
- `CTRADER_ACCOUNT_ID` (must be a demo account)

Install runtime dependencies with `pip install -r requirements.txt`.

## Run the local read-only worker

After setting the three required cTrader environment values above and completing OAuth authorization, also set:

- `CTRADER_SYMBOLS` — comma-separated exact symbol names from the enabled-symbol list, for example `XAUUSD,EURUSD` only if those exact names are enabled by your broker.
- `CTRADER_MAX_QUOTE_AGE_SECONDS` — optional freshness threshold; defaults to 10 seconds.

Run from the repository root:

```bash
python -m engine.ctrader_worker
```

The worker authenticates to the demo host, subscribes to the selected symbols, logs timestamped bid/ask updates, and warns when a quote is missing or stale. It stops on authentication errors, disconnection, or a 30-second startup timeout. It does not automatically reconnect and it has no order-placement path. Keep the terminal open while it runs; Ctrl+C stops it.

## Connector behavior
- Connects only to cTrader's demo Open API host.
- Authenticates the application, checks the selected account exists in the granted account list, and refuses accounts marked live.
- Loads enabled symbol names and IDs for that account.
- Requests historical trend bars for a selected symbol and timeframe using a bounded time window.
- Requests timestamped live bid/ask updates for selected enabled symbols, waits for cTrader's subscription acknowledgement, and stops if the acknowledgement is not received before the startup timeout. It rejects missing-timestamp or crossed updates, retains bid and ask updates independently, and emits a complete quote only after both sides have been received.
- Maintains a reverse symbol-ID lookup so incoming spot events are associated with the correct instrument.
- Provides a separate fail-closed quote freshness validator; stale, timezone-naive, incomplete, crossed, or materially future-dated quotes are not considered fresh; the older of the bid and ask timestamps determines quote age.
- Converts cTrader's 1/100000 price representation and low-plus-delta OHLC format into the project's Candle model.
- Emits candle lists through a callback. It does not send any trade, close, amend, or cancel requests.

## Important limitations
The connector is callback-based because Spotware's Python SDK uses Twisted. It is a connection module, not yet a running background worker or dashboard connection. The app still needs a secure OAuth callback/token-refresh service, a supervised worker process, adding automatic reconnect supervision, secure OAuth callback/token refresh, and tests against an actual Pepperstone demo account before this can be called connected. The official SDK handles protocol heartbeats internally; this module does not yet supervise reconnects or worker health. The SDK and credentials are not exercised by CI against a broker.


## $20 starting-capital risk policy

The initial account target is **$20**. The default risk policy is deliberately conservative:

- Maximum planned loss per trade: **0.5% of current equity** (about **$0.10** at $20).
- Daily loss stop: **2% of current equity** (about **$0.40** at $20).
- Maximum concurrent positions: **1**.
- The risk gate rejects a proposed trade above the configured per-trade limit. The broker's minimum volume, margin, spread, commissions, and estimated slippage must also permit the trade; otherwise the correct action is to skip it.
- These are risk limits, not a promise that losses will be limited exactly to those amounts. Gaps, execution slippage, and fees can cause larger losses.
- Keep the system in demo/paper mode until the data connection and all safety tests have been verified. No live trading is enabled by this setup guide.
