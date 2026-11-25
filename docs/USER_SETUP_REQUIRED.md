# User setup required before the first demo execution

This list is intentionally separate from code completion. Do not send API secrets, private keys, OAuth codes, or passwords in ChatGPT.

## 1. GMGN read-only feed

- Create an official GMGN API key at https://gmgn.ai/ai.
- GMGN's setup process uses an Ed25519 key pair; submit the public key when creating the API key.
- Keep the private key secure and offline. Dominion's current read-only connector needs only the API key.
- Enter the API key in the Android app's **GMGN Official API · Read Only** panel.
- Save it in Android Keystore and restart the phone engine.
- Confirm the GMGN feed status becomes `CONNECTED`.

No GMGN wallet swaps or trading orders are currently enabled.

## 2. Binance Spot Testnet account

- Create a Spot Testnet API key from the official Binance Spot Testnet environment.
- Enable Spot trading permission for the Testnet key; keep withdrawals disabled.
- Enter the key and secret in the Android app's Binance Testnet panel.
- Confirm the read-only account/risk snapshot is verified and the account reports trading permission.
- The **Binance Testnet automation** switch is OFF by default. Only enable it when you explicitly want simulated Spot BUY orders on Binance Testnet.
- The router requires fresh quotes, verified symbol filters, authenticated per-symbol fees, available USDT, the shared position limit, and the durable daily-loss ledger.

The Android strategy loop is now wired to the protected Testnet router, but no actual Testnet order has yet been placed or verified. Automatic emergency market-flattening for an unprotected fill is not implemented; an uncertain protection state halts new entries and requires manual review.

## 3. Bitget Spot Demo API

Bitget officially supports Demo API keys. The documented flow is:
- Switch the Bitget account to **Demo mode** first.
- Open **Personal Center → API Key Management → Create a Demo API Key**.
- Use that Demo key with the `paptrading: 1` request header. The REST host remains `api.bitget.com`; the Demo key and header select the simulated environment.
- Keep withdrawals disabled. Do not use a live key with the demo header.
- Demo API access requires KYC according to Bitget's documentation.

Bitget's public market-data feed is already connected. The order adapter remains separate and must be completed and verified against the Demo API before the app exposes Bitget execution.

## 4. HTX Unified Account Demo

HTX announced Unified Account Demo Trading on 9 November 2026. Its demo interface supports Spot, Futures and Multi-Currency Margin with virtual funds. The older public Spot API reference still labels its legacy testnet as stopped; the new demo announcement does not document a matching REST API host or authentication flow.

Use the official demo interface for manual familiarization only. Do not connect an HTX live trading key to the old live API and call it a demo test. HTX execution stays disabled until the new Unified Account Demo API route is confirmed from official documentation and can be tested safely.

## 3. cTrader / Pepperstone demo

- The existing view-only authorization is preserved.
- The cTrader app must have the required Spotware approval and trading scope.
- After the final backend deployment, use the dashboard's separate **Authorize demo trading** action to request trading scope.
- Confirm the account is Pepperstone demo and the backend reports trading permission before enabling demo automation.
- Do not authorize a live account.

## 5. Exchange execution costs

- Binance's Testnet router fetches authenticated per-symbol commission rates directly; it does not rely on guessed fees.
- Bitget, HTX and OKX still need verified account-tier fees before their quotes can contribute to fee-adjusted arbitrage comparisons.
- Unknown fees keep cross-exchange arbitrage execution blocked. Do not use guessed fees to claim net profitability.

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
- Bitget and HTX public market-data feeds are connected; their execution adapters remain disabled pending implementation and demo verification.
- The cTrader engine is demo-only and requires trading-scope authorization and verified demo-order tests.
- Live-money trading remains locked and requires a separate explicit decision after demo acceptance.
