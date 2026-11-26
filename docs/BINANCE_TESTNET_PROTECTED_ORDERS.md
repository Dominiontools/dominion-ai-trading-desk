# Binance Spot Testnet protected-order lifecycle

## Current implementation

The Binance Spot Testnet route is connected to the Android strategy service. It is an opt-in test environment only; it is not a production trading route.

- The adapter is pinned to `https://testnet.binance.vision`.
- Order placement requires both constructor authorization and the explicit `DOMINION_ENABLE_BINANCE_TESTNET_ORDERS=YES` runtime gate.
- The Android **Binance Testnet automation** switch is OFF by default and requires Testnet credentials saved in the Android credential vault.
- Credentials are used on-device by the local Python service. They are not sent to Netlify.
- The initial route accepts validated crypto BUY signals only. SELL signals and unsupported markets are skipped.
- Risk limits are shared with the strategy workflow: maximum 0.5% planned risk per trade, 2% daily loss stop, and one open position.
- Account permission, USDT equity and available balance, open holdings, symbol filters, fresh quotes, authenticated per-symbol commission rates, and daily-loss state must all be verified before an entry can be planned.

## Protected entry and exits

The adapter submits a Binance OTOCO order list. The working entry is a BUY LIMIT with FOK time-in-force. The pending exits are a SELL LIMIT_MAKER take-profit and a SELL STOP_LOSS_LIMIT stop-loss.

A placement response alone is not proof of protection. The lifecycle queries the entry and both exit legs. It reports `PROTECTED` only after the entry is FILLED and both exit legs are confirmed NEW. A stop-limit can fail to execute during a fast gap, so exchange-held protection does not guarantee a fill or cap realized losses.

## Restart recovery and daily loss

Before the network submission, the lifecycle writes the unique order-list ID, symbol and planned risk amount to an atomic local journal. On restart it queries every recorded order list and does not blindly resubmit uncertain entries.

Corrupt or incomplete journal state, unknown exchange states, unresolved protection, missing symbol mapping, or daily-loss ledger failures halt new entries and require operator review. Confirmed stop-loss exits are recorded idempotently in the append-only daily-loss ledger using planned risk as a conservative loss estimate; this is not a substitute for exact realized P&L.

The risk-context provider treats any non-zero non-USDT Spot balance as an unmanaged holding. This conservative rule blocks a new position until the holding is reviewed.

## Emergency boundary

A partial entry fill is explicitly classified as `UNPROTECTED_PARTIAL_FILL`. The lifecycle does not report it as protected, does not submit another entry, persists the halt across restarts, and requires operator review. Regression tests cover this state.

The Binance lifecycle currently fails closed when protection cannot be confirmed. It halts new entries and reports that operator action is required. **Automatic market flattening of an unexpected filled-but-unprotected Binance Testnet position is not yet implemented.** Do not treat the Binance route as fully end-to-end accepted until that emergency path is implemented and tested.

The separate cTrader demo engine does include emergency close handling for bot-owned positions found without protective SL/TP, and closes bot-owned positions when its daily-loss stop is reached. That cTrader capability does not apply to Binance.

## Verification status

The latest completed CI and Android debug APK workflows passed on commit `01a360b96a99994cc4ccd3fa6c98c1bfbd3f27df`. A further partial-fill regression-test commit has since been added; its CI and APK workflows must pass before that newer commit is considered verified. These are build and automated-test results; they do not prove a real Binance Testnet order has been placed or that the complete exchange lifecycle has been accepted.

No Binance Testnet order has been placed by this implementation. Actual demo-order verification requires the user to enable the Testnet switch in the Android app and use a valid Binance Spot Testnet key with Spot trading permission. No production keys or live orders are part of this route.

Bitget and HTX remain public market-data sources in the agreed scope. Their private/demo execution adapters are not prerequisites for this release stage. cTrader remains a separate demo route and still requires trading-scope authorization before a broker-confirmed demo-order test.

Live-money trading remains locked.
