# cTrader control configuration validator

`src/cloudflare/ctrader-control-config.js` is a pure, Cloudflare-compatible
validator extracted from the existing Netlify control endpoint's policy.

It enforces the required enabled flag, explicit confirmation before enabling,
supported profiles, score threshold 1–15, boolean session filter, per-trade
risk 0.05–0.5%, daily loss 0.5–2%, and a normalized 1–20 symbol watchlist.
Omitted settings inherit the prior stored configuration; defaults remain
intraday, score 6, session filter on, 0.5% risk, 2% daily loss, and
XAUUSD/EURUSD/GBPUSD. The helper labels its resulting configuration demo-only.

This module does not authenticate requests, consume replay nonces, read or
write D1, verify cTrader authorization, enable automation, connect to a broker,
or place orders. A future Worker route must perform those checks independently
and remain fail-closed. The existing Netlify endpoint and production deployment
are unchanged.
