# User setup required before the first demo execution

This list is intentionally separate from code completion. Do not send API secrets, private keys, OAuth codes, or passwords in ChatGPT.

## 1. Binance Spot Testnet account

- Create a Spot Testnet API key from the official Binance Spot Testnet environment.
- Enable Spot trading permission for the Testnet key; keep withdrawals disabled.
- Enter the key and secret in the Android app's Binance Testnet panel.
- Confirm the read-only account/risk snapshot is verified and the account reports trading permission.
- The **Binance Testnet automation** switch is OFF by default. Only enable it when you explicitly want simulated Spot BUY orders on Binance Testnet.
- The router requires fresh quotes, verified symbol filters, authenticated per-symbol fees, available USDT, the shared position limit, and the durable daily-loss ledger.

The Android strategy loop is now wired to the protected Testnet router, but no actual Testnet order has yet been placed or verified. A fail-closed emergency market-flattening path is implemented and unit-tested; its actual Testnet exercise and failure-injection verification remain outstanding.

## 2. Bitget and HTX public market data — no setup required

Bitget and HTX are included as public market-data sources only in this release stage. Their public feeds do not require private API keys, deposits, demo-account setup, or trading permissions.

No Bitget Demo API key or HTX Demo API key is required from the user. No Bitget or HTX execution adapter is part of the current acceptance checklist. Cross-exchange observations from these feeds are informational/paper analysis only; do not present a price spread as guaranteed net arbitrage profit. Where account-specific trading fees cannot be verified, fee-adjusted execution must remain blocked.

## 3. cTrader / Pepperstone demo

- The existing view-only authorization is preserved.
- The cTrader app must have the required Spotware approval and trading scope.
- After the final backend deployment, use the dashboard's separate **Authorize demo trading** action to request trading scope.
- Confirm the account is Pepperstone demo and the backend reports trading permission before enabling demo automation.
- Do not authorize a live account.

## 5. Exchange execution costs

- Binance's Testnet router fetches authenticated per-symbol commission rates directly; it does not rely on guessed fees.
- Bitget, HTX and OKX public quotes may be used for market comparison and paper monitoring.
- Account-tier fees must be verified before any fee-adjusted execution claim; unknown fees keep arbitrage execution blocked. Do not use guessed fees to claim net profitability.

## 6. Final two-account Netlify connection

Before the single coordinated deployment:
- Set the same random `DOMINION_CONTROL_API_SECRET` as a server-side secret in both the old cTrader backend project and the new dashboard project.
- Preserve `CTRADER_CLIENT_ID`, `CTRADER_CLIENT_SECRET`, and `CTRADER_TOKEN_ENCRYPTION_KEY` on the old backend.
- Keep the new dashboard protected by team login.
- Configure the old backend CORS allowlist for the new dashboard origin only.
- Deploy both projects together once, after all final checks and explicit user approval.

## Netlify deployment credit issue

The existing cTrader backend team's latest deployment attempts were skipped because that account exceeded its available Netlify credits. The new dashboard project currently has no deployment. No deployment has been started from this development branch.

Before the single final release, confirm that the old backend team has enough credits for one production deployment. If the credits cannot be restored, the alternative is to host the active cTrader backend on the new Netlify account and update the cTrader application's registered redirect URI to the new callback URL. That alternative requires a fresh cTrader authorization; the existing encrypted view-only authorization in the old account will remain preserved and untouched.

Do not silently switch backend accounts or redirect URIs. Choose that migration only after reviewing the effect and obtaining the user's approval.

## Safety boundary

- The Android crypto strategy is paper-only by default. Binance Spot Testnet execution is an optional BUY-only mode behind an explicit OFF-by-default Android switch.
- Bitget and HTX public market-data feeds are the agreed scope for this stage. No private credentials or execution setup is required.
- The cTrader engine is demo-only and requires trading-scope authorization and verified demo-order tests.
- Live-money trading remains locked and requires a separate explicit decision after demo acceptance.
