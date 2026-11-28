# Next.js + Cloudflare migration

## Target architecture

- One Next.js App Router application owns the dashboard and backend route handlers.
- Cloudflare Workers runs the Next.js server output through `@opennextjs/cloudflare`.
- Cloudflare D1 stores durable cTrader state; API credentials and encryption keys are Cloudflare runtime secrets.
- GitHub stores source and CI only. It must never contain broker credentials, exchange API keys, OAuth secrets, or production tokens.
- The Android crypto scanner remains a phone-local service for continuous market feeds and Binance Spot Testnet execution. The dashboard continues to reach it through the phone-local service; a request-lifecycle Worker is not a replacement for that persistent process.

## Migration status

1. [x] Add the Next.js App Router shell around the existing dashboard.
2. [x] Add the OpenNext Cloudflare adapter and Worker build configuration.
3. [x] Add Next.js health, cTrader OAuth start/callback, and status route handlers.
4. [x] Add Cloudflare Access JWT verification, operator-email allowlisting, same-origin checks, and D1 one-time nonce protection for cTrader settings.
5. [x] Permit saving paused demo strategy settings; enabling automation remains rejected until the Next.js execution cycle is actually connected and validated.
6. [ ] Port and connect the cTrader demo execution cycle, including broker-confirmed order reconciliation, recovery, and protected position management.
7. [ ] Connect the Android crypto bridge to authenticated Next.js API routes without moving the continuous scanner out of the phone runtime.
8. [ ] Validate the complete cTrader session lifecycle and Android crypto relay end to end.
9. [ ] Configure Cloudflare D1, Access policy, and secrets only after source and tests are ready.
10. [ ] Obtain explicit approval before the one final production deployment.

## Cloudflare Access requirements for cTrader settings

The control route fails closed unless these runtime variables are configured in Cloudflare:

- `CF_ACCESS_ISSUER`: the HTTPS issuer URL for the Cloudflare Access team.
- `CF_ACCESS_AUD`: the Access application's audience tag.
- `CTRADER_CONTROL_EMAIL`: the one operator email allowed to change settings.

The Cloudflare Access application must protect the dashboard and inject its signed JWT. The route independently verifies the JWT signature, issuer, audience, expiry, and allowed email. It also requires a same-origin request and a unique D1 nonce. No Access settings or secrets have been configured yet.

The control route deliberately rejects `enabled: true` with `CTRADER_EXECUTION_RUNTIME_NOT_READY`. Do not enable automation until the full execution and recovery path is connected and tested.

## Android compatibility

The existing Capacitor/Vite build is retained temporarily as a compatibility build while the Next.js server application is migrated. `npm run build:legacy` and `npm run android:build-web` are transitional only; the production web application build is `npm run build` (Next.js). Do not remove the legacy entry point until the native bridge has a verified Next.js-compatible packaging strategy and an APK smoke test.

## Validation and deployment safety

GitHub Actions runs the test suite, the Next.js production build, and the Cloudflare OpenNext build. The `deploy` script is not used by CI. No Cloudflare deployment, D1 migration, Netlify deployment, or broker order is performed by this migration.
