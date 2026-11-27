# Cloudflare Worker API scaffold

This file documents the first isolated Worker entrypoint on `cloudflare-backend-migration`.
It is not deployed and does not replace either Netlify project.

## Current routes

- `GET /api/health`: reports that the Worker is reachable and explicitly reports all trading disabled.
- `/api/ctrader/*`: returns HTTP 503 with `not_migrated`; no broker credentials are read and no orders can be sent.
- `/api/crypto/*`: returns HTTP 503 with `phone_engine_required`; the Android-local Python engine remains the current market-data service.
- Other `/api/*`: returns HTTP 404.
- Non-API requests: served from the Vite `dist` assets through the Worker assets binding.

## Safety properties

- No API keys, OAuth secrets, tokens, or account data are stored in source control.
- No D1 database, KV namespace, R2 bucket, or secret binding is assumed to exist.
- No cTrader order route or exchange order route is implemented.
- Live trading and automated trading remain disabled.
- Existing Netlify projects and the Netlify Blob store are untouched.

## Dashboard integration findings

The current frontend still points cTrader status and authorization at the existing
`dominion-ai-trading-desk-p7cp.netlify.app` function URLs. Engine control also uses the
Netlify control proxy. The crypto panel calls the Android-local API at
`http://localhost:8766`. Those endpoints must remain unchanged until their Cloudflare
replacements are implemented and verified; changing the frontend now would break the
existing connections.

## Next implementation gates

1. Port the cTrader OAuth callback and read-only status flow, including exact redirect URI
   validation, one-time state, secure cookies, encryption-key handling, and demo-account checks.
2. Provision a separate Cloudflare D1 database and apply the reviewed migration. Do not reuse
   or delete Netlify Blob data.
3. Port engine control and replay protection; keep scheduled automation disabled.
4. Evaluate the cTrader execution-cycle dependency graph and Cloudflare runtime/WebSocket limits
   before attempting broker execution.
5. Keep the Android crypto engine separate until a compatible always-on runtime is selected.
6. Run tests and a staging verification before requesting approval for the one final deployment.
