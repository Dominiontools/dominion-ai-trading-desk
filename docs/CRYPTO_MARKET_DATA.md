# Public crypto market-data feeds

## Connected adapters
The read-only module `engine/crypto_feeds.py` can fetch best bid/ask and top-level
sizes for a requested spot pair from:
- Binance public Spot book ticker: `data-api.binance.vision/api/v3/ticker/bookTicker`
- Bitget classic Spot ticker: `api.bitget.com/api/v2/spot/market/tickers`
- HTX merged ticker: `api.huobi.pro/market/detail/merged`

These endpoints are public market data. No API keys are sent. The adapters do not
call account, wallet, transfer, withdrawal, or order endpoints.

## Timestamp handling
Bitget and HTX timestamps are parsed from their responses. Binance bookTicker does
not include a timestamp, so the adapter records local receipt time. This is weaker
than an exchange event timestamp; comparisons must account for clock skew and
request latency. The scanner's freshness gate is a preliminary filter, not a
latency guarantee.

## Important limitations
- This implementation fetches one REST snapshot per exchange when called. It is
  not a continuous one-second loop and is not a WebSocket feed.
- REST responses arrive at different moments. A future collector should capture
  request-start, response-receipt and exchange timestamps, measure round-trip time,
  and reject snapshots whose age/skew exceeds policy.
- It reads only the top of book. A proper executable arbitrage estimate must walk
  order-book depth and account for actual taker fees, precision, minimum size,
  balances already held on both venues, and fill risk.
- Public ticker endpoints can be rate-limited or unavailable. Failures are surfaced;
  no missing quote is fabricated and no stale quote is reused.
- Still paper-only. No order placement or private API credentials are implemented.
