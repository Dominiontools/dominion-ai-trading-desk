# Local read-only API bridge

The crypto paper monitor now has a small standard-library HTTP bridge for a
local dashboard or a later Android integration.

## Start the bridge

Create the server from the application process with the same JSONL decision
log path used by `CryptoPaperMonitor`:

```python
from engine.crypto_api import create_server

server = create_server(
    "data/crypto_decisions.jsonl",
    status_provider=lambda: {
        "engine": "running",  # derive this from the actual monitor lifecycle
        "poll_interval_seconds": 5,
    },
    host="127.0.0.1",
    port=8766,
)
server.serve_forever()
```

This example only starts the read-only HTTP server. It does not start the
monitor. The caller must manage monitor lifecycle separately and must shut
down both components cleanly.

## Read-only endpoints

- `GET /health` — liveness and fixed paper-only guardrails.
- `GET /api/crypto/status` — status supplied by the local application.
- `GET /api/crypto/decisions?limit=50` — newest valid JSONL decision records
  (limit is clamped to 1–100).

All responses state `mode=PAPER_ONLY` and `orders_enabled=false`.
POST, PUT and DELETE are rejected. There are no endpoints for credentials,
wallets, exchange accounts, monitor start/stop, or order placement.

## Security and integration limits

- The server refuses any bind address other than `127.0.0.1`. It is not a
  LAN or internet service and is not suitable for remote access.
- No CORS headers are enabled. A separately hosted HTTPS website cannot
  simply fetch this HTTP loopback endpoint; browsers may block it due to
  origin and mixed-content rules.
- The next Android integration must run this service inside a controlled
  local app process (or use a deliberately designed authenticated native
  bridge). Do not expose this port publicly or add permissive CORS as a
  workaround.
- The API reads decisions only. It does not launch the scanner, authenticate
  exchanges, or submit trades.
- The monitor still needs verified fee configuration before it will evaluate
  arbitrage opportunities. Public REST snapshots are not a low-latency
  execution feed and no profitability is implied.
