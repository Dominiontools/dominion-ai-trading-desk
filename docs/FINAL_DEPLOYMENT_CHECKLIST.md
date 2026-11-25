# Final coordinated deployment checklist

This project follows the user's one-deployment rule. Do not connect Git, change production branches, start builds, or deploy either site until the full review is complete and the user explicitly approves the final coordinated deployment.

## Netlify projects

### Existing account — cTrader backend
- Project: `dominion-ai-trading-desk-p7cp`
- Site ID: `c6f3a9e8-24b3-483f-a084-58400e569983`
- Base directory: `ctrader-auth-service`
- Build command: `echo 'Building isolated cTrader authorization callback'`
- Publish directory: `public`
- Functions directory: `netlify/functions`
- Production branch for the final release: `feat/complete-demo-trading-engine`
- Preserve the existing cTrader callback URL:
  `https://dominion-ai-trading-desk-p7cp.netlify.app/.netlify/functions/ctrader-callback`

### New account — main dashboard
- Project: `dominion-ai-trading-desk-new`
- Site ID: `7b1a5e86-dea3-4a67-9795-f58c1ae133a6`
- Base directory: repository root
- Build command: `npm run build`
- Publish directory: `dist`
- Functions directory: `netlify/functions`
- Production branch for the final release: `feat/complete-demo-trading-engine`
- Keep **Require SSO team login** enabled for all deploys.

The old `dominion-ai-trading-desk-r30v` project is not part of the new two-site production path.

## Environment variables

The old cTrader backend must retain:
- `CTRADER_CLIENT_ID`
- `CTRADER_CLIENT_SECRET`
- `CTRADER_TOKEN_ENCRYPTION_KEY`

Create one new random secret and set the exact same value as a **secret** environment variable in both projects:
- `DOMINION_CONTROL_API_SECRET`

The secret must be available to Functions/runtime. Do not put it in frontend build variables, source code, GitHub files, chat messages or browser storage. Do not print it in logs.

## Single-release sequence

1. Confirm all GitHub Actions checks pass on `feat/complete-demo-trading-engine`.
2. Complete the code, dependency, OAuth, CORS, access-control and security review.
3. Verify the old account still contains the encrypted view-only cTrader token record.
4. Configure the shared HMAC secret in both Netlify projects.
5. Confirm the old backend and new dashboard build settings above.
6. Connect/configure the two projects to the same completed branch without triggering a premature production build.
7. Perform one coordinated final deployment of both projects.
8. Verify the new dashboard can read the old backend's view-only and trading status endpoints.
9. Complete separate cTrader demo trading authorization after Spotware grants the required permission.
10. Reconcile the demo account read-only first. The user must then explicitly enable demo automation in the dashboard.

## Hard safety conditions

- Do not replace or delete the existing view-only cTrader token.
- Do not place a trade during deployment or connection verification.
- The scheduled cTrader engine is disabled by default.
- The cTrader execution host is demo-only; live trading remains locked.
- Crypto exchange testnet order execution is not yet wired into the Android service and must not be described as active.
- If any required test, permission, account, commission, symbol rule, balance, quote, margin or protective-order check fails, trading must fail closed.
