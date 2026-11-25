import os
from urllib.parse import parse_qs, urlsplit

import pytest

from engine.binance_testnet import BinanceSpotTestnetClient, TESTNET_BASE_URL


def make_client(monkeypatch, transport, *, enabled=False):
    monkeypatch.setenv("DOMINION_ENABLE_BINANCE_TESTNET_ORDERS", "YES" if enabled else "NO")
    return BinanceSpotTestnetClient(
        "test-api-key", "test-api-secret", allow_orders=enabled,
        transport=transport, clock_ms=lambda: 1_700_000_000_000,
    )


def test_refuses_non_testnet_host():
    with pytest.raises(ValueError, match="fixed Binance"):
        BinanceSpotTestnetClient("key", "secret", base_url="https://api.binance.com")


def test_order_disabled_by_default_even_with_credentials(monkeypatch):
    client = make_client(monkeypatch, lambda *args: pytest.fail("network must not be called"))
    with pytest.raises(PermissionError):
        client.place_limit_order(
            symbol="BTCUSDT", side="BUY", quantity="0.001",
            price="30000", client_order_id="dominion-test-1",
        )


def test_order_requires_explicit_constructor_and_environment_gates(monkeypatch):
    captured = {}
    def transport(method, url, headers, timeout):
        captured.update(method=method, url=url, headers=headers)
        return {"status": "NEW", "orderId": 123}
    client = make_client(monkeypatch, transport, enabled=True)
    result = client.place_limit_order(
        symbol="BTCUSDT", side="BUY", quantity="0.001",
        price="30000.00", client_order_id="dominion-test-2",
    )
    parsed = parse_qs(urlsplit(captured["url"]).query)
    assert result["orderId"] == 123
    assert captured["method"] == "POST"
    assert urlsplit(captured["url"]).netloc == "testnet.binance.vision"
    assert captured["headers"]["X-MBX-APIKEY"] == "test-api-key"
    assert parsed["type"] == ["LIMIT"]
    assert parsed["timeInForce"] == ["GTC"]
    assert parsed["signature"]


@pytest.mark.parametrize("quantity,price", [("0", "1"), ("-1", "1"), ("1", "NaN")])
def test_rejects_invalid_order_numbers(monkeypatch, quantity, price):
    client = make_client(monkeypatch, lambda *args: {"ok": True}, enabled=True)
    with pytest.raises(ValueError):
        client.place_limit_order(
            symbol="BTCUSDT", side="BUY", quantity=quantity,
            price=price, client_order_id="dominion-test-3",
        )


def test_order_gate_requires_both_explicit_switches(monkeypatch):
    monkeypatch.setenv("DOMINION_ENABLE_BINANCE_TESTNET_ORDERS", "YES")
    client = BinanceSpotTestnetClient("key", "secret", allow_orders=False,
                                      transport=lambda *args: {"ok": True})
    assert client.allow_orders is False

def test_protected_otoco_uses_fok_entry_and_two_sell_exit_legs(monkeypatch):
    captured = {}
    def transport(method, url, headers, timeout):
        captured.update(method=method, url=url)
        return {"orderListId": 77, "listOrderStatus": "EXECUTING"}
    client = make_client(monkeypatch, transport, enabled=True)
    result = client.place_protected_buy_otoco(
        symbol="BTCUSDT", quantity="0.001", entry_price="30000",
        stop_loss="29500", take_profit="31000",
        list_client_order_id="dominion123",
    )
    params = parse_qs(urlsplit(captured["url"]).query)
    assert result["orderListId"] == 77
    assert urlsplit(captured["url"]).path == "/api/v3/orderList/otoco"
    assert params["workingSide"] == ["BUY"]
    assert params["workingTimeInForce"] == ["FOK"]
    assert params["pendingSide"] == ["SELL"]
    assert params["pendingAboveType"] == ["LIMIT_MAKER"]
    assert params["pendingAbovePrice"] == ["31000"]
    assert params["pendingBelowType"] == ["STOP_LOSS_LIMIT"]
    assert params["pendingBelowStopPrice"] == ["29500"]
    assert params["pendingBelowTimeInForce"] == ["GTC"]
    assert params["signature"]


def test_protected_otoco_stays_disabled_without_both_gates(monkeypatch):
    client = make_client(monkeypatch, lambda *args: pytest.fail("network must not be called"))
    with pytest.raises(PermissionError):
        client.place_protected_buy_otoco(
            symbol="BTCUSDT", quantity="0.001", entry_price="30000",
            stop_loss="29500", take_profit="31000",
            list_client_order_id="dominion123",
        )


def test_protected_otoco_rejects_bad_bracket_and_long_list_id(monkeypatch):
    client = make_client(monkeypatch, lambda *args: {"ok": True}, enabled=True)
    with pytest.raises(ValueError, match="stop-loss"):
        client.place_protected_buy_otoco(
            symbol="BTCUSDT", quantity="0.001", entry_price="30000",
            stop_loss="30100", take_profit="31000",
            list_client_order_id="dominion123",
        )
    with pytest.raises(ValueError, match="1-20 ASCII characters"):
        client.place_protected_buy_otoco(
            symbol="BTCUSDT", quantity="0.001", entry_price="30000",
            stop_loss="29500", take_profit="31000",
            list_client_order_id="dominion123456789012345",
        )

def test_reconcile_requires_filled_entry_and_both_exit_legs_new(monkeypatch):
    def transport(method, url, headers, timeout):
        params = parse_qs(urlsplit(url).query)
        client_id = params.get("origClientOrderId", [""])[0]
        statuses = {"dominion123E": "FILLED", "dominion123T": "NEW", "dominion123S": "NEW"}
        return {"status": statuses[client_id]}
    client = make_client(monkeypatch, transport)
    result = client.reconcile_protected_buy_otoco(
        symbol="BTCUSDT", list_client_order_id="dominion123")
    assert result["state"] == "PROTECTED"
    assert result["protected"] is True
    assert result["working_status"] == "FILLED"


def test_reconcile_never_claims_protection_for_pending_new_children(monkeypatch):
    def transport(method, url, headers, timeout):
        params = parse_qs(urlsplit(url).query)
        client_id = params.get("origClientOrderId", [""])[0]
        statuses = {"dominion123E": "FILLED", "dominion123T": "PENDING_NEW",
                    "dominion123S": "PENDING_NEW"}
        return {"status": statuses[client_id]}
    client = make_client(monkeypatch, transport)
    result = client.reconcile_protected_buy_otoco(
        symbol="BTCUSDT", list_client_order_id="dominion123")
    assert result["state"] == "PROTECTION_UNCONFIRMED"
    assert result["protected"] is False


def test_cancel_refuses_to_remove_bracket_from_filled_position(monkeypatch):
    calls = []
    def transport(method, url, headers, timeout):
        calls.append(method)
        return {"status": "FILLED"}
    client = make_client(monkeypatch, transport, enabled=True)
    with pytest.raises(PermissionError, match="filled position"):
        client.cancel_order_list(symbol="BTCUSDT", list_client_order_id="dominion123")
    assert calls == ["GET"]


def test_exchange_info_is_public_and_pinned_to_testnet(monkeypatch):
    captured = {}
    def transport(method, url, headers, timeout):
        captured.update(method=method, url=url, headers=headers)
        return {"symbols": []}
    client = make_client(monkeypatch, transport)
    result = client.exchange_info("BTCUSDT")
    parsed = parse_qs(urlsplit(captured["url"]).query)
    assert result == {"symbols": []}
    assert captured["method"] == "GET"
    assert urlsplit(captured["url"]).netloc == "testnet.binance.vision"
    assert urlsplit(captured["url"]).path == "/api/v3/exchangeInfo"
    assert parsed["symbol"] == ["BTCUSDT"]
    assert captured["headers"] == {}



@pytest.mark.parametrize("entry_status,expected_state", [
    ("EXPIRED", "NO_POSITION"),
    ("CANCELED", "NO_POSITION"),
    ("NEW", "ENTRY_PENDING"),
    ("PARTIALLY_FILLED", "UNPROTECTED_PARTIAL_FILL"),
])
def test_reconcile_does_not_query_exit_orders_before_entry_fills(
    monkeypatch, entry_status, expected_state
):
    calls = []
    def transport(method, url, headers, timeout):
        params = parse_qs(urlsplit(url).query)
        client_id = params.get("origClientOrderId", [""])[0]
        calls.append(client_id)
        return {"status": entry_status}
    client = make_client(monkeypatch, transport)
    result = client.reconcile_protected_buy_otoco(
        symbol="BTCUSDT", list_client_order_id="dominion123"
    )
    assert result["state"] == expected_state
    assert calls == ["dominion123E"]
    assert result["take_profit_status"] is None
    assert result["stop_loss_status"] is None



def test_account_commission_is_signed_and_pinned_to_spot_testnet(monkeypatch):
    captured = {}
    def transport(method, url, headers, timeout):
        captured.update(method=method, url=url, headers=headers)
        return {"symbol": "BTCUSDT"}
    client = make_client(monkeypatch, transport)
    result = client.account_commission("btcusdt")
    params = parse_qs(urlsplit(captured["url"]).query)
    assert result["symbol"] == "BTCUSDT"
    assert captured["method"] == "GET"
    assert urlsplit(captured["url"]).netloc == "testnet.binance.vision"
    assert urlsplit(captured["url"]).path == "/api/v3/account/commission"
    assert params["symbol"] == ["BTCUSDT"]
    assert params["signature"]
    assert captured["headers"]["X-MBX-APIKEY"] == "test-api-key"
