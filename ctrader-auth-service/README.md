# Dominion cTrader Authorization Service

This is a separate, minimal Netlify service for cTrader OAuth callbacks. It does not host the trading dashboard and does not place orders.

## Netlify setup

- Connect this repository to the Netlify project named `dominion-ctrader-auth`.
- Select branch `feat/ctrader-auth-service`.
- Set the Base directory to `ctrader-auth-service`.
- Keep deploys protected until the callback code and environment variables are ready. The production callback must be reachable by cTrader, so public access will be enabled only after explicit approval.

## Required production environment variables

Set these in Netlify's site environment settings, with Functions/Runtime scope and secret protection where applicable:

- `CTRADER_CLIENT_ID`
- `CTRADER_CLIENT_SECRET` — use a newly rotated Spotware secret; never commit it or paste it into chat.
- `CTRADER_TOKEN_ENCRYPTION_KEY` — base64-encoded 32-byte random key.

The registered Spotware redirect URI must exactly equal:

`https://dominion-ctrader-auth.netlify.app/.netlify/functions/ctrader-callback`

Do not register or test this URI until the production callback has been deployed and verified. OAuth tokens are encrypted before storage. This callback does not expose tokens in its response and does not submit trades.
