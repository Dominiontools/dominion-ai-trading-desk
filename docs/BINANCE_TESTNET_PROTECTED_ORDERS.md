# Binance Spot Testnet protected-order lifecycle

The testnet adapter now supports Binance's OTOCO order-list endpoint. The
working entry is a BUY LIMIT with **FOK** time-in-force. The pending exits are
a SELL LIMIT_MAKER take-profit and a SELL STOP_LOSS_LIMIT stop-loss, submitted
as one OTOCO list. Binance Testnet documents OTOCO at
`POST /api/v3/orderList/otoco`; pending OCO legs activate only after the
working order is fully filled.

## Safety behavior

- The client remains fixed to `https://testnet.binance.vision`.
- Both gates are required: constructor `allow_orders=True` and
  `DOMINION_ENABLE_BINANCE_TESTNET_ORDERS=YES`.
- The risk router accepts only its pre-validated BUY plan and submits a FOK
  entry with both protective legs attached in the same OTOCO request.
- FOK is used so a resting partial entry cannot leave an open partial fill.
  If the exchange nevertheless reports `PARTIALLY_FILLED`, the lifecycle
  classifier reports `UNPROTECTED_PARTIAL_FILL` and requires immediate action.
- A successful placement response is **not** proof of protection. The entry
  and both child orders must be queried separately. The state is PROTECTED
  only after the entry is FILLED and both exit legs are confirmed NEW.
- A pending-new response, missing child, rejected child, or unknown status
  remains `PROTECTION_UNCONFIRMED`; never count it as a protected position.
- A stop-limit can fail to execute during a fast gap. OTOCO does not guarantee
  a stop-loss fill or cap realized losses.

## Still not connected or verified

This module is not yet wired to the Android service or UI, and no testnet
credentials or orders have been used. Symbol filters and actual account-tier
fees are still caller-supplied and must be fetched/verified. Credential entry
and secure Android storage, automatic polling/reconciliation, emergency
handling, and a full authorized testnet lifecycle test remain outstanding.
Bitget and HTX order adapters are not implemented. Live trading remains locked.
