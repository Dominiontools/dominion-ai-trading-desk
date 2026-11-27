# cTrader D1 engine configuration store

This isolated helper reads and writes the singleton `engine_config` row defined in
`0001_initial_schema.sql`. It validates the persisted shape, requires the demo
environment, enforces the existing 0.5% per-trade / 2% daily-loss / one-position
ceilings, and uses a parameterized singleton upsert.

The helper is not an HTTP route. It does not authenticate a dashboard request, verify a
cTrader account, consume a replay nonce, or independently authorize automation. Those
checks must happen before a caller persists a requested change. The Cloudflare Worker
currently has no D1 binding, so this module is not wired into production or invoked by
the dashboard. Tests use a mocked D1 interface; a real D1 migration and integration
test remain outstanding.
