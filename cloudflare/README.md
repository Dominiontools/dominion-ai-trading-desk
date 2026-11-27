# Cloudflare migration plan

This directory contains the Cloudflare replacement work for Dominion AI Trading Desk.
All migration work is developed on the separate `cloudflare-backend-migration` branch. The production Cloudflare project remains connected to `cloudflare-deploy`. The existing Netlify projects,
deployments, environment variables, and Blob records are preservation-only until the
Cloudflare replacement passes acceptance tests and the user approves the single final cutover.

## Cloudflare build configuration

The connected Cloudflare Worker project is configured with:
- Production branch: `cloudflare-deploy`
- Build command: `npm run build`
- Deploy command: `npx wrangler deploy`
- Root directory: `/`
- Worker static assets: `./dist` (from `wrangler.jsonc`)

The package build script runs the TypeScript application check followed by the Vite production
build. Keep the command exactly as `npm run build` (without punctuation). A push to this
branch can trigger Cloudflare's connected Git build; do not push merely to test repeatedly.

## Deployment isolation

Migration commits and CI runs are restricted to `cloudflare-backend-migration`. They do not
trigger the production Cloudflare deployment, which remains connected to `cloudflare-deploy`.
No deployment is authorized until the user approves the final cutover.

## Service boundaries

- `/api/ctrader/callback`: OAuth callback and authorization-code exchange.
- `/api/ctrader/status`: verify the selected Pepperstone demo account and expose safe status.
- `/api/ctrader/engine/status`: report engine state without exposing credentials.
- `/api/ctrader/engine/control`: authenticated dashboard control; automation remains disabled by default.
- `/api/ctrader/engine/run`: authenticated scheduled execution entrypoint.
- Cloudflare Cron Trigger: invokes the scheduled execution cycle at the existing one-minute cadence.

## Storage migration

The current Netlify service stores OAuth state, encrypted view-only and trading token records,
engine configuration, engine status/events, replay nonces, and execution locks in the
`dominion-ctrader-oauth-prod` Blob store.

The Cloudflare replacement must use a separate Cloudflare storage namespace (D1 for structured
records and atomic uniqueness/leases, with secrets in Worker secrets). It must NOT point at,
overwrite, or delete the Netlify Blob store. Existing encrypted token ciphertext is not assumed
portable until the encryption format and key are verified. Preserve the separate view-only and
trading token records.

Required D1 records: oauth_states, ctrader_tokens, engine_config, engine_status, engine_events,
request_nonces, and execution_locks. OAuth state and nonce records require expiry and one-time
consumption semantics. Execution locks require atomic acquisition and expiry.

## Security and trading safety

- Keep the cTrader demo WebSocket endpoint hard-coded; reject live account identifiers.
- Preserve OAuth state validation, secure HttpOnly cookies, exact redirect URI checks, and
  separate view-only versus trading authorization.
- Use Web Crypto HMAC verification and constant-time comparison for signed internal requests.
- Never return access/refresh tokens, encryption keys, or raw broker payloads to the browser.
- Keep scheduled automation disabled by default and require explicit dashboard enablement.
- Keep live trading disabled; do not add production trading endpoints.
- Do not place an order during OAuth, status verification, or migration.
- Keep the one-minute schedule; do not claim high-frequency execution.

## Migration sequence

1. Inventory all Netlify functions, imports, environment variables, storage keys, and scheduled
   behavior. No production writes.
2. Implement Cloudflare Worker routing and D1 schema in this branch only.
3. Port OAuth callback and status with Web Crypto and separate Cloudflare storage.
4. Port authenticated engine control and replay protection.
5. Port the scheduled worker and execution-cycle dependencies; verify outbound cTrader
   WebSocket compatibility and runtime limits before enabling any cycle.
6. Port the dashboard proxy and update API base URLs only on the Cloudflare branch.
7. Run unit/integration tests with mocked broker responses and no order placement.
8. Migrate credentials only through secure Cloudflare secret entry and a separately reviewed
   token migration procedure. Never copy secrets into Git.
9. Test demo account verification, disabled-by-default behavior, risk gates, idempotency,
   restart recovery, and emergency stop.
10. Obtain explicit user approval before the one final Cloudflare deployment/cutover.

## Known blockers to resolve before runtime implementation

- The Netlify Blob store has no automatic Cloudflare equivalent. A safe, explicit data migration
  path is required; the old store must remain intact.
- The callback currently uses the Netlify hostname as its registered redirect URI. A new
  Cloudflare callback hostname must be registered with Spotware before OAuth can move.
- The cTrader engine cycle is a large module and uses Netlify Blob APIs; its full dependency
  graph must be ported, not merely wrapped.
- Confirm Cloudflare Workers support for the cTrader outbound WebSocket flow and execution time
  requirements before moving the broker execution loop.
- The Python crypto engine is a separate migration track and is not made operational by this
  cTrader Worker.


## Session coordinator prototype

The pure policy helper in `src/cloudflare/ctrader-session-guard.js` requires an explicitly
enabled demo session, verified trading permission, a confirmed non-live account, and a fresh
broker heartbeat. It also provides bounded exponential reconnect backoff. It does not open a
broker connection or place orders. See `cloudflare/CTRADER_SESSION_GUARD.md`.

Cloudflare Durable Objects can make outbound WebSocket connections, but those connections do
not hibernate and only prevent eviction for a maximum of 15 minutes per connection. The
cTrader session design must therefore include reconnect/re-authentication and state recovery;
a permanent in-memory broker session must not be assumed. See `cloudflare/CTRADER_PORTING_NOTES.md`.


## Execution lease primitives

The D1 store helper now includes atomic execution-lease acquisition and owner-only release.
A live lease cannot be replaced before expiry; a release must present the exact lock ID.
Callers must generate lock IDs with a cryptographically secure random source, use bounded
lease durations, and fail closed if acquisition returns no lease. These primitives are not
wired to a trading cycle yet and have not been exercised against a provisioned D1 database.
