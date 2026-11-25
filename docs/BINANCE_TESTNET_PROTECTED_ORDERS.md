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

The new BinanceProtectedLifecycle coordinator now performs a single gated
submission followed by bounded exchange reconciliation (up to four checks) to allow
transient PENDING_NEW child orders to become active. It rejects duplicate
order-list IDs within the coordinator, reports PROTECTED only when the entry is
FILLED and both exit legs are NEW, and halts additional submissions when the
result is uncertain. It can also reconcile an existing order list without
submitting another order. Unit tests cover successful protection, duplicate
submission, uncertain network outcomes and fail-closed behavior.

This coordinator is not yet wired to the Android service or UI, and no testnet
credentials or orders have been used. Symbol filters and actual account-tier
fees still need to be fetched and verified at runtime. Durable recovery across
Android process restarts, emergency flattening of any unexpected partial fill,
background reconciliation, and a full authorized testnet lifecycle test remain
outstanding. Bitget and HTX order adapters are not implemented. Live trading
remains locked.


## Restart reconciliation

The durable journal records each submitted order-list client ID together with its
symbol before the network request. On app/process restart, the recovery routine
can query every recorded OTOCO bracket without placing a replacement order.
Execution remains halted if any order cannot be matched to a symbol, if an
exchange response is uncertain, or if protection cannot be confirmed. Legacy
journals without symbol metadata deliberately remain halted for manual review.


## Strategy signal routing boundary

`engine/binance_signal_router.py` converts a validated BUY crypto setup and
fresh Binance quote into a risk-sized Testnet OTOCO plan. It requires explicit
verification of both the account snapshot and daily realized-loss context,
fresh exchange symbol filters, verified taker fees, a single-position risk
check, and the existing durable protected-order lifecycle. It rejects SELL
setups because the initial Spot Testnet route is BUY-only.

The router is currently a tested integration component, not enabled in the
Android strategy loop. The Android engine remains paper-only until account
balance and daily-loss accounting are connected, Testnet order authorization
is explicitly enabled, and end-to-end demo verification is completed.


## Daily loss and account context

The Binance Testnet risk context provider reads the account's USDT free and
locked balances, requires the account to confirm `canTrade`, and obtains
open-position state only from a successful full journal reconciliation. It
uses USDT-only equity (excluding other assets) as a conservative sizing basis.
Unknown account permissions, unresolved orders, or a corrupt daily-loss ledger
block new entries.

The append-only UTC daily-loss ledger records the conservative planned-risk
amount only after Binance confirms a stop-loss exit. Entries are idempotent by
order-list ID and are not double-counted after restart. Older journal entries
without a saved risk basis remain halted if their stop-loss exit is discovered.


The risk-context provider also treats any non-zero non-USDT Spot balance as
an unmanaged open holding. That is intentionally conservative: manual holdings
are not silently ignored by the one-position rule. Such a balance must be
reviewed or explicitly handled before the bot can open another position.


## Account-tier trading fees

The Testnet adapter now queries the authenticated per-symbol commission
schedule using Binance's signed `GET /api/v3/account/commission` endpoint.
The parser requires standard, special and tax commission groups, uses the
highest taker/buyer/seller rate in each group, and ignores optional BNB
discounts so order sizing remains conservative. Missing or malformed rates
block order planning; no fee is guessed.


## Android Testnet automation switch

The strategy loop can now route a validated BUY setup through the protected
Testnet router when the user explicitly enables **Binance Testnet automation**
inside the Android app. The switch is OFF by default, requires saved Testnet
credentials, and is stored in Android private preferences. Disabling it stops
new entries after the foreground service restarts; existing exchange-hosted
protective orders remain at Binance. The runtime passes decrypted credentials
to the on-device Python process only while this Testnet mode is enabled. No
credentials are sent to Netlify, and the adapter remains pinned to
`testnet.binance.vision`.

This integration is code-complete but not yet end-to-end verified against a
real Binance Spot Testnet account. The first actual demo order must be
explicitly enabled by the user in the Android app.


## Unconfirmed protection and emergency boundary

If an order submission or exchange reconciliation is uncertain, the durable
lifecycle halts further entries and reports that operator review is required.
It does not blindly retry an entry. The Android Disable automation control
prevents new entries after service restart, while any confirmed exchange-held
OTOCO legs remain at Binance. Automatic emergency market-flattening for a
filled but unprotected position is not yet implemented; an unconfirmed
protection state must be treated as requiring immediate manual review in the
Binance Spot Testnet account.
