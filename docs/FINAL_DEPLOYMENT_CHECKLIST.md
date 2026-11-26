# Final coordinated deployment checklist

This checklist records the original coordinated release requirements and the current post-release acceptance gates. The main dashboard production deployment was completed on 2026-11-26 (Netlify deploy ID: `6b082fd0437d2e6b804faf9`). Do not redeploy, change production branches, or trigger another production build without the user's explicit approval.

## Netlify projects

### Existing account — cTrader backend
- Project: `dominion-ai-trading-desk-p7cp`
- Site ID: `c6f3a9e8-24b3-483f-a084-58400e569983`
- Base directory: `ctrader-auth-service`
- Build command: `echo 'Building Dominion cTrader demo service'`
- Publish directory: `public`
- Functions directory: `netlify/functions`
- Preserve the existing cTrader callback URL:
  `https://dominion-ai-trading-desk-p7cp.netlify.app/.netlify/functions/ctrader-callback`

### Main dashboard
- Project: `dominion-ai-trading-desk-new`
- Site ID: `7b1a5e86-dea3-4a67-9795-f58c1ae133a6`
- Production URL: `https://dominion-ai-trading-desk-new.netlify.app`
- Base directory: repository root
- Build command: `npm run build`
- Publish directory: `dist`
- Functions directory: `netlify/functions`
- Keep **Require SSO team login** enabled for all deploys.

The old `dominion-ai-trading-desk-r30v` project is not part of the current two-site production path.

## Environment variables

The cTrader backend must retain:
- `CTRADER_CLIENT_ID`
- `CTRADER_CLIENT_SECRET`
- `CTRADER_TOKEN_ENCRYPTION_KEY`

The coordinated two-site design requires the same random secret as a **secret** environment variable in both projects:
- `DOMINION_CONTROL_API_SECRET`

The secret must be available to Functions/runtime. Do not put it in frontend build variables, source code, GitHub files, chat messages, browser storage or logs. The automated environment-variable update was denied by Netlify permissions; confirm its configuration in both projects before relying on cross-site control endpoints.

## Original coordinated release sequence

1. Confirm all GitHub Actions checks pass on `feat/complete-demo-trading-engine`.
2. Complete code, dependency, OAuth, CORS, access-control and security review.
3. Verify the old account still contains the encrypted view-only cTrader token record.
4. Configure `DOMINION_CONTROL_API_SECRET` in both Netlify projects (Functions/Runtime scope).
5. Confirm the backend and dashboard build settings above.
6. Configure both projects against the completed branch without triggering a premature production build.
7. Obtain explicit user approval before a coordinated production deployment.
8. Verify the dashboard can read the backend's view-only and trading status endpoints without placing a trade.
9. Confirm the exact p7cp callback URI is registered in the Spotware developer application; complete separate cTrader demo trading authorization only after Spotware grants the required permission.
10. Reconcile the demo account read-only first. Demo automation requires a separate explicit user action.

## Current post-release acceptance gates

- Latest CI run `45855394008`: Python safety tests, dashboard build, Netlify Functions bundle check, cTrader risk tests and generated Android Java bridge compilation all passed. The live-public-market smoke test was skipped because it is opt-in.
- The crypto Android service contains a Binance Spot Testnet-only, BUY-only protected OTOCO execution path behind an OFF-by-default switch. This does not authorize live trading and does not mean an end-to-end Testnet order lifecycle has been verified.
- The Android native emergency-close bridge compiles, but it has not yet been exercised on a physical device. No emergency-close Testnet order has been submitted.
- cTrader remains a separate Forex/Gold path. Saved authorization is view-only; trading-scope authorization and Pepperstone demo lifecycle tests remain outstanding.
- HTX remains excluded from fee-adjusted net calculations until its official public Spot maker/taker fee row can be verified. Its fee page currently requires login.
- The Android workflow is manual-only. No APK has been built from this release candidate.

## Hard safety conditions

- Do not replace or delete the existing view-only cTrader token.
- Do not place an order during deployment or connection verification.
- Binance execution is Testnet-only and requires explicit in-app enablement; live-money trading and withdrawals remain locked.
- cTrader scheduled execution remains disabled by default and demo-only.
- If any required test, permission, account, commission, symbol rule, balance, quote, margin or protective-order check fails, trading must fail closed.
- Do not build/deliver an APK or redeploy until the remaining review and acceptance gates are complete and the user explicitly approves that action.
