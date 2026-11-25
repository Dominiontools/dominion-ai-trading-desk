# DOMINION AI TRADING DESK

A demo-first automated trading platform for Forex, Gold, and Crypto. One central Desk Manager coordinates eight specialist agents while separate market adapters handle each market's data and execution rules.

## Current stage
The development branch now contains a separate cTrader demo-trading authorization flow, a scheduled demo execution cycle, server-side risk checks, broker-side protection verification, and dashboard controls. These changes are not deployed or live-tested yet. The existing view-only cTrader authorization and encrypted tokens are preserved; the new trading permission is stored separately. The scheduled engine remains disabled until demo trading authorization and an explicit dashboard enable action are completed. No trade has been placed by this new engine.

## Eight agents
1. **SCANNER** — detects configured market conditions and candidate setups.
2. **RISK** — validates risk, sizing, exposure, and safety limits.
3. **SNIPER** — simulation execution adapter; live execution is intentionally disabled.
4. **WHALE** — monitors large-participant activity when reliable data is connected.
5. **RUG** — crypto contract/liquidity/developer-wallet risk checks; Forex adapts this role to feed and broker anomaly monitoring.
6. **EXIT** — manages simulated stops, targets, trailing stops, and scale-outs.
7. **HYPE** — social sentiment for crypto and economic/news sentiment for Forex.
8. **DESK MANAGER** — coordinates agents and records decisions; it never trades.

## Safety defaults
- Demo/paper mode only.
- cTrader execution hard-codes the demo WebSocket host and rejects live accounts.
- cTrader scheduled strategy checks run once per minute after deployment; they are not high-frequency or second-by-second Forex execution.
- Demo automation is disabled by default and requires a separate trading authorization plus an explicit dashboard enable action.
- Keep the existing cTrader OAuth **accounts/view-only** authorization for status and read-only access.
- A separate **trading** OAuth scope is used only by the demo execution service; it stores a separate encrypted token record and verifies that the selected account is a demo account.
- Live trading is disabled in the application configuration.
- No API keys or secrets belong in source control.
- Never enable withdrawals on exchange API keys.
- Require explicit human approval before any live-trading implementation or deployment.
- Validate strategies with historical data, paper trading, fees, slippage, and drawdown tests before considering live use.

## Two-account Netlify architecture
- New account: `dominion-ai-trading-desk-new` serves the dashboard and authenticated control proxy.
- Existing account: `dominion-ai-trading-desk-p7cp` preserves cTrader OAuth, encrypted tokens, status, and the scheduled demo execution functions.
- The dashboard-to-backend control path uses a server-side HMAC secret; the secret must be configured in both accounts before the final deployment.
- All development is on `feat/complete-demo-trading-engine`. Do not connect the new site or trigger Netlify builds until the complete review is finished.
- The project rule is one coordinated final deployment only, after explicit user approval.
- Build command: `npm run build`; publish directory: `dist`; Node.js 22.

## Android app

The dashboard can be installed as an Android app. See [docs/ANDROID_APP.md](docs/ANDROID_APP.md) for local setup and the GitHub Actions APK build. The Android app includes the on-device crypto paper monitor. It does not hold cTrader OAuth tokens or send cTrader broker orders; cTrader demo execution is handled by the old account's scheduled Netlify function. Crypto exchange order routing remains disabled.

## Run the dashboard locally
```bash
npm install
npm run dev
```

## Run Python safety tests
```bash
python -m pip install -r requirements-dev.txt
python -m pytest
```

## Project layout
- `src/` — dashboard UI.
- `engine/` — Python domain logic and market adapters.
- `tests/` — automated safety and risk tests.
- `docs/` — architecture and operating notes.

## Important
This software is not financial advice and does not guarantee profits. Simulated fills are not equivalent to real market execution.
