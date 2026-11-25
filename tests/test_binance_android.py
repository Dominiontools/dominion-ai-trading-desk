import json

from engine import binance_android


class FakeClient:
    def __init__(self, api_key, api_secret, *, allow_orders):
        assert api_key == "test-key"
        assert api_secret == "test-secret"
        assert allow_orders is False

    def account(self):
        return {
            "canTrade": True,
            "canWithdraw": False,
            "canDeposit": True,
            "accountType": "SPOT",
            "permissions": ["SPOT"],
            "balances": [
                {"asset": "USDT", "free": "20.00000000", "locked": "0.0"},
                {"asset": "BTC", "free": "0", "locked": "0"},
                {"asset": "BAD", "free": "NaN", "locked": "0"},
            ],
        }


def test_account_summary_is_read_only_and_filters_zero_or_invalid_balances(monkeypatch):
    monkeypatch.setattr(binance_android, "BinanceSpotTestnetClient", FakeClient)
    result = json.loads(binance_android.account_summary("test-key", "test-secret"))
    assert result["connected"] is True
    assert result["environment"] == "BINANCE_SPOT_TESTNET"
    assert result["can_trade"] is True
    assert result["can_withdraw"] is False
    assert result["balances"] == [{"asset": "USDT", "free": "20.00000000", "locked": "0.0"}]


def test_account_summary_does_not_return_credentials_or_raw_account(monkeypatch):
    monkeypatch.setattr(binance_android, "BinanceSpotTestnetClient", FakeClient)
    result = binance_android.account_summary("test-key", "test-secret")
    assert "test-key" not in result
    assert "test-secret" not in result
    assert "balances" in result
    assert "accountType" not in result


def test_account_summary_missing_credentials_fails_closed():
    result = json.loads(binance_android.account_summary("", ""))
    assert result == {"connected": False, "error": "CREDENTIALS_MISSING"}


def test_restart_recovery_uses_read_only_client_and_does_not_submit(monkeypatch, tmp_path):
    from engine import binance_lifecycle
    from engine import risk_execution

    calls = {"client": 0, "reconcile": 0, "submit": 0}

    class RecoveryClient:
        def __init__(self, api_key, api_secret, *, allow_orders):
            assert api_key == "test-key"
            assert api_secret == "test-secret"
            assert allow_orders is False
            calls["client"] += 1

        def reconcile_protected_buy_otoco(self, *, symbol, list_client_order_id):
            calls["reconcile"] += 1
            return {"state": "PROTECTED", "protected": True,
                    "action_required": False}

    class EmptyGate:
        pass

    monkeypatch.setattr(binance_android, "BinanceSpotTestnetClient", RecoveryClient)
    monkeypatch.setattr(binance_lifecycle, "BinanceProtectedLifecycle",
                        binance_lifecycle.BinanceProtectedLifecycle)
    journal = tmp_path / "empty-journal.json"
    result = json.loads(binance_android.reconcile_saved_orders(
        "test-key", "test-secret", str(journal)
    ))
    assert result["status"] == "NO_JOURNALED_ORDERS"
    assert result["orders_enabled"] is False
    assert result["halted"] is False
    assert calls == {"client": 1, "reconcile": 0, "submit": 0}


def test_restart_recovery_without_credentials_stays_blocked():
    result = json.loads(binance_android.reconcile_saved_orders("", "", "/tmp/not-used"))
    assert result["status"] == "SKIPPED"
    assert result["halted"] is True
    assert result["orders_enabled"] is False
