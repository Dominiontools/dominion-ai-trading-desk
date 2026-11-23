# DOMINION AI TRADING DESK

A demo-first automated trading platform for Forex, Gold, and Crypto. One central Desk Manager coordinates eight specialist agents while separate market adapters handle each market's data and execution rules.

## Current stage
Foundation scaffold plus a read-only cTrader demo market-data connector. The dashboard is an interface prototype with illustrative values. The connector requires an approved cTrader Open API application and demo view-only credentials; it has not yet been authenticated against a broker. No broker or exchange order endpoint is enabled.

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
- cTrader connector hard-codes the demo host and rejects live accounts.
- Use cTrader OAuth **accounts/view-only** scope; do not grant trading scope to this data connector.
- Live trading is disabled in the application configuration.
- No API keys or secrets belong in source control.
- Never enable withdrawals on exchange API keys.
- Require explicit human approval before any live-trading implementation or deployment.
- Validate strategies with historical data, paper trading, fees, slippage, and drawdown tests before considering live use.

## Android app

The dashboard can be installed as an Android app. See [docs/ANDROID_APP.md](docs/ANDROID_APP.md) for local setup and the GitHub Actions APK build. The Android app is currently a demo-only dashboard shell; live broker data and order execution are not connected.

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
