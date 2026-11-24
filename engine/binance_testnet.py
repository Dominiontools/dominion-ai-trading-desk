"""Explicitly gated Binance Spot Testnet client.

This adapter is isolated from production exchange hosts. It never reads or
stores credentials from files; callers provide API credentials at runtime.
Order placement is disabled unless the caller opts in and the environment
flag DOMINION_ENABLE_BINANCE_TESTNET_ORDERS is exactly YES. Limit orders only.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time
from decimal import Decimal, InvalidOperation
from typing import Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import json

TESTNET_BASE_URL = "https://testnet.binance.vision"


def _positive_decimal(value: str | int | float | Decimal, field: str) -> str:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} must be a valid decimal.") from exc
    if not number.is_finite() or number <= 0:
        raise ValueError(f"{field} must be greater than zero.")
    return format(number, "f")


class BinanceSpotTestnetClient:
    """Minimal signed REST client for Binance Spot Testnet, not production."""

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        *,
        allow_orders: bool = False,
        base_url: str = TESTNET_BASE_URL,
        transport: Callable[[str, str, dict[str, str], float], dict] | None = None,
        clock_ms: Callable[[], int] | None = None,
        timeout: float = 8.0,
    ):
        if base_url.rstrip("/") != TESTNET_BASE_URL:
            raise ValueError("Only the fixed Binance Spot Testnet host is permitted.")
        if not api_key.strip() or not api_secret.strip():
            raise ValueError("Binance Testnet API key and secret are required.")
        if timeout <= 0:
            raise ValueError("Timeout must be positive.")
        self._api_key = api_key.strip()
        self._api_secret = api_secret.encode("utf-8")
        self.allow_orders = bool(allow_orders) and os.getenv(
            "DOMINION_ENABLE_BINANCE_TESTNET_ORDERS", ""
        ) == "YES"
        self.base_url = TESTNET_BASE_URL
        self.transport = transport or self._http
        self.clock_ms = clock_ms or (lambda: int(time.time() * 1000))
        self.timeout = timeout

    @staticmethod
    def _http(method: str, url: str, headers: dict[str, str], timeout: float) -> dict:
        request = Request(url, headers=headers, method=method)
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, dict):
                raise RuntimeError("Unexpected Binance response shape.")
            return payload

    def _signed(self, method: str, path: str, params: dict[str, str]) -> dict:
        values = dict(params)
        values["timestamp"] = str(self.clock_ms())
        values.setdefault("recvWindow", "5000")
        query = urlencode(values)
        signature = hmac.new(
            self._api_secret, query.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        url = f"{self.base_url}{path}?{query}&signature={signature}"
        return self.transport(
            method, url, {"X-MBX-APIKEY": self._api_key}, self.timeout
        )

    def exchange_info(self, symbol: str) -> dict:
        """Fetch public symbol filters from the fixed Spot Testnet host."""
        pair = symbol.strip().upper()
        if not pair.isalnum() or not 5 <= len(pair) <= 20:
            raise ValueError("Invalid trading symbol.")
        query = urlencode({"symbol": pair})
        return self.transport(
            "GET", f"{self.base_url}/api/v3/exchangeInfo?{query}", {}, self.timeout
        )

    def account(self) -> dict:
        """Read the Testnet account only."""
        return self._signed("GET", "/api/v3/account", {})

    def place_limit_order(
        self,
        *,
        symbol: str,
        side: str,
        quantity: str | int | float | Decimal,
        price: str | int | float | Decimal,
        client_order_id: str,
    ) -> dict:
        """Place a GTC limit order only after two independent enable gates."""
        if not self.allow_orders:
            raise PermissionError(
                "Binance Testnet orders are disabled. Explicitly enable the testnet order flag."
            )
        pair = symbol.strip().upper()
        if not pair.isalnum() or not 5 <= len(pair) <= 20:
            raise ValueError("Invalid trading symbol.")
        direction = side.strip().upper()
        if direction not in {"BUY", "SELL"}:
            raise ValueError("Side must be BUY or SELL.")
        if not client_order_id or len(client_order_id) > 36 or not client_order_id.isascii():
            raise ValueError("A short ASCII client order ID is required.")
        params = {
            "symbol": pair,
            "side": direction,
            "type": "LIMIT",
            "timeInForce": "GTC",
            "quantity": _positive_decimal(quantity, "quantity"),
            "price": _positive_decimal(price, "price"),
            "newClientOrderId": client_order_id,
        }
        return self._signed("POST", "/api/v3/order", params)

    def place_protected_buy_otoco(self, *, symbol: str, quantity: str, entry_price: str,
                                  stop_loss: str, take_profit: str, list_client_order_id: str) -> dict:
        """Submit a FOK BUY entry with exchange-held OCO exit legs (Spot Testnet only)."""
        if not self.allow_orders:
            raise PermissionError("Binance Testnet orders are disabled.")
        pair = symbol.strip().upper()
        if not pair.isalnum() or not 5 <= len(pair) <= 20:
            raise ValueError("Invalid trading symbol.")
        if not list_client_order_id or len(list_client_order_id) > 20 or not list_client_order_id.isascii():
            raise ValueError("Order-list client ID must be 1-20 ASCII characters.")
        qty = _positive_decimal(quantity, "quantity")
        entry = _positive_decimal(entry_price, "entry price")
        stop = _positive_decimal(stop_loss, "stop loss")
        target = _positive_decimal(take_profit, "take profit")
        if not Decimal(stop) < Decimal(entry) < Decimal(target):
            raise ValueError("BUY bracket requires stop-loss < entry < take-profit.")
        params = {
            "symbol": pair, "listClientOrderId": list_client_order_id,
            "workingType": "LIMIT", "workingSide": "BUY",
            "workingPrice": entry, "workingQuantity": qty,
            "workingTimeInForce": "FOK",
            "workingClientOrderId": list_client_order_id + "E",
            "pendingSide": "SELL", "pendingQuantity": qty,
            "pendingAboveType": "LIMIT_MAKER", "pendingAbovePrice": target,
            "pendingAboveClientOrderId": list_client_order_id + "T",
            "pendingBelowType": "STOP_LOSS_LIMIT",
            "pendingBelowStopPrice": stop, "pendingBelowPrice": stop,
            "pendingBelowTimeInForce": "GTC",
            "pendingBelowClientOrderId": list_client_order_id + "S",
            "newOrderRespType": "RESULT",
        }
        return self._signed("POST", "/api/v3/orderList/otoco", params)

    def query_order_list(self, *, list_client_order_id: str) -> dict:
        if not list_client_order_id or len(list_client_order_id) > 20:
            raise ValueError("A valid order-list client ID is required.")
        return self._signed("GET", "/api/v3/orderList", {"origClientOrderId": list_client_order_id})

    def query_order_by_client_id(self, *, symbol: str, client_order_id: str) -> dict:
        pair = symbol.strip().upper()
        if not pair.isalnum() or not client_order_id or len(client_order_id) > 36:
            raise ValueError("A valid symbol and client order ID are required.")
        return self._signed("GET", "/api/v3/order", {"symbol": pair, "origClientOrderId": client_order_id})

    def reconcile_protected_buy_otoco(self, *, symbol: str, list_client_order_id: str) -> dict:
        """Query all three OTOCO legs and classify protection from exchange state."""
        if not list_client_order_id or len(list_client_order_id) > 20:
            raise ValueError("A valid order-list client ID is required.")
        working = self.query_order_by_client_id(symbol=symbol, client_order_id=list_client_order_id + "E")
        take_profit = self.query_order_by_client_id(symbol=symbol, client_order_id=list_client_order_id + "T")
        stop_loss = self.query_order_by_client_id(symbol=symbol, client_order_id=list_client_order_id + "S")
        from .binance_protection import classify_otoco
        state = classify_otoco(working.get("status", "UNKNOWN"),
                               take_profit.get("status"), stop_loss.get("status"))
        return {
            **state,
            "working_status": working.get("status", "UNKNOWN"),
            "take_profit_status": take_profit.get("status", "UNKNOWN"),
            "stop_loss_status": stop_loss.get("status", "UNKNOWN"),
            "list_client_order_id": list_client_order_id,
        }
    def cancel_order_list(self, *, symbol: str, list_client_order_id: str) -> dict:
        if not self.allow_orders:
            raise PermissionError("Binance Testnet order actions are disabled.")
        pair = symbol.strip().upper()
        if not pair.isalnum() or not list_client_order_id or len(list_client_order_id) > 20:
            raise ValueError("A valid symbol and order-list client ID are required.")
        working = self.query_order_by_client_id(symbol=pair, client_order_id=list_client_order_id + "E")
        if working.get("status") == "FILLED":
            raise PermissionError("Refusing to cancel an OTOCO protecting a filled position.")
        return self._signed("DELETE", "/api/v3/orderList", {"symbol": pair, "listClientOrderId": list_client_order_id})
    def query_order(self, *, symbol: str, order_id: int) -> dict:
        pair = symbol.strip().upper()
        if not pair.isalnum() or order_id <= 0:
            raise ValueError("A valid symbol and positive order ID are required.")
        return self._signed("GET", "/api/v3/order", {
            "symbol": pair, "orderId": str(order_id)
        })

    def cancel_order(self, *, symbol: str, order_id: int) -> dict:
        if not self.allow_orders:
            raise PermissionError("Binance Testnet order actions are disabled.")
        pair = symbol.strip().upper()
        if not pair.isalnum() or order_id <= 0:
            raise ValueError("A valid symbol and positive order ID are required.")
        return self._signed("DELETE", "/api/v3/order", {
            "symbol": pair, "orderId": str(order_id)
        })
