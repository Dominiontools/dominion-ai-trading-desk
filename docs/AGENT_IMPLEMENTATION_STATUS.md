# Agent implementation status

The video reference shows a multi-agent trading desk. Dominion implements the same eight-role layout, but the roles do not all have live execution authority. This status distinguishes code from connected data and from order execution.

| Agent | Current implementation | Execution status |
|---|---|---|
| SCANNER | DEX Screener discovery and a dynamic top-52 liquid USDT scanner using batched public REST snapshots from Binance, Bitget, HTX and OKX | Analysis only |
| RUG | GoPlus supported-chain checks; missing fields remain unknown | Risk screening only |
| WHALE | GeckoTerminal trade-flow observations | Monitoring only |
| HYPE | Public RSS headline sentiment | Monitoring only |
| SNIPER | Multi-timeframe crypto strategy and optional Binance Spot Testnet BUY router | Paper by default; Testnet only after explicit Android enablement |
| EXIT | Simulated crypto exit manager plus Binance exchange-held OTOCO protection, a 5-second read-only Testnet reconciliation worker, restart recovery and a separately gated emergency-flatten routine; separate cTrader demo position manager | Crypto paper / opt-in Binance Testnet / cTrader demo |
| RISK | Shared 0.5% trade-risk and 2% daily-stop gate, verified USDT account context, symbol filters, per-symbol fees and durable stop-loss ledger | Paper by default; gated Binance Testnet routing |
| DESK MANAGER | Combines agent state, readiness gates, activity and safety status | Coordination only |

## Important limitations

- Eight cards in the dashboard are not eight independent autonomous services. The Android service runs the available workflows and reports their states.
- The cross-exchange scanner reports fee-adjusted paper opportunities. Binance, Bitget, HTX and OKX market data does not mean orders can be placed on those venues.
- Binance Spot Testnet routing is connected to the Android strategy loop behind an explicit OFF-by-default automation switch. It is BUY-only and uses exchange-held stop-loss/take-profit legs. A partial entry fill is surfaced explicitly as `UNPROTECTED_PARTIAL_FILL`, remains unprotected, halts new entries and survives restart reconciliation. When Testnet mode is explicitly enabled, a background worker re-checks every journaled OTOCO order list every five seconds using read-only exchange queries. Invalid, stale/unresolved or failed reconciliation disables further entries and marks the EXIT/RISK agents for review. This worker does not submit or cancel orders. A deterministic, restart-safe emergency flatten path is implemented and unit-tested but is not yet invoked automatically by the monitor; actual Testnet emergency-close verification remains a mandatory readiness gate. End-to-end order, exit and restart verification on a real Testnet account remains outstanding.
- The cTrader backend contains a demo-only execution engine, but the saved authorization is currently view-only. Trading-scope authorization and broker-confirmed demo-order tests remain external acceptance gates. Its 2R scale-out now persists the outstanding close target before submission, reconciles the broker's actual remaining volume, resumes incomplete closes after worker restarts, and only marks the scale-out complete after the requested volume is confirmed. This is unit-tested at the risk/reconciliation layer. Emergency closes for unprotected Dominion positions and daily-loss stops now reconcile the broker position before reporting closure; if volume remains open, the engine reports a pending close and keeps the position blocked from new entries. These paths still require end-to-end Pepperstone demo testing.
- Live-money trading remains locked.


## Binance Testnet activation boundary

The Android automation switch is OFF by default and requires saved Testnet
credentials. Enabling it is a separate user action; no order is sent merely by
building or installing the app. When enabled, the local strategy loop uses the
verified account snapshot, daily-loss ledger, fresh quote, exchange filters
and authenticated per-symbol commission schedule before it can submit a
protected Testnet BUY. Live endpoints and wallet execution are not included.
