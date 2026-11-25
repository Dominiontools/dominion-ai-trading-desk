# Dominion AI Trading Desk — execution acceptance specification

This specification records the user's requested operating model. It is an implementation target, not a statement that these capabilities are already connected or verified.

## Current implementation status on the development branch

- **Implemented in code, not deployed or broker-tested:** separate cTrader demo trading authorization, encrypted token separation, scheduled demo execution cycle, broker-side SL/TP verification, risk sizing, daily stop, break-even, 2R scale-out and 3R runner management.
- **Implemented in code, paper-only:** Android multi-timeframe crypto confluence strategy and BTC cross-exchange REST snapshot monitor.
- **Still outstanding:** dynamic 52-market discovery, crypto exchange testnet order lifecycle, shared cross-division position/risk lock, full independent division controls, all eight agents connected to verified feeds/workflows, configurable strategy builder, and broker/exchange integration tests.
- No new Netlify deployment has been started and this development engine has not placed a trade.

## 1. Shared desk, independent market divisions

- One Desk Manager and one eight-agent roster coordinate the whole application: SCANNER, RISK, SNIPER, WHALE, RUG, EXIT, HYPE, and DESK MANAGER.
- Forex/Gold and Crypto are separate divisions with independent enable/disable controls, market data, configuration, execution adapters, logs, and readiness states.
- The shared RISK agent enforces portfolio-wide limits across both divisions. A position opened in one division counts against the shared position limit.
- Forex/Gold execution is isolated behind the cTrader adapter. Crypto execution is isolated behind exchange adapters. Neither adapter can bypass the shared risk gate.
- The Desk Manager coordinates and audits; it does not place orders itself.

## 2. Forex and Gold strategy requirements

Supported strategy families:
- Trend following and higher-timeframe trend agreement.
- Breakouts and support/resistance retests.
- Fibonacci pullbacks.
- EMA trend confirmation (50/200) and pullback confirmation (20/50).
- MACD and RSI confirmation.
- SMC/ICT concepts: liquidity sweeps, break of structure (BOS), change of character (CHoCH), order blocks, and fair-value gaps (FVG).
- London and New York session filters.
- Configurable confluence score threshold.

Supported timeframe profiles:
- 5-minute execution with 1-hour context.
- 15-minute execution with 4-hour context.
- 4-hour execution with 1-day context.

The SMC Gold example must support: 4H BOS; retracement into discount; 15M liquidity sweep/CHoCH; order-block/FVG entry; stop beyond the swept low/high; target prior swing or liquidity; minimum 2R reward-to-risk.

Risk placement may use a stop 0.8–2.5 ATR beyond a recent swing, with 2R and 3R target levels. Every proposed stop and target must be validated against broker symbol rules and minimum stop distances before routing.

Initial watchlist candidates include XAUUSD, EURUSD, GBPUSD and broker-enabled additional Forex pairs. Symbol names must be discovered from the connected broker; examples are not assumed to be enabled.

## 3. Crypto strategy and market-integrity requirements

- Cross-exchange monitoring for Binance, Bitget, and HTX, including BTC/USDT price comparison, liquidity/depth, spread, volume changes, and fee-aware arbitrage estimates.
- Target one-second observation intervals where exchange limits and device/network performance allow. Public REST polling must not be represented as WebSocket streaming.
- Token discovery and safety checks include contract verification, mint/freeze authority, liquidity/LP lock evidence, honeypot checks, holder concentration, whale activity, developer-wallet activity, and social/news signals.
- The user-requested crypto watchlist includes PAXGUSDT, BTCUSDT, ETHUSDT and additional configurable markets; token discovery may monitor up to 52 markets, subject to feed/API limits.
- Missing or stale safety evidence blocks a token from execution. A score is evidence for review, not a guarantee that a token is safe.

For Crypto, the user's 40% equity-per-trade setting is treated only as an upper bound on capital/notional allocation, never as permitted loss. Forex/Gold sizing instead uses the broker's verified contract, volume, currency-conversion and margin rules; the Crypto notional cap is not applied to leveraged Forex/Gold positions. The user's 2% slippage value is an absolute rejection ceiling, not a target; the current stricter Crypto execution gate (15 bps / 0.15%) remains the default until separately reviewed.

## 4. Shared risk and order-management policy

- Maximum planned loss risk per trade: 0.5% of equity.
- Daily realized-loss stop: 2% of starting daily equity.
- Maximum concurrent open positions: one across all enabled divisions.
- Maximum notional allocation per trade: 40% of equity, subject to margin and venue constraints.
- Reject spread above 20 bps, estimated slippage above 15 bps, or quote age above 10 seconds.
- Reject unknown contract/lot rules, unverified fees, insufficient margin, invalid volume steps, closed markets, and unverified symbol metadata.
- Every entry requires broker/exchange-confirmed protective stop-loss and take-profit handling. A filled position without confirmed protection triggers emergency handling and blocks new entries.
- Support automatic exits at stop-loss/take-profit, strategy invalidation, configured trailing stops, and manual close requests.
- Reconcile local state against broker/exchange state after startup, reconnect, order response, and on a regular schedule.
- Use idempotent client order identifiers, durable journals, structured logs, and a global emergency stop.
- Never enable withdrawals or request withdrawal permissions on exchange API keys.

## 5. Execution stages and authorization

1. Strategy backtests and deterministic unit tests.
2. Paper trading using live public/demo market data.
3. Broker demo and exchange testnet order lifecycle tests, including partial fills, rejected orders, protective-order verification, cancellation, close, and restart recovery.
4. Final security and operational review.
5. Live-money mode remains disabled until the demo lifecycle is verified, the required broker/exchange approvals and trading scopes are in place, and the user explicitly approves live-money activation.

The currently saved Pepperstone cTrader authorization is view-only. It must remain untouched. A separate trading-scope authorization is required before cTrader demo order tests can be run. The current crypto credential vault is storage groundwork; its order adapter is not yet connected to the Android service.

## 6. Completion criteria

The system is not considered operational until:
- Both divisions can be enabled/disabled independently.
- Market data is current and source-labelled.
- Each strategy emits explainable, reproducible signals with timeframe and confluence details.
- The shared risk gate calculates valid size using verified venue contract rules and account currency.
- Demo/testnet entry, protective SL/TP, auto-exit, manual close, reconciliation, and restart recovery pass integration tests.
- The UI shows actual broker/exchange balances, positions, order states, P/L, agent activity, and engine health; it never substitutes sample values for live data.
- All order decisions and state changes are auditable.
