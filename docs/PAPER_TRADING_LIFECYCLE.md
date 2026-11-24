# Paper trading lifecycle

This module wires the core paper-trading lifecycle into one tested service:
strategy/scanner signal input -> validation -> 0.5% risk gate -> paper entry ->
trailing-stop updates -> stop-loss/take-profit/manual paper exit -> journal.

Defaults follow the project rules: $20 starting equity, 0.5% maximum risk per
trade ($0.10 at $20), 2% daily loss stop ($0.40 at $20), and one open position.
A signal is rejected for invalid levels, excessive size, stale quotes, wide
spread, excessive estimated slippage, or a reached daily loss limit.

This is a reusable execution simulator, not a signal generator and not a broker
adapter. It does not submit real orders, read exchange account balances, or
guarantee fills. Feed actual, validated market signals into `open_from_signal`
and current prices into `update_price`. PnL excludes fees, funding, spread and
slippage beyond the pre-entry gate, so it is illustrative paper accounting.
All events are tagged PAPER_ONLY and orders_enabled=false.
