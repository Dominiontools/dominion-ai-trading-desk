# Crypto arbitrage — paper mode

## Current scope
The first crypto module compares supplied bid/ask quotes for the same symbol across
different exchanges. It calculates the gross price gap, subtracts conservative taker
fees and a provisional slippage allowance, checks quote freshness and top-of-book
size, and returns paper-only opportunities.

It does **not** connect to Binance, Bitget, HTX, GMGN, wallets, or smart contracts.
It does not sign transactions, transfer funds, or place orders.

## Important execution realities
- Cross-exchange arbitrage normally requires funds already available on both exchanges.
  Moving funds after seeing a gap is usually too slow and adds network/withdrawal risk.
- A displayed bid/ask is not a guaranteed fill. Real sizing must walk the order book.
- Fee tiers, rebates, minimum order sizes, precision, rate limits and API outages matter.
- Stablecoin, custody, exchange and transfer risks remain even if withdrawals are disabled.
- Token mint/freeze authority, LP locks and honeypot checks are chain-specific; no single
  check can prove a token is safe.
- A one-second polling loop is not high-frequency trading and cannot guarantee priority.

## Project safety policy
- Paper mode only; no live execution path in this module.
- Starting capital assumption: $20. Do not copy the example post's 40% equity allocation.
- Keep the project-wide risk policy at no more than 0.5% planned risk per trade,
  2% daily loss stop, and one open position until separately tested.
- If quotes are stale, depth is missing, fees are unknown, or net edge is too small,
  reject the opportunity.
- Log every scan decision before any future simulated position state changes.
- Live trading requires a separate implementation, tests, explicit user approval,
  and exchange API keys with withdrawals disabled.
