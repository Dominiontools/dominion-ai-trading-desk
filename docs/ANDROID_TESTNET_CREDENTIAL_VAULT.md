# Android Testnet Credential Vault

The Android app now provisions a native-only credential vault. Binance Spot Testnet API key and secret are encrypted with an AES-256 Android Keystore key using AES-GCM; the ciphertext and IV are stored in private app preferences.

The Capacitor bridge exposes save, status, and clear operations. It does not expose a read/decrypt method to JavaScript, does not log credentials, and does not sync them to a server. Clearing credentials also deletes the Keystore key.

**Important limits:** this is secure local storage groundwork, not an exchange connection. The stored values are currently used for a read-only account summary only; there is no credential-entry screen yet, and no Testnet request or order has been made. The Android Python bundle includes the restart-safe protected-order lifecycle and risk/protection dependencies. When the foreground service restarts and Testnet credentials are saved, the native service now invokes a read-only reconciliation routine against every journaled bracket. This recovery path can query and classify existing exchange orders but cannot submit, cancel, or amend orders. New order execution is still not connected to the Android strategy loop. Testnet order routing remains disabled until account, symbol filters, fees, risk plan, and protected order lifecycle are wired and verified. Use Testnet-only API keys with withdrawals disabled.


## Dashboard recovery status

On foreground-service startup, the native bridge runs read-only Binance Spot
Testnet reconciliation when credentials are present. It passes a sanitized
summary into the loopback dashboard status response under
`binance_testnet_recovery`. The response contains only the recovery status,
halt state, reconciled count, unresolved count, and operator-action flag. It
does not expose API credentials, order-list IDs, symbols, signed requests, or
exchange payloads. The local API remains read-only and always reports
`orders_enabled: false`.


At foreground-service startup the native bridge also requests a read-only
Binance account/risk snapshot. It requires `canTrade=true`, reconciles every
journaled order, reads the durable UTC daily-loss ledger, and treats non-USDT
Spot balances as unmanaged holdings for the one-position rule. The dashboard
receives only a sanitized USDT equity/available-balance, daily-loss, open-
position and journal-count summary. The snapshot client is constructed with
`allow_orders=False`; this startup check cannot place, cancel or amend orders.
