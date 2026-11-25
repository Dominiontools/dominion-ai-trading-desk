# GMGN integration — official access and release gates

GMGN is a requested source for the Crypto division, especially token discovery, trending tokens, token information, contract/security checks, holder/trader analysis, and wallet activity.

## Approved integration route

Use GMGN's official Agent API / GMGN Skills rather than reverse-engineered website endpoints or unofficial scraping.

Official documentation:
- Agent API: https://docs.gmgn.ai/index/gmgn-agent-api
- GMGN Q&A and data API availability: https://docs.gmgn.ai/index/q-a
- Solana Trading API application: https://docs.gmgn.ai/index/cooperation-api-integrate-gmgn-solana-trading-api

The official Agent API describes token information/security, market candles, trending lists, wallet portfolio/activity and swap workflows. GMGN directs users to create an API key through its official AI page. Its Q&A separately says the general data-crawling API is not openly available and requires a partner IP-whitelist application. These are distinct access routes and must not be confused.

## Request-rate protection

The current connector is paced for GMGN's documented Free-plan bucket: Trenches (weight 2) and trending (weight 3) refresh together every five minutes; between refreshes, at most one token-security request (weight 1) is sent per agent cycle. API errors trigger a cooldown, and a plan-upgrade-required response disables further requests until the service is restarted after access is changed. Do not increase these request rates without checking the user's actual GMGN plan.

## What is not connected yet

- No GMGN API key or approved data access has been supplied/configured for Dominion.
- No GMGN wallet/API trading permission has been verified.
- No GMGN swap, sniper, or copy-trading order route is enabled.
- Current token discovery uses DEX Screener, GeckoTerminal, GoPlus (supported EVM chains only), and public RSS as separate sources. These are not GMGN data and must not be labelled as GMGN-connected.

## Integration requirements

1. Obtain GMGN API access through the official GMGN account process.
2. Confirm which chains and read endpoints are enabled for that key.
3. Add the credential only to the secure server/native credential vault, never to browser storage or Git.
4. Implement a read-only connector first: Trenches token discovery, trending data and documented token-security fields. The current connector also extracts parsed Solana Trenches candidates and routes GMGN security responses into the Rug agent. Pool, holder/trader, wallet activity and K-line endpoints remain available in the client but are not yet wired into agent workflows.
5. Normalize source timestamps and chain/address identifiers; reject stale, missing, unsupported or contradictory evidence.
6. Keep GMGN as an independent evidence source. A GMGN security label is not a guarantee and must not override failed safety checks from other sources.
7. Only after read-only integration tests pass should a separate demo/test wallet execution design be reviewed. No GMGN swap or live-wallet order is enabled by this document.

## Safety

- Never request or store wallet withdrawal permission.
- Never ask the user to send private keys or API secrets in chat.
- Do not use reverse-engineered endpoints or browser scraping as a production substitute for official access.
- Do not claim GMGN is connected until the API credential, supported endpoints and live read-only responses are verified.
