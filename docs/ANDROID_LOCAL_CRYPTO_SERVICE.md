# Running the local crypto paper service on Android

This is the first real market-data service for Dominion AI Trading Desk. It
fetches public top-of-book snapshots from Binance, Bitget and HTX and writes
paper-only scanner decisions. It cannot access exchange accounts, wallets,
deposits, withdrawals or order endpoints.

## Temporary phone setup (Termux)

The Android APK is currently the dashboard. The Python service must run
separately on the same phone during development.

1. Install Python in Termux and open the repository folder.
2. Install project dependencies with `pip install -r requirements.txt`.
3. Start the service with `python -m engine.crypto_service`.
4. Keep Termux running while testing the app. Android battery restrictions,
   force-stop, reboot, or loss of internet can stop the process.
5. Open Dominion AI Trading Desk. The Crypto / Cross-Exchange panel should
   connect to `http://localhost:8766` and show the most recent quote snapshot.

Default pairs are BTCUSDT and ETHUSDT, refreshed every five seconds. Configure
pairs with `DOMINION_CRYPTO_SYMBOLS=BTCUSDT,ETHUSDT` and interval with
`DOMINION_CRYPTO_INTERVAL_SECONDS=5`.

## Fee configuration

The scanner intentionally does not guess exchange fees. Until you verify your
own account's current taker fees, the service still records live quotes but
marks every scan `BLOCKED / FEE_CONFIG_MISSING`. Only after verification may
you set these environment variables in the local shell:

- `DOMINION_FEE_BINANCE_TAKER_BPS`
- `DOMINION_FEE_BITGET_TAKER_BPS`
- `DOMINION_FEE_HTX_TAKER_BPS`

Values are basis points (1 bp = 0.01%). Do not copy a fee rate from an
advertisement or another account tier. The present scanner's 5 bp slippage
assumption is provisional and is not a guaranteed fill-cost model.

## Important limitations

- REST snapshots, not WebSocket streaming or high-frequency execution.
- Top-of-book depth only; it does not yet model full order-book fills.
- Paper opportunities only. There are no exchange order adapters.
- No live or demo orders are sent by this service.
- The local API binds only to 127.0.0.1 and accepts read-only GET requests.
- Do not expose this API to the public internet.
