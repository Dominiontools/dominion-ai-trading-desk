# DOMINION AI TRADING DESK

A demo-first automated trading platform for Forex, Gold, and Crypto. One central Desk Manager coordinates eight specialist agents while separate market adapters handle each market's data and execution rules.

## Current stage
Foundation scaffold. The dashboard is an interface prototype with illustrative values. The Python domain layer contains the initial agent roster and risk policy. No broker or exchange order endpoint is enabled.

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
- Live trading is disabled in the application configuration.
- No API keys or secrets belong in source control.
- Never enable withdrawals on exchange API keys.
- Require explicit human approval before any live-trading implementation or deployment.
- Validate strategies with historical data, paper trading, fees, slippage, and drawdown tests before considering live use.

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
- `engine/` — Python domain logic and agent interfaces.
- `tests/` — automated safety and risk tests.
- `docs/` — architecture and operating notes.

## Important
This software is not financial advice and does not guarantee profits. Simulated fills are not equivalent to real market execution.
