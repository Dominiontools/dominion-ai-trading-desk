from datetime import datetime, timezone
from decimal import Decimal

import pytest

from engine.binance_risk_context import BinanceRiskContextProvider
from engine.binance_daily_loss import BinanceDailyLossLedger


class AccountClient:
    def __init__(self, can_trade=True):
        self.can_trade = can_trade

    def account(self):
        return {
            "canTrade": self.can_trade,
            "balances": [
                {"asset": "USDT", "free": "250.00", "locked": "10.00"},
                {"asset": "BTC", "free": "0.1", "locked": "0"},
            ],
        }


class Recovery:
    def __init__(self, result):
        self.result = result

    def reconcile_after_restart(self):
        return dict(self.result)


def test_provider_builds_conservative_verified_usdt_risk_context(tmp_path):
    now = datetime(2026, 11, 25, 12, tzinfo=timezone.utc)
    ledger = BinanceDailyLossLedger(tmp_path / "loss.jsonl")
    ledger.record_stop_loss(
        order_list_id="loss001", symbol="BTCUSDT",
        planned_loss_quote="2.50", recorded_at=now,
    )
    recovery = Recovery({
        "status": "RECONCILED", "halted": False,
        "operator_action_required": False,
        "orders": [
            {"order_list_id": "old001", "state": "EXITED_TAKE_PROFIT", "safe": True},
        ],
    })
    provider = BinanceRiskContextProvider(
        AccountClient(), recovery, ledger,
    )
    snapshot = provider.snapshot(now=now)
    assert snapshot.account_snapshot_verified is True
    assert snapshot.daily_loss_verified is True
    assert snapshot.quote_asset == "USDT"
    assert snapshot.context.equity_quote == Decimal("260.00")
    assert snapshot.context.available_quote == Decimal("250.00")
    assert snapshot.context.daily_loss_quote == Decimal("2.50")
    assert snapshot.context.open_positions == 0


def test_provider_counts_confirmed_protected_position_and_blocks_new_trade(tmp_path):
    ledger = BinanceDailyLossLedger(tmp_path / "loss.jsonl")
    recovery = Recovery({
        "status": "RECONCILED", "halted": False,
        "operator_action_required": False,
        "orders": [
            {"order_list_id": "open001", "state": "PROTECTED", "safe": True},
        ],
    })
    snapshot = BinanceRiskContextProvider(
        AccountClient(), recovery, ledger,
    ).snapshot()
    assert snapshot.context.open_positions == 1


def test_provider_blocks_if_recovery_is_halted_or_unresolved(tmp_path):
    ledger = BinanceDailyLossLedger(tmp_path / "loss.jsonl")
    recovery = Recovery({
        "status": "RECONCILIATION_REQUIRED", "halted": True,
        "operator_action_required": True, "orders": [],
    })
    with pytest.raises(PermissionError, match="unresolved"):
        BinanceRiskContextProvider(
            AccountClient(), recovery, ledger,
        ).snapshot()


def test_provider_requires_confirmed_account_trade_permission(tmp_path):
    ledger = BinanceDailyLossLedger(tmp_path / "loss.jsonl")
    recovery = Recovery({"status": "NO_JOURNALED_ORDERS", "halted": False, "orders": []})
    with pytest.raises(PermissionError, match="trading permission"):
        BinanceRiskContextProvider(
            AccountClient(can_trade=False), recovery, ledger,
        ).snapshot()


def test_provider_blocks_when_daily_loss_ledger_is_corrupt(tmp_path):
    path = tmp_path / "loss.jsonl"
    path.write_text("{broken", encoding="utf-8")
    recovery = Recovery({"status": "NO_JOURNALED_ORDERS", "halted": False, "orders": []})
    with pytest.raises(RuntimeError, match="ledger is invalid"):
        BinanceRiskContextProvider(
            AccountClient(), recovery, BinanceDailyLossLedger(path),
        ).snapshot()
