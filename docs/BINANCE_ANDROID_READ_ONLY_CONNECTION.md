# Read-only Binance Testnet account connection

The Android native bridge decrypts the saved API key and secret inside the app process, passes them directly to the embedded Python read-only account helper, and returns only a filtered account summary (permissions and non-zero asset balances). The API key, secret, request signature, and raw exchange response are never returned to the WebView.

This helper constructs the client with `allow_orders=False`. It only calls `GET /api/v3/account` on the fixed `https://testnet.binance.vision` host. It does not submit, cancel, or modify orders.

Use a Binance Spot Testnet key only. The UI should show the exchange's actual withdrawal permission; do not assume it is disabled just because the app is testnet. No real-money account is accessed.
