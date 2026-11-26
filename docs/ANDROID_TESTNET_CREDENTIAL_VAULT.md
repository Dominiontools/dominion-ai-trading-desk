# Android Testnet Credential Vault

The Android app provisions a native-only credential vault. Binance Spot Testnet API key and secret are encrypted with an AES-256 Android Keystore key using AES-GCM; the ciphertext and IV are stored in private app preferences.

The Capacitor bridge exposes save, status, and clear operations. It does not expose a read/decrypt method to JavaScript, does not log credentials, and does not sync them to a server. Clearing credentials also deletes the Keystore key.

## Credential entry and account verification

The current development-branch Android UI includes a **BINANCE SPOT TESTNET CREDENTIALS** panel with:
- **Binance Spot Testnet API key** and **Binance Spot Testnet API secret** password fields.
- **Save encrypted credentials** to store them in Android Keystore.
- **Check Testnet account** for a signed, read-only account and permission check.
- **Clear credentials** to remove the stored values and encryption key.

After saving, the form clears the visible secret. The account check is read-only and does not submit an order. The panel also reports environment, account type, trading permission, and withdrawal permission when the exchange responds.

These controls are in the Android app build containing the current development-branch changes. An older APK does not gain these controls automatically; it must be replaced by the new APK after the final build is completed and supplied.

## Restart recovery and execution boundary

The Android Python bundle includes the restart-safe protected-order lifecycle and risk/protection dependencies. When the foreground service restarts and Testnet credentials are saved, the native service invokes read-only reconciliation against every journaled bracket. This recovery path can query and classify existing exchange orders but cannot blindly resubmit an uncertain order.

The Android strategy loop is wired to the protected Binance Spot Testnet router. Execution is gated by all of the following:
- Explicit **Binance Testnet automation** switch, OFF by default.
- Valid saved Testnet credentials and successful signed account/risk snapshot.
- Fresh Binance quote, valid symbol filters, verified authenticated per-symbol commission rates, available USDT, one-position rule, and durable daily-loss ledger.
- BUY-only Spot strategy signal and a verified exchange-held OTOCO protective order state.

The switch can be enabled only after credentials are saved and includes an explicit confirmation. It controls simulated Binance Spot Testnet BUY orders only; it does not enable production/live trading. When enabled, the foreground service passes decrypted credentials only to the on-device Python Testnet client. Credentials are not sent to Netlify.

**Important remaining limitation:** automatic emergency market-flattening for a filled but unprotected Binance position is not implemented. If protection cannot be confirmed, the lifecycle halts new entries and requires operator review. No actual Binance Testnet order has yet been placed and verified on the user's account.

## Dashboard recovery status

On foreground-service startup, the native bridge runs read-only Binance Spot Testnet reconciliation when credentials are present. It passes a sanitized summary into the loopback dashboard status response under `binance_testnet_recovery`. The response contains only recovery status, halt state, reconciled count, unresolved count, and operator-action flag. It does not expose API credentials, order-list IDs, symbols, signed requests, or exchange payloads.

At foreground-service startup the native bridge also requests a read-only Binance account/risk snapshot. It requires `canTrade=true`, reconciles every journaled order, reads the durable UTC daily-loss ledger, and treats non-USDT Spot balances as unmanaged holdings for the one-position rule. The dashboard receives only a sanitized USDT equity/available-balance, daily-loss, open-position and journal-count summary. The snapshot client is constructed with `allow_orders=False`; this startup check cannot place, cancel or amend orders.

## Explicit Testnet automation permission

The Android app includes a separate Binance Spot Testnet automation switch. It is OFF by default and cannot be enabled until Testnet credentials are saved. The preference is stored locally and is not a secret. When enabled, the foreground service decrypts the saved credentials from Android Keystore and passes them only to the on-device Python Testnet client. The client is pinned to the Binance Spot Testnet host and still requires its independent constructor/environment gates.

Turning the switch off and restarting the service prevents new entries; already submitted exchange-hosted stop-loss/take-profit orders remain on Binance until their exit condition is reached. Live-money trading remains disabled.
