# cTrader demo execution service

## Architecture

The two Netlify accounts have separate responsibilities:

- **New account — dashboard:** `dominion-ai-trading-desk-new`. It serves the user interface and an authenticated control proxy.
- **Existing account — cTrader backend:** `dominion-ai-trading-desk-p7cp`. It retains the cTrader OAuth callback, encrypted token store, status endpoints and the scheduled demo execution function.
- **Broker:** Pepperstone cTrader demo. The execution module connects only to `wss://demo.ctraderapi.com:5036`; it does not select a live endpoint.

The dashboard does not receive cTrader access tokens. The new account's server-side proxy signs control requests with HMAC; the old backend verifies the signature, timestamp and one-time nonce before changing the stored engine configuration.

## Authorization

The existing `accounts` / view-only authorization remains in `account/tokens` and `account/status`.

A separate dashboard link starts the cTrader OAuth flow with the `trading` scope. The callback verifies permission scope 1 and confirms that the selected account is a demo account. It encrypts the new token separately under:

- `account/trading-tokens`
- `account/trading-status`

The view-only token is never overwritten. The scheduled engine refuses to run without a connected demo trading status, scope 1, a verified demo account ID and the existing encryption key. Spotware approval may be required before cTrader grants trading permission.

## Scheduled engine

`ctrader-engine-cycle.mts` is a Netlify Scheduled Function configured for one cycle per minute. It is not a persistent WebSocket process and does not provide second-by-second Forex execution.

The engine configuration is stored in Netlify Blobs at `account/engine-config`. If no configuration exists, automation is disabled. The dashboard can configure the timeframe profile (scalp/intraday/swing), broker symbol watchlist, minimum confluence score, London/New York session filter, risk per trade and daily-loss stop. Risk can be reduced below the hard limits but cannot be raised above 0.5% per trade or 2% daily loss. The dashboard can enable automation only after trading authorization is verified and the user confirms the demo-automation warning.

The cycle:
1. Acquires a short-lived lock to avoid overlapping runs.
2. Loads and, when necessary, refreshes the encrypted trading token.
3. Authenticates the application and the verified demo account.
4. Reads account, positions, pending orders, symbol rules, quotes, candle history, closed deals and cash-flow history.
5. Evaluates the configured multi-timeframe confluence strategy.
6. Applies risk, commission, spread, slippage, volume, stop-distance and margin checks.
7. Sends at most one market-range demo order, with stop-loss and take-profit attached.
8. Reconciles the broker position and confirms protective levels. If a bot-filled position is unprotected, it requests an emergency close.
9. Manages an open bot position: strategy-invalidation exit, break-even stop at 1R, partial close at 2R where broker volume rules allow, and a broker-side 3R target for the remaining position.

The broker-side stop-loss and take-profit remain active if the scheduled function is delayed or unavailable.

## Risk and execution gates

- Maximum planned price risk plus estimated round-trip commission: **0.5% of account equity per trade**; the user may configure a lower value down to 0.05%.
- Daily realized plus bot-position mark-to-market loss stop: **2% maximum**, configurable down to 0.5%. Deal and cash-flow history must be complete to calculate the realized component.
- Maximum one open position; existing pending orders block a new entry.
- Maximum spread: **20 bps**.
- Maximum market-range slippage: **15 bps**.
- Expected margin must be returned and must not exceed **50% of account equity**.
- Broker minimum/maximum/step volume, minimum stop distances and short-selling permissions are checked.
- Commission details must be available and supported by the calculation. Unknown commission data blocks an entry.
- The initial risk model supports a USD-denominated cTrader account and symbols whose quote asset matches the account deposit asset. Unsupported currency conversions are blocked rather than guessed.
- The 40% notional allocation cap applies to Crypto, not leveraged Forex/Gold positions.

These are conservative software gates, not a guarantee against gaps, broker outages, rejected orders or losses.

## Control and environment configuration

The old backend needs its existing server-side variables:

- `CTRADER_CLIENT_ID`
- `CTRADER_CLIENT_SECRET`
- `CTRADER_TOKEN_ENCRYPTION_KEY`

The **same newly generated** `DOMINION_CONTROL_API_SECRET` must be configured as a server-side environment variable in both Netlify accounts. Never place it in browser code, source control, a chat message or a public build artifact.

The new dashboard project must remain protected by Netlify team login so the control proxy can verify `context.user`. The old backend control endpoint accepts only valid HMAC-signed requests from that proxy.

## Deployment and activation

This development branch is not deployed. No new cTrader demo order has been placed by this implementation.

Before activation:
1. Complete the full code and security review.
2. Configure the shared control secret in both accounts.
3. Verify the old backend still retains the existing view-only authorization.
4. Complete the separate cTrader demo trading authorization after Spotware approval.
5. Deploy both accounts together in the single final deployment approved by the user.
6. Confirm status and run read-only reconciliation first.
7. The user must explicitly enable demo automation in the dashboard before the scheduled engine can place demo orders.

Live-money trading remains disabled in code. This engine has no live endpoint, no live-account selection and no live activation control.
