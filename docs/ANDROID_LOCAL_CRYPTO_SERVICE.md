# On-device crypto paper monitor

The Android build bundles a Python runtime and the paper market-data engine.
The user starts and stops it from the Crypto / Cross-Exchange panel; Termux is
not required for this embedded build.

## Start the engine

1. Install the current debug APK on the Android phone.
2. Open Dominion AI Trading Desk.
3. In **Crypto / Cross-Exchange**, tap **Start phone engine**.
4. Allow notifications if Android asks. A persistent notification indicates
   that the foreground service is active.
5. Keep mobile data or Wi-Fi connected. The panel connects to the local
   read-only API at `http://localhost:8766` and displays the latest public
   exchange quote snapshots and scanner decisions.
6. Tap **Stop** when you want the monitor to stop.

The default pairs are BTCUSDT and ETHUSDT. The monitor polls public REST
endpoints from Binance, Bitget and HTX approximately every five seconds. This
is not WebSocket streaming or high-frequency trading.

## Samsung background settings

For longer paper-monitor sessions, set the app's battery usage to **Unrestricted**
in Android Settings > Apps > Dominion AI Trading Desk > Battery, if that
setting is available. Keep notifications enabled. Android can still stop
background work under severe resource pressure; force-stopping the app, turning
off the phone, or losing internet will stop useful monitoring. After a reboot
or force-stop, open the app and start the engine again.

## Fee configuration

The scanner intentionally does not guess exchange fees. Until you verify your
own account's current taker fees, the engine still records public quotes but
marks scans `BLOCKED / FEE_CONFIG_MISSING`. The current in-app build does not
yet expose fee editing; do not add unverified fee values merely to make the
scanner report opportunities.

The scanner's provisional 5 bps slippage assumption is not a guaranteed fill
cost and is not sufficient for live execution.

## Safety and current limitations

- Public market data only. No exchange account keys, wallet access, deposits,
  withdrawals, or order endpoints are included.
- No live or demo orders are sent. Order routing is disabled in code.
- REST top-of-book snapshots only; full depth and executable fill simulation
  are not implemented.
- The scanner records paper decisions only and blocks when fee configuration
  is missing, the snapshot is incomplete, or the data is invalid/stale.
- The local API binds only to `127.0.0.1`, exposes read-only GET routes, and
  must never be exposed to the public internet.
- cTrader/Pepperstone is not connected to this Android service yet.

## Directional crypto paper strategy and persistent paper book

The embedded Android service also runs a 10/30 SMA crossover strategy using
completed Binance Spot 1-minute candles. It requests 80 klines and discards the
currently forming candle; signals are blocked if the latest completed candle
is older than two minutes or if the quote is stale. A candidate is sized from
the configured $20 paper equity and 0.5% maximum risk, with a 1% initial stop,
2:1 target, $20 notional cap, spread/slippage gates, and one open position.

The paper book writes entry, hold, blocked-entry and exit events to
`paper_trades.jsonl`. On engine restart it restores realized P/L and any
unclosed paper position from that journal, so the EXIT agent can continue
monitoring it. The dashboard exposes paper equity, realized P/L, daily loss,
open-position status and SMA strategy status.

This is still PAPER_ONLY. The directional strategy is a baseline example, not
a claim of profitability or a full implementation of every strategy in the
user's strategy guide. It uses public REST candles and a single Binance quote,
not a WebSocket stream. The separate arbitrage monitor remains analysis-only;
an arbitrage price gap is never converted into a one-sided directional trade.

## Remaining integration checklist

The phone API now exposes a structured readiness checklist. It distinguishes:
- Phone installation and real-device validation (user must confirm on the handset).
- Spotware approval of the existing cTrader application (external approval).
- Pepperstone demo authorization (requires approval and the user's account authorization).
- Actual cTrader demo order, stop-loss, take-profit and close-position verification.
- Exchange testnet authorization and test-order verification.
- Verified exchange fee configuration.
- Connecting all specialist agents to validated execution and exit workflows.
- Live-money trading, which remains locked pending separate explicit approval.

The checklist does not infer approvals, credentials, test results or successful orders. It reports these as outstanding until the corresponding integration is explicitly verified. The Android APK still has no exchange-account order capability and no cTrader broker-order route.
