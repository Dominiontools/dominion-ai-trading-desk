# Android Testnet Credential Vault

The Android app now provisions a native-only credential vault. Binance Spot Testnet API key and secret are encrypted with an AES-256 Android Keystore key using AES-GCM; the ciphertext and IV are stored in private app preferences.

The Capacitor bridge exposes save, status, and clear operations. It does not expose a read/decrypt method to JavaScript, does not log credentials, and does not sync them to a server. Clearing credentials also deletes the Keystore key.

**Important limits:** this is secure local storage groundwork, not an exchange connection. The stored values are currently used for a read-only account summary only; there is no credential-entry screen yet, and no Testnet request or order has been made. The Android Python bundle now includes the restart-safe protected-order lifecycle module and its risk/protection dependencies, but the native bridge still does not invoke that lifecycle for order execution. Testnet order routing remains disabled until account, symbol filters, fees, risk plan, and protected order lifecycle are wired and verified. Use Testnet-only API keys with withdrawals disabled.
