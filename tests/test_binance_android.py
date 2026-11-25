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

    calls = {"client": 0, "reconcile": 0}

    class RecoveryClient:
        def __init__(self, api_key, api_secret, *, allow_orders):
            assert api_key == "test-key"
            assert api_secret == "test-secret"
            assert allow_orders is False
            calls["client"] += 1

        def reconcile_protected_buy_otoco(self, *, symbol, list_client_order_id):
            assert symbol == "BTCUSDT"
            assert list_client_order_id == "dominion123"
            calls["reconcile"] += 1
            return {"state": "PROTECTED", "protected": True,
                    "action_required": False}

    monkeypatch.setattr(binance_android, "BinanceSpotTestnetClient", RecoveryClient)
    journal = tmp_path / "binance-lifecycle.json"
    journal.write_text(json.dumps({
        "version": 1,
        "submitted_ids": ["dominion123"],
        "submitted_symbols": {"dominion123": "BTCUSDT"},
        "halted": True,
        "last_result": None,
    }), encoding="utf-8")
    result = json.loads(binance_android.reconcile_saved_orders(
        "test-key", "test-secret", str(journal)
    ))
    assert result["status"] == "RECONCILED"
    assert result["orders_enabled"] is False
    assert result["halted"] is False
    assert calls == {"client": 1, "reconcile": 1}


def test_restart_recovery_without_credentials_stays_blocked():
    result = json.loads(binance_android.reconcile_saved_orders("", "", "/tmp/not-used"))
    assert result["status"] == "SKIPPED"
    assert result["halted"] is True
    assert result["orders_enabled"] is False



def test_android_risk_snapshot_returns_only_verified_read_only_context(monkeypatch, tmp_path):
    class RiskClient:
        def __init__(self, api_key, api_secret, *, allow_orders):
            assert api_key == "test-key"
            assert api_secret == "test-secret"
            assert allow_orders is False

        def account(self):
            return {
                "canTrade": True,
                "balances": [
                    {"asset": "USDT", "free": "100.00", "locked": "5.00"},
                ],
            }

    monkeypatch.setattr(binance_android, "BinanceSpotTestnetClient", RiskClient)
    result = json.loads(binance_android.account_risk_snapshot(
        "test-key", "test-secret",
        str(tmp_path / "binance-lifecycle.json"),
        str(tmp_path / "binance-daily-loss.jsonl"),
    ))
    assert result["status"] == "NO_JOURNALED_ORDERS"
    assert result["halted"] is False
    assert result["orders_enabled"] is False
    assert result["risk_context"] == {
        "verified": True, "quote_asset": "USDT",
        "equity_quote": "105.00", "available_quote": "100.00",
        "daily_loss_quote": "0", "open_positions": 0,
        "open_order_lists": 0, "status": "VERIFIED",
    }
    assert "test-secret" not in json.dumps(result)


def test_android_risk_snapshot_blocks_when_account_lacks_trade_permission(monkeypatch, tmp_path):
    class ReadOnlyClient:
        def __init__(self, api_key, api_secret, *, allow_orders):
            assert allow_orders is False

        def account(self):
            return {"canTrade": False, "balances": []}

    monkeypatch.setattr(binance_android, "BinanceSpotTestnetClient", ReadOnlyClient)
    result = json.loads(binance_android.account_risk_snapshot(
        "test-key", "test-secret",
        str(tmp_path / "binance-lifecycle.json"),
        str(tmp_path / "binance-daily-loss.jsonl"),
    ))
    assert result["status"] == "RISK_CONTEXT_BLOCKED"
    assert result["halted"] is True
    assert result["risk_context"]["verified"] is False
    assert result["orders_enabled"] is False
