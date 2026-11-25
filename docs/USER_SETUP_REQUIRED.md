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
- Enable only the permissions needed for the testnet account check and future Spot test orders.
- Keep withdrawals disabled.
- Enter the key and secret in the Android app's Binance Testnet panel.
- Confirm the account check reports `BINANCE_SPOT_TESTNET` and `can_withdraw: false`.

Saving credentials and reading the account does not enable order execution. The protected-order lifecycle must be completed and tested before any testnet order switch is exposed.

## 3. cTrader / Pepperstone demo

- The existing view-only authorization is preserved.
- The cTrader app must have the required Spotware approval and trading scope.
- After the final backend deployment, use the dashboard's separate **Authorize demo trading** action to request trading scope.
- Confirm the account is Pepperstone demo and the backend reports trading permission before enabling demo automation.
- Do not authorize a live account.

## 4. Exchange execution costs

- Supply or verify the actual account-tier taker fees for Binance, Bitget, HTX and OKX. OKX public market data does not require an API key; its fee value is still required before its quotes can contribute to fee-adjusted arbitrage comparisons.
- Unknown fees keep cross-exchange arbitrage execution blocked. Do not use guessed fees to claim net profitability.

## 5. Final two-account Netlify connection

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

- The Android crypto strategy and arbitrage scanner are paper-only today.
- The Binance Testnet order lifecycle is not yet wired to the Android strategy loop.
- The cTrader engine is demo-only and requires trading-scope authorization and verified demo-order tests.
- Live-money trading remains locked and requires a separate explicit decision after demo acceptance.
