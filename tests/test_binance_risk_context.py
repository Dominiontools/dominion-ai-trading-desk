from datetime import datetime, timezone
from decimal import Decimal

import pytest

from engine.binance_risk_context import BinanceRiskContextProvider
from engine.binance_daily_loss import BinanceDailyLossLedger


class AccountClient:
    def __init__(self, can_trade=True, btc_free="0", eth_free="0", free_usdt="250.00", locked_usdt="10.00", open_orders=None):
        self.can_trade = can_trade
        self.btc_free = btc_free
        self.eth_free = eth_free
        self.free_usdt = free_usdt
        self.locked_usdt = locked_usdt
        self.open_orders = [] if open_orders is None else open_orders

    def account(self):
        return {
            "canTrade": self.can_trade,
            "balances": [
                {"asset": "USDT", "free": self.free_usdt, "locked": self.locked_usdt},
                {"asset": "BTC", "free": self.btc_free, "locked": "0"},
                {"asset": "ETH", "free": self.eth_free, "locked": "0"},
            ],
        }

    def account_open_orders(self):
        return self.open_orders


class Recovery:
    def __init__(self, result):
        self.result = result

    def reconcile_after_restart(self):
        return dict(self.result)


def clean_recovery(orders=None):
    return Recovery({
        "status": "RECONCILED" if orders else "NO_JOURNALED_ORDERS",
        "halted": False, "operator_action_required": False,
        "orders": [] if orders is None else orders,
    })


def provider(client, recovery, ledger):
    return BinanceRiskContextProvider(client, recovery, ledger)


def test_provider_builds_verified_risk_context_capped_at_twenty_usdt(tmp_path):
    now = datetime(2026, 11, 25, 12, tzinfo=timezone.utc)
    ledger = BinanceDailyLossLedger(tmp_path / "loss.jsonl")
    ledger.record_stop_loss(
        order_list_id="loss001", symbol="BTCUSDT",
        planned_loss_quote="0.25", recorded_at=now,
    )
    snapshot = provider(AccountClient(), clean_recovery(), ledger).snapshot(now=now)
    assert snapshot.account_snapshot_verified is True
    assert snapshot.daily_loss_verified is True
    assert snapshot.quote_asset == "USDT"
    assert snapshot.actual_equity_quote == Decimal("260.00")
    assert snapshot.risk_capital_cap_quote == Decimal("20")
    assert snapshot.context.equity_quote == Decimal("20")
    assert snapshot.context.available_quote == Decimal("20")
    assert snapshot.context.daily_loss_quote == Decimal("0.25")
    assert snapshot.context.open_positions == 0
    assert snapshot.exchange_open_orders == 0


def test_low_account_balance_is_not_increased_by_risk_cap(tmp_path):
    ledger = BinanceDailyLossLedger(tmp_path / "loss.jsonl")
    snapshot = provider(
        AccountClient(free_usdt="12", locked_usdt="0"), clean_recovery(), ledger,
    ).snapshot()
    assert snapshot.context.equity_quote == Decimal("12")
    assert snapshot.context.available_quote == Decimal("12")


def test_seeded_non_quote_testnet_inventory_does_not_count_as_open_positions(tmp_path):
    ledger = BinanceDailyLossLedger(tmp_path / "loss.jsonl")
    client = AccountClient(btc_free="0.001", eth_free="0.01")
    snapshot = provider(client, clean_recovery(), ledger).snapshot()
    assert snapshot.context.open_positions == 0


def test_provider_counts_confirmed_protected_position_and_blocks_new_trade(tmp_path):
    ledger = BinanceDailyLossLedger(tmp_path / "loss.jsonl")
    recovery = clean_recovery([
        {"order_list_id": "open001", "state": "PROTECTED", "safe": True},
    ])
    snapshot = provider(AccountClient(), recovery, ledger).snapshot()
    assert snapshot.context.open_positions == 1


def test_account_wide_open_order_occupies_one_position_slot(tmp_path):
    ledger = BinanceDailyLossLedger(tmp_path / "loss.jsonl")
    client = AccountClient(open_orders=[
        {"symbol": "BTCUSDT", "side": "SELL", "status": "NEW", "orderId": 123},
        {"symbol": "ETHUSDT", "side": "BUY", "status": "PARTIALLY_FILLED", "orderId": 456},
    ])
    snapshot = provider(client, clean_recovery(), ledger).snapshot()
    assert snapshot.context.open_positions == 1
    assert snapshot.exchange_open_orders == 2


def test_protected_journal_and_oco_legs_are_not_double_counted(tmp_path):
    ledger = BinanceDailyLossLedger(tmp_path / "loss.jsonl")
    recovery = clean_recovery([
        {"order_list_id": "open001", "state": "PROTECTED", "safe": True},
    ])
    client = AccountClient(open_orders=[
        {"symbol": "BTCUSDT", "side": "SELL", "status": "NEW", "orderId": 123},
        {"symbol": "BTCUSDT", "side": "SELL", "status": "NEW", "orderId": 124},
    ])
    snapshot = provider(client, recovery, ledger).snapshot()
    assert snapshot.context.open_positions == 1


def test_provider_fails_closed_on_malformed_open_orders(tmp_path):
    ledger = BinanceDailyLossLedger(tmp_path / "loss.jsonl")
    client = AccountClient(open_orders=[{"symbol": "BTCUSDT", "side": "HOLD", "status": "UNKNOWN"}])
    with pytest.raises(ValueError, match="open-orders response is malformed"):
        provider(client, clean_recovery(), ledger).snapshot()


def test_provider_fails_closed_when_account_wide_open_orders_unavailable(tmp_path):
    class NoOpenOrdersClient(AccountClient):
        account_open_orders = None

    ledger = BinanceDailyLossLedger(tmp_path / "loss.jsonl")
    with pytest.raises(PermissionError, match="cannot be verified"):
        provider(NoOpenOrdersClient(), clean_recovery(), ledger).snapshot()


def test_provider_blocks_if_recovery_is_halted_or_unresolved(tmp_path):
    ledger = BinanceDailyLossLedger(tmp_path / "loss.jsonl")
    recovery = Recovery({
        "status": "RECONCILIATION_REQUIRED", "halted": True,
        "operator_action_required": True, "orders": [],
    })
    with pytest.raises(PermissionError, match="unresolved"):
        provider(AccountClient(), recovery, ledger).snapshot()


def test_provider_requires_confirmed_account_trade_permission(tmp_path):
    ledger = BinanceDailyLossLedger(tmp_path / "loss.jsonl")
    with pytest.raises(PermissionError, match="trading permission"):
        provider(AccountClient(can_trade=False), clean_recovery(), ledger).snapshot()


def test_provider_blocks_when_daily_loss_ledger_is_corrupt(tmp_path):
    path = tmp_path / "loss.jsonl"
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(RuntimeError, match="ledger is invalid"):
        provider(AccountClient(), clean_recovery(), BinanceDailyLossLedger(path)).snapshot()
