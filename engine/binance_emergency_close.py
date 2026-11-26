"""Fail-closed emergency flattening for bot-owned Binance Spot Testnet OTOCO positions.

This routine is intentionally separate from normal trade management. It cancels
only the named bot order-list, verifies both exit legs are terminal, refuses to
sell while any other SELL order is open, sizes from the live free base balance
using MARKET_LOT_SIZE, submits one uniquely identified MARKET SELL, and verifies
the exchange-reported result and remaining base balance. Any uncertainty halts.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_DOWN
from typing import Any


TERMINAL = {"CANCELED", "EXPIRED", "REJECTED", "FILLED"}


def _decimal(value: Any, label: str, *, allow_zero: bool = False) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"Invalid {label}.") from exc
    if not number.is_finite() or (number < 0 if allow_zero else number <= 0):
        raise ValueError(f"Invalid {label}.")
    return number


def _market_rules(exchange_info: dict, symbol: str) -> tuple[str, Decimal, Decimal, Decimal]:
    if not isinstance(exchange_info, dict) or not isinstance(exchange_info.get("symbols"), list):
        raise ValueError("Exchange symbol metadata is malformed.")
    rows = [row for row in exchange_info["symbols"]
            if isinstance(row, dict) and row.get("symbol") == symbol]
    if len(rows) != 1 or rows[0].get("status") != "TRADING":
        raise PermissionError("Symbol is missing, duplicated, or not trading.")
    row = rows[0]
    base = row.get("baseAsset")
    if not isinstance(base, str) or not base.isalnum():
        raise ValueError("Base asset metadata is invalid.")
    filters = row.get("filters")
    if not isinstance(filters, list):
        raise ValueError("Symbol filters are missing.")
    lots = [f for f in filters if isinstance(f, dict) and f.get("filterType") == "MARKET_LOT_SIZE"]
    if len(lots) != 1:
        raise ValueError("A unique MARKET_LOT_SIZE filter is required.")
    lot = lots[0]
    step = _decimal(lot.get("stepSize"), "market quantity step")
    minimum = _decimal(lot.get("minQty"), "market minimum quantity")
    maximum = _decimal(lot.get("maxQty"), "market maximum quantity")
    if maximum < minimum:
        raise ValueError("Market quantity limits are inconsistent.")
    return base, step, minimum, maximum


def emergency_flatten_otoco(
    client: Any, *, symbol: str, list_client_order_id: str,
    emergency_client_order_id: str, reference_price: str,
) -> dict:
    """Cancel the named bot bracket and submit at most one balance-sized market sell.

    This function never retries a market order after an ambiguous submission.
    A caller must persist the emergency client ID before invoking it.
    """
    if not getattr(client, "allow_orders", False):
        raise PermissionError("Binance Testnet order actions are disabled.")
    pair = symbol.strip().upper()
    if not pair.isalnum() or not 5 <= len(pair) <= 20:
        raise ValueError("Invalid symbol.")
    if (not list_client_order_id or len(list_client_order_id) > 20
            or not emergency_client_order_id or len(emergency_client_order_id) > 36
            or not emergency_client_order_id.isascii()):
        raise ValueError("Invalid emergency order identifiers.")
    price = _decimal(reference_price, "reference price")

    entry = client.query_order_by_client_id(
        symbol=pair, client_order_id=list_client_order_id + "E"
    )
    if entry.get("status") not in {"FILLED", "PARTIALLY_FILLED"}:
        raise PermissionError("No filled bot entry exists to emergency-close.")
    executed = _decimal(entry.get("executedQty", "0"), "entry executed quantity", allow_zero=True)
    if executed == 0:
        raise RuntimeError("Entry has no confirmed executed quantity.")

    # Inspect both exits before cancellation. If one already filled, the
    # exchange should have terminated its sibling and the list may be ALL_DONE.
    tp = client.query_order_by_client_id(symbol=pair, client_order_id=list_client_order_id + "T")
    sl = client.query_order_by_client_id(symbol=pair, client_order_id=list_client_order_id + "S")
    if tp.get("status") not in TERMINAL or sl.get("status") not in TERMINAL:
        try:
            cancellation = client.cancel_filled_otoco_for_emergency(
                symbol=pair, list_client_order_id=list_client_order_id
            )
            if not isinstance(cancellation, dict):
                raise RuntimeError("Order-list cancellation response is malformed.")
        except Exception:
            # A cancel timeout/race is acceptable only if fresh broker queries
            # prove both exit orders are now terminal.
            tp = client.query_order_by_client_id(
                symbol=pair, client_order_id=list_client_order_id + "T"
            )
            sl = client.query_order_by_client_id(
                symbol=pair, client_order_id=list_client_order_id + "S"
            )
            if tp.get("status") not in TERMINAL or sl.get("status") not in TERMINAL:
                raise RuntimeError("Order-list cancellation is uncertain; refusing market sell.")
        tp = client.query_order_by_client_id(symbol=pair, client_order_id=list_client_order_id + "T")
        sl = client.query_order_by_client_id(symbol=pair, client_order_id=list_client_order_id + "S")
    if tp.get("status") not in TERMINAL or sl.get("status") not in TERMINAL:
        raise RuntimeError("Protective exit orders are not both confirmed terminal.")

    open_orders = client.account_open_orders(symbol=pair)
    if any(str(order.get("side", "")).upper() == "SELL" for order in open_orders):
        raise RuntimeError("Another SELL order is open; refusing emergency market sell.")

    metadata = client.exchange_info(pair)
    base_asset, step, min_qty, max_qty = _market_rules(metadata, pair)
    account = client.account()
    balances = account.get("balances") if isinstance(account, dict) else None
    if not isinstance(balances, list):
        raise RuntimeError("Account balance response is malformed.")
    matches = [b for b in balances if isinstance(b, dict) and b.get("asset") == base_asset]
    if len(matches) != 1:
        raise RuntimeError("Base-asset balance is missing or ambiguous.")
    free = _decimal(matches[0].get("free"), "free base balance", allow_zero=True)
    locked = _decimal(matches[0].get("locked"), "locked base balance", allow_zero=True)
    if locked != 0:
        raise RuntimeError("Base asset remains locked after exit cancellation.")
    # Never liquidate unrelated holdings: cap the sell at this bot entry's
    # exchange-confirmed executed quantity, then round down to market step.
    owned_available = min(free, executed)
    quantity = (owned_available / step).to_integral_value(rounding=ROUND_DOWN) * step
    if quantity < min_qty or quantity > max_qty:
        raise RuntimeError("Available base balance is below/above MARKET_LOT_SIZE; manual review required.")

    # Check minimum notional conservatively using the supplied fresh reference price.
    filters = next(row for row in metadata["symbols"] if row.get("symbol") == pair)["filters"]
    notionals = [f for f in filters if isinstance(f, dict)
                 and f.get("filterType") in {"NOTIONAL", "MIN_NOTIONAL"}]
    if len(notionals) != 1:
        raise RuntimeError("A unique minimum-notional filter is required.")
    min_notional = _decimal(notionals[0].get("minNotional"), "minimum notional")
    if quantity * price < min_notional:
        raise RuntimeError("Emergency sell would violate minimum notional; manual review required.")

    # Caller must durably journal this ID before this one-shot request.
    order = client.place_market_sell(
        symbol=pair, quantity=format(quantity, "f"),
        client_order_id=emergency_client_order_id,
    )
    if not isinstance(order, dict) or order.get("status") != "FILLED":
        raise RuntimeError("Emergency market sell is not confirmed FILLED; do not resubmit.")

    executed_sell = _decimal(order.get("executedQty", "0"), "market sell executed quantity", allow_zero=True)
    if executed_sell <= 0 or executed_sell > quantity:
        raise RuntimeError("Emergency market sell execution quantity is invalid.")
    after = client.account()
    after_balances = after.get("balances") if isinstance(after, dict) else None
    if not isinstance(after_balances, list):
        raise RuntimeError("Post-close account balance is malformed.")
    after_matches = [b for b in after_balances
                     if isinstance(b, dict) and b.get("asset") == base_asset]
    if len(after_matches) != 1:
        raise RuntimeError("Post-close base-asset balance is missing or ambiguous.")
    remaining_free = _decimal(after_matches[0].get("free"), "remaining free balance", allow_zero=True)
    remaining_locked = _decimal(after_matches[0].get("locked"), "remaining locked balance", allow_zero=True)
    if remaining_free != 0 or remaining_locked != 0:
        raise RuntimeError("Residual base asset remains after emergency sell; manual review required.")
    return {
        "status": "EMERGENCY_FLAT_CONFIRMED",
        "symbol": pair,
        "base_asset": base_asset,
        "sold_quantity": format(executed_sell, "f"),
        "remaining_base_balance": "0",
        "emergency_client_order_id": emergency_client_order_id,
        "operator_action_required": False,
    }
