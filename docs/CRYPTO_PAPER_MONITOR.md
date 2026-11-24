# Continuous crypto paper monitor

The new engine.crypto_monitor module adds a controlled polling loop around the
public Binance, Bitget and HTX REST ticker adapters. Each cycle appends one JSON
record to a JSON Lines decision log.

## Safety behavior
- Paper-only: every record explicitly sets orders_enabled to false.
- Requires taker-fee estimates for all three exchanges. Missing fees block the
  scan; no fee tier is invented or assumed.
- Logs fetch failures and does not reuse old quotes.
- Logs quote snapshots, collection duration, and whether a net-edge threshold
  was met.
- Polling interval cannot be configured below one second. Default is five
  seconds to reduce unnecessary REST requests.
- The loop requires a caller-supplied stop event and can be bounded by
  max_cycles. There is no hidden background thread or auto-start behavior.

## How to run
Create a PublicCryptoFeeds instance and pass it to CryptoPaperMonitor with a
decision_log path. Supply current taker-fee values verified for the user's own
account and product tier. Until those values are verified, leave fee
configuration empty; every scan will be blocked safely. Start the run method
with a threading.Event and set that event to stop the monitor.

## Limitations
This is periodic REST polling, not a one-second guaranteed feed, WebSocket
stream, high-frequency trading engine, or arbitrage execution system. Public
API rate limits, network delay, exchange clock differences and top-of-book-only
depth remain limitations. The provisional 5 bps slippage estimate in the
underlying scanner is not a measured fill model. No trades, wallet actions,
deposits or withdrawals are possible from this module.
