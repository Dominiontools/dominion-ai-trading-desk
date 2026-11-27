# cTrader demo engine status store

`src/cloudflare/ctrader-engine-status-store.js` provides a D1 singleton read/write helper for a future Cloudflare status endpoint.

- Persists only allowlisted status/reason values and bounded public metadata.
- Requires the snapshot to be explicitly `environment: "demo"` and forces `liveTradingEnabled: false`.
- A connected snapshot must carry the explicit `isLive: false` verification marker and a recognized access mode.
- Reads fail closed for malformed, live-looking, or unknown stored records.
- Returned status excludes account IDs, tokens, and other private fields.
- Missing status returns a disconnected `NOT_CONFIGURED` default.

This is a persistence helper only. No Worker route reads or writes it yet; no cTrader account has been connected; no broker heartbeat is being received; and no real Cloudflare D1 database has been provisioned or integration-tested. Tests use a mocked D1 interface.
