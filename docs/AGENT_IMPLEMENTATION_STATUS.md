# Agent implementation status

The video reference shows a multi-agent trading desk. Dominion implements the same eight-role layout, but the roles do not all have live execution authority. This status distinguishes code from connected data and from order execution.

| Agent | Current implementation | Execution status |
|---|---|---|
| SCANNER | DEX Screener discovery, GMGN Trenches when a key is configured, and a dynamic top-52 liquid USDT scanner using batched public REST snapshots from Binance, Bitget, HTX and OKX | Analysis only |
| RUG | GoPlus supported-chain checks plus GMGN documented token-security evidence; missing fields remain unknown | Risk screening only |
| WHALE | GeckoTerminal trade-flow observations | Monitoring only |
| HYPE | Public RSS headline sentiment | Monitoring only |
| SNIPER | Multi-timeframe crypto paper strategy plus GMGN paper-review candidate filter | Paper only; no GMGN swaps |
| EXIT | Simulated crypto exit/position manager; separate cTrader demo position manager manages broker positions | Crypto paper / cTrader demo |
| RISK | Paper risk planner, cTrader demo risk sizing and protective-order gates | Crypto order lifecycle not yet wired |
| DESK MANAGER | Combines agent state, readiness gates, activity and safety status | Coordination only |

## Important limitations

- Eight cards in the dashboard are not eight independent autonomous services. The Android service runs the available workflows and reports their states.
- GMGN must be configured with an official API key before Trenches, trending and security reads can connect.
- GMGN sniper candidates are filtered for paper review only. No private key or swap endpoint is connected.
- The cross-exchange scanner reports fee-adjusted paper opportunities. Binance, Bitget, HTX and OKX market data does not mean orders can be placed on those venues.
- Binance Spot Testnet protected-order code exists, but its complete order lifecycle is not yet connected to the Android strategy loop.
- The cTrader backend contains a demo-only execution engine, but the saved authorization is currently view-only. Trading-scope authorization and broker-confirmed demo-order tests remain external acceptance gates.
- Live-money trading remains locked.
