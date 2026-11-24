# Crypto directional paper strategy

The phone engine can use Binance public Spot 1-minute candles with a configurable
10/30 simple-moving-average crossover. A signal is only a candidate: it is
checked against the $20 paper equity, 0.5% risk cap, 2% daily loss limit, one
position maximum, spread/slippage and quote freshness rules.

Initial paper protection uses a 1% stop distance and 2:1 target. Position size
is calculated from the $0.10 risk budget and capped at $20 notional. Open
positions are marked using the executable side of the quote (bid to close BUY,
ask to close SELL); trailing stops, stop-losses and take-profits are journaled.

This is one baseline strategy, not a profit claim or a representation of every
strategy in the user's strategy guide. It uses public Binance REST candles,
not WebSockets, and does not place exchange orders. Public API availability,
minimum exchange order sizes, commissions and slippage can differ from paper
assumptions. The separate cross-exchange arbitrage monitor remains analysis-only.
