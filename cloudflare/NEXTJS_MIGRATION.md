# Next.js + Cloudflare migration

## Target architecture

- One Next.js App Router application owns the dashboard and backend route handlers.
- Cloudflare Workers runs the Next.js server output through `@opennextjs/cloudflare`.
- Cloudflare D1 stores durable cTrader state; API credentials and encryption keys are Cloudflare runtime secrets.
- GitHub stores source and CI only. It must never contain broker credentials, exchange API keys, OAuth secrets, or production tokens.
- The Android crypto scanner remains a phone-local service for continuous market feeds and Binance Spot Testnet execution. It will communicate with authenticated Next.js API routes; it is not moved into a request-lifecycle Worker.

## Migration status

1. [x] Add the Next.js App Router shell around the existing dashboard.
2. [x] Add the OpenNext Cloudflare adapter and Worker build configuration.
3. [x] Add the first Next.js health route; cTrader OAuth/status routes remain to be ported.
4. [ ] Port cTrader OAuth and status routes into Next.js route handlers.
5. [ ] Port cTrader configuration, control authentication, durable order recovery, and execution services.
6. [ ] Connect the Android bridge to the authenticated Next.js API contract.
7. [ ] Validate the cTrader session lifecycle and phone crypto relay end to end.
8. [ ] Configure Cloudflare D1 and secrets only after source and tests are ready.
9. [ ] Obtain explicit approval before the one final production deployment.

## Android compatibility

The existing Capacitor/Vite build is retained temporarily as a compatibility build while the Next.js server application is migrated. `npm run build:legacy` and `npm run android:build-web` are transitional only; the production web application build is `npm run build` (Next.js). Do not remove the legacy entry point until the native bridge has a verified Next.js-compatible packaging strategy and an APK smoke test.

## Deployment safety

The `deploy` script is intentionally not used by CI. GitHub Actions only installs dependencies, runs tests, and builds the Next.js app. No Cloudflare deploy, D1 migration, Netlify deploy, or broker order is performed by this migration.
