from copy import deepcopy

import pytest

from engine.binance_emergency_close import emergency_flatten_otoco


class FakeClient:
    allow_orders = True

    def __init__(self):
        self.calls = []
        self.balances = [
            {"asset": "BTC", "free": "0.001", "locked": "0"},
            {"asset": "USDT", "free": "100", "locked": "0"},
        ]
        self.orders = {
            "entryE": {"status": "FILLED", "executedQty": "0.001"},
            "entryT": {"status": "CANCELED"},
            "entryS": {"status": "CANCELED"},
        }
        self.open_orders = []
        self.market_response = {"status": "FILLED", "executedQty": "0.001"}

    def query_order_by_client_id(self, *, symbol, client_order_id):
        self.calls.append(("query", client_order_id))
        return dict(self.orders[client_order_id])

    def cancel_filled_otoco_for_emergency(self, *, symbol, list_client_order_id):
        self.calls.append(("cancel-list", list_client_order_id))
        return {"listStatusType": "ALL_DONE"}

    def account_open_orders(self, *, symbol):
        self.calls.append(("open-orders", symbol))
        return deepcopy(self.open_orders)

    def exchange_info(self, symbol):
        return {"symbols": [{
            "symbol": symbol, "status": "TRADING", "baseAsset": "BTC",
            "filters": [
                {"filterType": "MARKET_LOT_SIZE", "stepSize": "0.0001",
                 "minQty": "0.0001", "maxQty": "100"},
                {"filterType": "MIN_NOTIONAL", "minNotional": "5"},
            ],
        }]}

    def account(self):
        self.calls.append(("account", None))
        return {"balances": deepcopy(self.balances)}

    def place_market_sell(self, *, symbol, quantity, client_order_id):
        self.calls.append(("market-sell", quantity, client_order_id))
        if self.market_response.get("status") == "FILLED":
            self.balances[0]["free"] = "0"
        return dict(self.market_response)


def run(client):
    return emergency_flatten_otoco(
        client, symbol="BTCUSDT", list_client_order_id="entry",
        emergency_client_order_id="emergency123", reference_price="50000",
    )


def test_emergency_close_cancels_bracket_then_sells_and_verifies_flat():
    client = FakeClient()
    result = run(client)
    assert result["status"] == "EMERGENCY_FLAT_CONFIRMED"
    assert result["sold_quantity"] == "0.001"
    names = [call[0] for call in client.calls]
    assert names.index("cancel-list") < names.index("open-orders")
    assert names.index("open-orders") < names.index("market-sell")


def test_refuses_to_sell_when_either_protective_leg_is_not_terminal():
    client = FakeClient()
    client.orders["entryS"] = {"status": "NEW"}
    with pytest.raises(RuntimeError, match="not both confirmed terminal"):
        run(client)
    assert not any(call[0] == "market-sell" for call in client.calls)


def test_refuses_to_sell_when_another_sell_order_is_open():
    client = FakeClient()
    client.open_orders = [{"side": "SELL", "status": "NEW"}]
    with pytest.raises(RuntimeError, match="Another SELL order"):
        run(client)
    assert not any(call[0] == "market-sell" for call in client.calls)


def test_refuses_to_sell_when_base_asset_is_still_locked():
    client = FakeClient()
    client.balances[0]["locked"] = "0.0001"
    with pytest.raises(RuntimeError, match="remains locked"):
        run(client)
    assert not any(call[0] == "market-sell" for call in client.calls)


def test_rounds_quantity_down_to_market_lot_step():
    client = FakeClient()
    client.balances[0]["free"] = "0.00109"
    client.market_response = {"status": "FILLED", "executedQty": "0.001"}
    result = run(client)
    sell = next(call for call in client.calls if call[0] == "market-sell")
    assert sell[1] == "0.001"
    assert result["status"] == "EMERGENCY_FLAT_CONFIRMED"


def test_does_not_claim_flat_when_exchange_reports_partial_market_execution():
    client = FakeClient()
    client.market_response = {"status": "PARTIALLY_FILLED", "executedQty": "0.0005"}
    with pytest.raises(RuntimeError, match="not confirmed FILLED"):
        run(client)


def test_does_not_claim_flat_when_residual_balance_remains():
    client = FakeClient()
    client.market_response = {"status": "FILLED", "executedQty": "0.0009"}
    with pytest.raises(RuntimeError, match="Residual base asset"):
        run(client)


def test_emergency_close_requires_explicit_testnet_order_gate():
    client = FakeClient()
    client.allow_orders = False
    with pytest.raises(PermissionError, match="actions are disabled"):
        run(client)
    assert client.calls == []


def test_refuses_when_entry_is_not_filled():
    client = FakeClient()
    client.orders["entryE"] = {"status": "NEW", "executedQty": "0"}
    with pytest.raises(PermissionError, match="No filled bot entry"):
        run(client)
    assert not any(call[0] == "market-sell" for call in client.calls)


def test_refuses_when_quantity_is_below_market_minimum():
    client = FakeClient()
    client.balances[0]["free"] = "0.00001"
    with pytest.raises(RuntimeError, match="MARKET_LOT_SIZE"):
        run(client)
    assert not any(call[0] == "market-sell" for call in client.calls)
