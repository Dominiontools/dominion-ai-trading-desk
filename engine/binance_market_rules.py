"""Read-only Binance Spot Testnet symbol-filter discovery."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from .risk_execution import BinanceSymbolRules


def parse_symbol_rules(payload: dict, symbol: str) -> BinanceSymbolRules:
    """Parse verified tick/lot/notional filters for one active symbol.

    The caller must obtain payload directly from the fixed Testnet
    exchangeInfo endpoint. Missing, duplicate, malformed, or inactive filters
    are rejected rather than replaced with guessed values.
    """
    pair = symbol.strip().upper()
    if not isinstance(payload, dict) or not isinstance(payload.get("symbols"), list):
        raise ValueError("Binance exchangeInfo response is malformed.")
    matches = [
        item for item in payload["symbols"]
        if isinstance(item, dict) and str(item.get("symbol", "")).upper() == pair
    ]
    if len(matches) != 1:
        raise ValueError("Requested symbol was not uniquely returned by Binance.")
    item = matches[0]
    if item.get("status") != "TRADING":
        raise PermissionError("Binance symbol is not currently trading.")
    filters = item.get("filters")
    if not isinstance(filters, list):
        raise ValueError("Binance symbol filters are missing.")

    def one(filter_type: str) -> dict:
        found = [x for x in filters if isinstance(x, dict) and x.get("filterType") == filter_type]
        if len(found) != 1:
            raise ValueError(f"Expected exactly one {filter_type} filter.")
        return found[0]

    def number(value, label: str) -> Decimal:
        try:
            result = Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"Invalid Binance {label}.") from exc
        if not result.is_finite() or result <= 0:
            raise ValueError(f"Invalid Binance {label}.")
        return result

    price = one("PRICE_FILTER")
    lot = one("LOT_SIZE")
    notional_filters = [
        x for x in filters if isinstance(x, dict)
        and x.get("filterType") in {"NOTIONAL", "MIN_NOTIONAL"}
    ]
    if len(notional_filters) != 1:
        raise ValueError("Expected exactly one Binance notional filter.")
    notional_filter = notional_filters[0]
    min_notional = number(notional_filter.get("minNotional"), "minimum notional")
    rules = BinanceSymbolRules(
        tick_size=number(price.get("tickSize"), "tick size"),
        step_size=number(lot.get("stepSize"), "quantity step"),
        min_quantity=number(lot.get("minQty"), "minimum quantity"),
        max_quantity=number(lot.get("maxQty"), "maximum quantity"),
        min_notional=min_notional,
        verified=True,
    )
    if rules.max_quantity < rules.min_quantity:
        raise ValueError("Binance quantity range is invalid.")
    return rules


def fetch_symbol_rules(client, symbol: str) -> BinanceSymbolRules:
    """Fetch and parse filters from the client's pinned public Testnet endpoint."""
    response = client.exchange_info(symbol)
    return parse_symbol_rules(response, symbol)
