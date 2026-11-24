# Binance Spot Testnet adapter (development only)

The project now includes an isolated signed REST adapter for **Binance Spot Testnet**.

- Fixed host: `https://testnet.binance.vision`; production Binance hosts are rejected.
- Account query and order query are supported.
- Order placement and cancellation are limited to GTC limit orders and are disabled by default.
- Both an explicit constructor opt-in and `DOMINION_ENABLE_BINANCE_TESTNET_ORDERS=YES` are required before testnet order actions are permitted.
- Credentials are passed at runtime and are not written to the repository, journal, dashboard, or local config files.
- The adapter is not yet wired into the Android service or dashboard. No testnet credentials have been supplied and no testnet order has been sent.
- Exchange filters (tick size, lot size, min notional), actual account fee tier, balance reservations, idempotent retry/reconciliation, order-state streaming, and full stop/target orchestration must be added before end-to-end testnet automation.
- Do not reuse testnet credentials on production. Live endpoints are deliberately unsupported by this adapter.

This is a development building block, not a completed exchange integration or a claim that a strategy is profitable.
