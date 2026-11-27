# cTrader session guard prototype

This module is a small, pure policy layer for a future Durable Object or persistent
cTrader session process. It does not open a WebSocket, authenticate with Spotware,
read secrets, or place orders.

## Demo execution gate

`evaluateCTraderDemoSession` fails closed unless all of the following are true:

- Demo automation was explicitly enabled.
- The broker session is connected and authenticated.
- The account environment is exactly `demo` and `isLive` is explicitly false.
- The verified permission scope is trading (`1`).
- The broker heartbeat is no older than 15 seconds and is not from the future.
- Live trading remains explicitly disabled.

The result is a policy decision only. A future execution cycle must additionally verify
fresh quotes, symbol metadata, fee/risk limits, idempotency, execution locks, and emergency
stop state before it can submit a demo order.

## Reconnection backoff

`getCTraderReconnectDelayMs` calculates bounded exponential backoff with optional
jitter. The caller must impose a finite retry budget, persist a disconnected state, and
never continue execution while disconnected. This helper does not itself reconnect.

## Cloudflare runtime boundary

Cloudflare documents that outbound WebSockets do not use Durable Object WebSocket
hibernation. An outbound connection prevents eviction for at most 15 minutes per connection;
after that the object may again be evicted according to its lifecycle rules. Therefore this
guard is not evidence that a cTrader session can remain continuously available. The full
broker protocol, reconnection, re-authentication, and recovery still require an isolated
runtime prototype and fault-injection tests before any automation is enabled.
