# cTrader Cloudflare port: dependency and safety review

Reviewed on 2026-11-27 from the existing cTrader service source. This is an engineering
checkpoint, not a claim that cTrader has been migrated or tested against a broker.

## Existing behavior that must be preserved

### OAuth callback

The current callback:
- Starts separate `view-only` and `trading` authorization flows.
- Uses the exact registered Netlify redirect URI and a 10-minute, one-time browser state.
- Exchanges the authorization code with the cTrader token endpoint.
- Verifies application authorization, requested permission scope, and an account whose
  `isLive` flag is explicitly false using the cTrader demo Open API.
- Encrypts access and refresh tokens with AES-256-GCM using a 32-byte base64 key.
- Stores view-only and trading tokens/status separately.
- Does not place an order during authorization.

A Cloudflare port must use a newly registered callback URI only after the new callback is
implemented and reviewed. Never change the Spotware redirect URI or existing Netlify callback
as part of this branch work.

### Status endpoint

The existing status endpoint:
- Reads the separate view-only or trading token record.
- Decrypts tokens only on the server.
- Re-verifies the cTrader demo account and permission scope when a status record is missing.
- Returns only safe connection metadata; it never returns tokens.
- Uses a strict origin allowlist for browser CORS.

### Engine control and execution

The control endpoint requires an HMAC signature, a recent timestamp, a unique nonce,
explicit confirmation before enabling demo automation, and a verified trading-scope demo
authorization. It validates profile, threshold, symbols and risk limits. Defaults are
disabled, 0.5% maximum risk per trade, 2% daily loss limit and one open position.

The execution cycle is a large dependency graph (approximately 48 KB in the current source)
that includes broker session handling, symbol metadata, sizing, protected order placement,
position monitoring, partial close, emergency close and recovery. The scheduled trigger is
one minute, not a high-frequency execution loop.

## Cloudflare port blockers

1. The Worker currently has no D1 binding or database ID. The D1 schema exists in source,
   but no database has been provisioned or migrated.
2. The existing encrypted token format is documented as AES-256-GCM, but ciphertext must
   not be copied until the exact key and record compatibility are confirmed through a
   secure migration procedure.
3. The cTrader service uses a long-lived outbound WebSocket session. Cloudflare Workers
   runtime support, session lifetime, execution limits and broker protocol compatibility
   must be tested before moving the execution cycle.
4. The current dashboard still calls the old Netlify URLs. Those URLs must remain in place
   until the Cloudflare replacements pass end-to-end checks.
5. The old Netlify Blob store and both Netlify projects are preservation-only. No deletion,
   overwrite, credential rotation or redeployment is part of this work.

## Next safe implementation sequence

1. Add and verify a Cloudflare D1 binding in a non-production environment, then apply
   `0001_initial_schema.sql`. The isolated D1 helper now includes atomic lease acquisition,
   owner-checked renewal, owner-checked release, and one-time request nonce insertion
   for replay protection; these are tested with a mocked D1 API,
   not yet against a provisioned Cloudflare database.
2. Implement atomic one-time OAuth state consumption and AES-GCM token encryption/decryption
   using Worker Web Crypto APIs.
3. Implement callback and safe status routes without exposing tokens; test with mocked cTrader
   responses before a real OAuth attempt.
4. Verify the cTrader WebSocket feasibility independently. If the Worker runtime cannot
   reliably host the session, keep the broker execution service on a suitable persistent
   runtime rather than forcing it into a Worker.
5. Port engine control only after the secure storage and replay-protection layer is verified.
6. Keep scheduled execution disabled until the user explicitly enables demo automation.
7. Do not merge or deploy to the production branch until the user approves the final release.


## Runtime finding: broker WebSocket must be reconnectable

Checked against Cloudflare's current Workers documentation on 2026-11-27:

- Workers support WebSocket connections, but runtime updates can terminate existing
  connections; Cloudflare explicitly requires clients to reconnect and restore state.
- A plain Worker isolate does not provide durable process state for a broker session.
- Durable Objects are the preferred Cloudflare primitive for reliable long-lived WebSocket
  coordination. However, outbound WebSockets do not use the WebSocket hibernation API; an
  open outbound connection prevents Durable Object eviction for up to 15 minutes, and
  subsequent I/O can extend its in-memory lifetime.
- Cron Trigger and Durable Object Alarm invocations have a 15-minute wall-time limit.
  An HTTP request can remain active while its client remains connected, but this is not a
  substitute for a fault-tolerant background trading process.

Engineering decision:

1. Do not run the cTrader trading loop as an ordinary request handler or rely on one
   in-memory Worker WebSocket surviving indefinitely.
2. Prototype the cTrader broker connection inside a Durable Object, with explicit
   heartbeat, reconnect/backoff, broker re-authentication, state reconstruction from D1,
   duplicate-order protection and a fail-closed disconnect state.
3. Test broker disconnects, Worker runtime restarts, Durable Object eviction, stale quotes,
   and duplicate scheduler delivery before any demo order is permitted.
4. If the prototype cannot meet broker-session reliability and execution timing, retain
   the cTrader execution process on a persistent runtime and use Cloudflare for the
   stateless API, OAuth callback, encrypted storage and dashboard routing.

This is a design decision based on platform documentation, not proof that the cTrader
Open API session has passed a live connectivity test. No broker connection or order was
attempted by this review.


## Control authentication prototype

Added `src/cloudflare/ctrader-control-auth.js` as a Worker-native Web Crypto verifier for
the existing control request signature format:
`HMAC-SHA256(secret, timestampText + "." + nonce + "." + rawBody)`.
It rejects malformed or stale timestamps, malformed UUID-style nonces, weak/missing
secrets, oversized request bodies and invalid signatures. Tests cover valid signatures,
tampering, stale requests and malformed headers.

This helper does not consume or persist a nonce, parse/validate the control JSON, read
environment secrets, check cTrader account status, or enable automation. The route must
call the D1 one-time nonce primitive after signature verification and before processing
the request, then apply all existing demo-only/risk/explicit-confirmation checks. No
control route has been connected and no engine setting can be changed through this helper.


## OAuth URL and token validation primitives

Added `src/cloudflare/ctrader-oauth.js` with two isolated helpers:

- Builds the cTrader authorization URL for either view-only (`accounts`) or trading scope.
- Requires the redirect URI to be HTTPS, same-origin with the Worker request, and exactly
  `/api/ctrader/oauth/callback`; it rejects open redirects and malformed state.
- Validates the token exchange response before encryption or persistence, including both
  access and refresh tokens and a positive expiry.

Tests cover both access modes, callback-origin/path validation, malformed state, and
incomplete/error token responses.

These are primitives only. No OAuth start or callback route is enabled yet, no cTrader
credentials are configured in Cloudflare, and no authorization request has been sent.
The callback URI must be registered in the Spotware app only after the complete callback
route is implemented and reviewed. The old Netlify redirect remains unchanged.
