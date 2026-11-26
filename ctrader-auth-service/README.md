# Dominion cTrader Demo Trading Service

This directory contains the complete cTrader/Pepperstone demo backend: OAuth callback, account-status verification, authenticated automation controls, scheduled demo execution cycle, background worker, risk controls, and position-management helpers.

## Final Netlify configuration

Use the existing Netlify project:

- Project: `dominion-ai-trading-desk-p7cp`
- Site URL: `https://dominion-ai-trading-desk-p7cp.netlify.app`
- Base directory: `ctrader-auth-service`
- Netlify config: `ctrader-auth-service/netlify.toml`
- Functions directory (relative to the base directory): `netlify/functions`
- Production branch: `feat/complete-demo-trading-engine` only after the user approves the single final release.

The dashboard already calls this site's callback, status, and demo-engine endpoints. Do not point the callback at a different Netlify hostname: OAuth initiation, callback handling, and the encrypted production Blob store must remain on this same site.

The registered Spotware redirect URI must exactly match:

`https://dominion-ai-trading-desk-p7cp.netlify.app/.netlify/functions/ctrader-callback`

Confirm that this exact URI is registered in the Spotware application before the final OAuth test. Do not change the existing redirect registration or trigger a deploy without the user's approval.

## Required production environment variables

Set these in the existing site's Netlify environment settings, with Functions/Runtime scope and secret protection:

- `CTRADER_CLIENT_ID`
- `CTRADER_CLIENT_SECRET`
- `CTRADER_TOKEN_ENCRYPTION_KEY` — base64-encoded 32-byte random key.
- `DOMINION_CONTROL_API_SECRET` — shared HMAC secret used by the dashboard proxy and scheduled worker.

Preserve the existing production values and the existing Blob store named `dominion-ctrader-oauth-prod`. The view-only token record must not be overwritten when trading authorization is added; trading tokens and status use separate keys.

## Safety and acceptance

- cTrader execution is demo-only and must verify the Pepperstone account is a demo account.
- Demo automation defaults to disabled and requires separate trading-scope authorization plus explicit user enablement.
- Live-money trading remains disabled in code.
- Verify callback continuity, read-only status, trading-scope status, order entry, broker-confirmed stop-loss/take-profit, partial close, restart recovery, and emergency close against the demo account before acceptance.
- No trade should be placed during OAuth authorization.
- A scheduled cycle runs once per minute; it is not a seconds-level WebSocket engine.
