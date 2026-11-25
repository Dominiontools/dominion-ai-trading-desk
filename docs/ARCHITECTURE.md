# Architecture — first foundation

## High-level flow
Market data adapters -> SCANNER -> specialist analysis -> RISK -> SNIPER simulation adapter -> EXIT manager -> audit/event log. DESK MANAGER coordinates the workflow and never executes trades.

## Public crypto market data\n- Binance, Bitget, HTX and OKX public Spot REST endpoints provide unauthenticated bid/ask snapshots for scanning. OKX is a data source only; no OKX account key or execution route is configured.\n- Feed failures are tracked per venue. Missing or stale venues must not be treated as confirmation, and unverified exchange fees keep arbitrage estimates from being treated as executable profit.\n\n## Market separation
- Forex/Gold adapter: cTrader market data and, later, cTrader demo execution.
- Crypto adapter: exchange market data and, later, exchange sandbox/testnet execution.
- Both pass through the same portfolio-level risk policy, but retain market-specific strategy and execution rules.

## Agent boundaries
The eight agents are independent services/modules with explicit inputs and outputs. A specialist may recommend or veto a candidate, but only RISK may approve its risk envelope. SNIPER accepts only a risk-approved order intent. The initial implementation contains no live order client.

## Continuous worker
The web dashboard is not the always-on trading engine. A persistent worker will run separately (initially locally on the user's computer for cost control) and communicate through an authenticated API when that layer is designed. Netlify is intended for the dashboard/web deployment, not 24/7 order execution.

## Safety gates
Demo-only configuration, strict position sizing, daily drawdown cap, max-position cap, slippage rejection, stale-feed/disconnect stop, duplicate-order idempotency, structured audit logs, and an emergency stop are required before broker sandbox integration.
