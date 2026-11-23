# Android app

The web dashboard is packaged as an Android application with Capacitor. The same build can also be installed as a Progressive Web App (PWA) from a supported Android browser when hosted over HTTPS.

## App identity

- Name: Dominion AI Trading Desk
- Android application ID: `com.dominion.aitradingdesk`
- Capacitor web output: `dist/`

## Local development

1. Install Node.js 20 or newer and Java 17.
2. Run `npm install`.
3. Run `npm run build`.
4. Run `npx cap add android` once to generate the Android project.
5. Run `npm run android:sync`.
6. Open Android Studio with `npm run android:open`, or build a debug APK from the Android project.

## GitHub Actions

The Android workflow builds a debug APK and uploads it as a workflow artifact. It does not publish to Google Play or deploy the website.

## Current limitations and safety

- The dashboard currently contains illustrative sample values; they are not live broker prices or account balances.
- cTrader account authentication and live market data are not yet connected to the mobile UI.
- Order placement remains disabled. The app is a control/dashboard shell, not an active trading terminal.
- Keep broker credentials and tokens on the secure backend. Never put them in the mobile app or source code.
- Demo/paper mode remains the default. Do not enable live trading without explicit user approval and a separately reviewed implementation.
