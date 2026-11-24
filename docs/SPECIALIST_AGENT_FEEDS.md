# Public specialist-agent feeds (paper-only)

The Android foreground engine runs two independent loops:
- The existing 5-second public exchange ticker monitor for BTC/USDT and ETH/USDT.
- A slower specialist-feed cycle, every 60 seconds, to respect provider limits.

## Connected public sources

| Agent | Provider | Data used | Notes |
|---|---|---|---|
| SCANNER | DEX Screener | Latest token profiles, pool price, liquidity, 24h volume and buys/sells | Public endpoints; latest profiles and pair enrichment |
| WHALE | GeckoTerminal | Recent pool swaps, USD trade value, side, timestamp and source wallet | Public pool-trades endpoint; alerts only above USD 100,000 notional |
| HYPE | Cointelegraph RSS | Public news headlines and descriptions | Basic keyword sentiment only; not social-media monitoring or market consensus |
| RUG | GoPlus Security | EVM token contract-security flags | Uses the documented free anonymous tier; optional Bearer token can raise limits |

Official references:
- DEX Screener API: https://docs.dexscreener.com/api/reference
- GeckoTerminal API: https://api.geckoterminal.com/docs/
- GoPlus API: https://docs.gopluslabs.io/reference/api-overview
- Cointelegraph RSS: https://cointelegraph.com/rss

## Configuration

GoPlus documents free API access with a limit of 30 calls per minute. The Token Security API reference includes an optional Authorization Bearer header; the Support page says an access token is needed when a higher limit is required. The phone engine therefore makes anonymous free-tier requests by default and can optionally attach DOMINION_GOPLUS_TOKEN if a higher-limit token is configured later. No credentials are needed for initial testing.

## Safety and limitations

- All feeds are read-only. They cannot access exchange accounts, wallets, or submit trades.
- DEX liquidity and volume are snapshots and can change rapidly.
- GeckoTerminal trade samples are not a complete view of every wallet or exchange.
- The whale alert threshold is a configurable heuristic, not proof that a wallet is an institutional whale.
- RSS keyword scoring can misread sarcasm, context, duplicates, and promotional content.
- GoPlus flags are not a guarantee that a token is safe. Missing fields remain unknown; no clean safety result is inferred from missing data.
- Solana and other unsupported GoPlus chain cases remain unassessed by this EVM adapter.
- Provider failures are surfaced as feed errors; missing data must never be interpreted as a pass.
- No automated entry or exit orders are enabled. cTrader position management remains blocked until Spotware approves the cTrader app and the user authorizes the Pepperstone demo account.