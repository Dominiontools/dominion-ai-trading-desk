from decimal import Decimal as D

import pytest

from engine.binance_lifecycle import BinanceProtectedLifecycle
from engine.risk_execution import (
    BinanceOrderPlan, BinanceTestnetRiskGate,
)


@pytest.fixture
def plan():
    return BinanceOrderPlan(
        symbol="BTCUSDT", side="BUY", quantity="0.001",
        limit_price="50000", stop_loss="49000", take_profit="52000",
        max_planned_loss_quote="1.2", estimated_round_trip_fee_quote="0.1",
        estimated_round_trip_slippage_quote="0.1",
        estimated_spread_cost_quote="0.1", notional_quote="50",
    )


class FakeGate(BinanceTestnetRiskGate):
    def __init__(self):
        pass

    def execute(self, client, plan, *, list_client_order_id):
        if not client.allow_orders:
            raise PermissionError("disabled")
        client.submissions += 1
        return {"orderListId": 123, "clientOrderId": list_client_order_id}


class FakeClient:
    allow_orders = True

    def __init__(self, state):
        self.state = state
        self.submissions = 0
        self.reconciliations = 0

    def reconcile_protected_buy_otoco(self, *, symbol, list_client_order_id):
        self.reconciliations += 1
        return dict(self.state)


def test_reports_protected_only_after_exchange_confirms_both_legs(plan):
    client = FakeClient({
        "state": "PROTECTED", "protected": True, "action_required": False,
        "working_status": "FILLED", "take_profit_status": "NEW",
        "stop_loss_status": "NEW",
    })
    lifecycle = BinanceProtectedLifecycle(FakeGate(), client)
    result = lifecycle.submit_and_verify(plan, list_client_order_id="dominion123")
    assert result["status"] == "PROTECTED"
    assert result["protected"] is True
    assert client.submissions == 1
    assert client.reconciliations == 1
    assert lifecycle.halted is False


def test_unconfirmed_protection_halts_future_submissions(plan):
    client = FakeClient({
        "state": "PROTECTION_UNCONFIRMED", "protected": False,
        "action_required": True,
    })
    lifecycle = BinanceProtectedLifecycle(FakeGate(), client)
    result = lifecycle.submit_and_verify(plan, list_client_order_id="dominion123")
    assert result["protected"] is False
    assert result["operator_action_required"] is True
    assert lifecycle.halted is True
    with pytest.raises(PermissionError, match="halted"):
        lifecycle.submit_and_verify(plan, list_client_order_id="dominion124")
    assert client.submissions == 1


def test_partial_entry_fill_is_explicitly_unprotected_and_halts(plan):
    client = FakeClient({
        "state": "UNPROTECTED_PARTIAL_FILL", "protected": False,
        "action_required": True, "working_status": "PARTIALLY_FILLED",
    })
    lifecycle = BinanceProtectedLifecycle(FakeGate(), client)
    result = lifecycle.submit_and_verify(plan, list_client_order_id="dominion123")
    assert result["status"] == "UNPROTECTED_PARTIAL_FILL"
    assert result["protected"] is False
    assert result["halted"] is True
    assert result["operator_action_required"] is True
    with pytest.raises(PermissionError, match="halted"):
        lifecycle.submit_and_verify(plan, list_client_order_id="dominion124")
    assert client.submissions == 1


def test_partial_entry_fill_remains_halted_after_restart(plan, tmp_path):
    journal = tmp_path / "private" / "binance-lifecycle.json"
    client = FakeClient({
        "state": "UNPROTECTED_PARTIAL_FILL", "protected": False,
        "action_required": True, "working_status": "PARTIALLY_FILLED",
    })
    first = BinanceProtectedLifecycle(FakeGate(), client, journal_path=journal)
    submitted = first.submit_and_verify(plan, list_client_order_id="dominion123")
    assert submitted["status"] == "UNPROTECTED_PARTIAL_FILL"

    restarted = BinanceProtectedLifecycle(FakeGate(), client, journal_path=journal)
    result = restarted.reconcile_after_restart()
    assert result["status"] == "RECONCILIATION_REQUIRED"
    assert result["halted"] is True
    assert result["operator_action_required"] is True
    assert result["orders"][0]["state"] == "UNPROTECTED_PARTIAL_FILL"
    assert result["orders"][0]["safe"] is False
    assert result["unresolved"][0]["state"] == "UNPROTECTED_PARTIAL_FILL"
    assert client.submissions == 1

def test_duplicate_order_list_id_is_never_submitted_twice(plan):
    client = FakeClient({
        "state": "PROTECTED", "protected": True, "action_required": False,
    })
    lifecycle = BinanceProtectedLifecycle(FakeGate(), client)
    lifecycle.submit_and_verify(plan, list_client_order_id="dominion123")
    with pytest.raises(PermissionError, match="Duplicate"):
        lifecycle.submit_and_verify(plan, list_client_order_id="dominion123")
    assert client.submissions == 1


def test_uncertain_submission_halts_and_does_not_retry(plan):
    class BrokenClient(FakeClient):
        def reconcile_protected_buy_otoco(self, **kwargs):
            raise TimeoutError("network timeout")

    client = BrokenClient({})
    lifecycle = BinanceProtectedLifecycle(FakeGate(), client)
    with pytest.raises(TimeoutError):
        lifecycle.submit_and_verify(plan, list_client_order_id="dominion123")
    assert lifecycle.halted is True
    assert lifecycle.last_result["status"] == "SUBMISSION_OR_RECONCILIATION_UNKNOWN"
    with pytest.raises(PermissionError, match="halted"):
        lifecycle.submit_and_verify(plan, list_client_order_id="dominion124")
    assert client.submissions == 1


def test_reconcile_existing_never_submits_an_order(plan):
    client = FakeClient({
        "state": "PROTECTED", "protected": True, "action_required": False,
    })
    lifecycle = BinanceProtectedLifecycle(FakeGate(), client)
    result = lifecycle.reconcile_existing(
        symbol=plan.symbol, list_client_order_id="dominion123"
    )
    assert result["protected"] is True
    assert client.submissions == 0
    assert client.reconciliations == 1


def test_pending_exit_legs_are_rechecked_before_failing_closed(plan):
    class SequenceClient(FakeClient):
        def __init__(self):
            super().__init__({})
            self.states = [
                {"state": "PROTECTION_UNCONFIRMED", "protected": False,
                 "action_required": True, "take_profit_status": "PENDING_NEW",
                 "stop_loss_status": "PENDING_NEW"},
                {"state": "PROTECTED", "protected": True, "action_required": False,
                 "take_profit_status": "NEW", "stop_loss_status": "NEW"},
            ]

        def reconcile_protected_buy_otoco(self, **kwargs):
            self.reconciliations += 1
            return self.states.pop(0)

    waits = []
    client = SequenceClient()
    lifecycle = BinanceProtectedLifecycle(
        FakeGate(), client, reconcile_attempts=3,
        reconcile_interval_seconds=0.2, wait=waits.append,
    )
    result = lifecycle.submit_and_verify(plan, list_client_order_id="dominion123")
    assert result["protected"] is True
    assert client.reconciliations == 2
    assert waits == [0.2]


def test_submitted_order_id_survives_process_restart(plan, tmp_path):
    journal = tmp_path / "private" / "binance-lifecycle.json"
    client = FakeClient({
        "state": "PROTECTED", "protected": True, "action_required": False,
    })
    first = BinanceProtectedLifecycle(FakeGate(), client, journal_path=journal)
    first.submit_and_verify(plan, list_client_order_id="dominion123")

    restarted = BinanceProtectedLifecycle(FakeGate(), client, journal_path=journal)
    with pytest.raises(PermissionError, match="Duplicate"):
        restarted.submit_and_verify(plan, list_client_order_id="dominion123")
    assert client.submissions == 1
    assert restarted.halted is False


def test_uncertain_submission_halt_survives_process_restart(plan, tmp_path):
    journal = tmp_path / "private" / "binance-lifecycle.json"

    class BrokenClient(FakeClient):
        def reconcile_protected_buy_otoco(self, **kwargs):
            raise TimeoutError("network timeout")

    client = BrokenClient({})
    first = BinanceProtectedLifecycle(FakeGate(), client, journal_path=journal)
    with pytest.raises(TimeoutError):
        first.submit_and_verify(plan, list_client_order_id="dominion123")

    restarted = BinanceProtectedLifecycle(FakeGate(), client, journal_path=journal)
    assert restarted.halted is True
    assert restarted.last_result["status"] == "SUBMISSION_OR_RECONCILIATION_UNKNOWN"
    with pytest.raises(PermissionError, match="halted"):
        restarted.submit_and_verify(plan, list_client_order_id="dominion124")
    assert client.submissions == 1


def test_corrupt_lifecycle_journal_fails_closed(plan, tmp_path):
    journal = tmp_path / "private" / "binance-lifecycle.json"
    journal.parent.mkdir(parents=True)
    journal.write_text("{not-json", encoding="utf-8")
    client = FakeClient({
        "state": "PROTECTED", "protected": True, "action_required": False,
    })
    lifecycle = BinanceProtectedLifecycle(FakeGate(), client, journal_path=journal)
    assert lifecycle.halted is True
    assert lifecycle.last_result["status"] == "LIFECYCLE_JOURNAL_INVALID"
    with pytest.raises(PermissionError, match="halted"):
        lifecycle.submit_and_verify(plan, list_client_order_id="dominion124")
    assert client.submissions == 0


def test_reconcile_existing_persists_order_id_and_protection_state(plan, tmp_path):
    journal = tmp_path / "private" / "binance-lifecycle.json"
    client = FakeClient({
        "state": "PROTECTED", "protected": True, "action_required": False,
    })
    first = BinanceProtectedLifecycle(FakeGate(), client, journal_path=journal)
    first.reconcile_existing(symbol=plan.symbol, list_client_order_id="dominion123")

    restarted = BinanceProtectedLifecycle(FakeGate(), client, journal_path=journal)
    assert restarted.halted is False
    with pytest.raises(PermissionError, match="Duplicate"):
        restarted.submit_and_verify(plan, list_client_order_id="dominion123")
    assert client.submissions == 0



def test_restart_reconciliation_uses_persisted_symbols_and_never_submits(plan, tmp_path):
    journal = tmp_path / "private" / "binance-lifecycle.json"
    client = FakeClient({
        "state": "PROTECTED", "protected": True, "action_required": False,
    })
    first = BinanceProtectedLifecycle(FakeGate(), client, journal_path=journal)
    first.submit_and_verify(plan, list_client_order_id="dominion123")

    restarted = BinanceProtectedLifecycle(FakeGate(), client, journal_path=journal)
    result = restarted.reconcile_after_restart()
    assert result["status"] == "RECONCILED"
    assert result["halted"] is False
    assert result["orders"] == [{
        "order_list_id": "dominion123", "symbol": "BTCUSDT",
        "state": "PROTECTED", "safe": True,
    }]
    assert client.submissions == 1


def test_restart_reconciliation_keeps_halt_if_any_order_is_unresolved(plan, tmp_path):
    journal = tmp_path / "private" / "binance-lifecycle.json"
    client = FakeClient({
        "state": "PROTECTION_UNCONFIRMED", "protected": False,
        "action_required": True,
    })
    first = BinanceProtectedLifecycle(FakeGate(), client, journal_path=journal)
    first.submit_and_verify(plan, list_client_order_id="dominion123")

    restarted = BinanceProtectedLifecycle(FakeGate(), client, journal_path=journal)
    result = restarted.reconcile_after_restart()
    assert result["status"] == "RECONCILIATION_REQUIRED"
    assert result["halted"] is True
    assert result["operator_action_required"] is True
    assert client.submissions == 1


def test_legacy_journal_without_symbols_fails_closed_on_restart_reconciliation(plan, tmp_path):
    import json

    journal = tmp_path / "private" / "binance-lifecycle.json"
    journal.parent.mkdir(parents=True)
    journal.write_text(json.dumps({
        "version": 1, "submitted_ids": ["dominion123"],
        "halted": True, "last_result": None,
    }), encoding="utf-8")
    client = FakeClient({
        "state": "PROTECTED", "protected": True, "action_required": False,
    })
    restarted = BinanceProtectedLifecycle(FakeGate(), client, journal_path=journal)
    result = restarted.reconcile_after_restart()
    assert result["status"] == "RECONCILIATION_REQUIRED"
    assert result["halted"] is True
    assert result["unresolved"][0]["reason"] == "SYMBOL_MISSING_FROM_LEGACY_JOURNAL"
    assert client.reconciliations == 0
    assert client.submissions == 0


def test_corrupt_journal_cannot_be_cleared_by_restart_reconciliation(plan, tmp_path):
    journal = tmp_path / "private" / "binance-lifecycle.json"
    journal.parent.mkdir(parents=True)
    journal.write_text("{broken", encoding="utf-8")
    client = FakeClient({
        "state": "PROTECTED", "protected": True, "action_required": False,
    })
    lifecycle = BinanceProtectedLifecycle(FakeGate(), client, journal_path=journal)
    result = lifecycle.reconcile_after_restart()
    assert result["status"] == "LIFECYCLE_JOURNAL_INVALID"
    assert result["halted"] is True
    assert result["operator_action_required"] is True
    assert client.reconciliations == 0
    assert client.submissions == 0
    with pytest.raises(PermissionError, match="halted"):
        lifecycle.submit_and_verify(plan, list_client_order_id="dominion999")


def test_reconcile_existing_does_not_clear_another_unresolved_order(plan, tmp_path):
    import json

    journal = tmp_path / "private" / "binance-lifecycle.json"
    journal.parent.mkdir(parents=True)
    journal.write_text(json.dumps({
        "version": 1,
        "submitted_ids": ["good123", "bad123"],
        "submitted_symbols": {"good123": "BTCUSDT", "bad123": "ETHUSDT"},
        "halted": True,
        "last_result": None,
    }), encoding="utf-8")

    class MixedClient(FakeClient):
        def reconcile_protected_buy_otoco(self, *, symbol, list_client_order_id):
            self.reconciliations += 1
            if list_client_order_id == "good123":
                return {"state": "PROTECTED", "protected": True,
                        "action_required": False}
            return {"state": "PROTECTION_UNCONFIRMED", "protected": False,
                    "action_required": True}

    client = MixedClient({})
    lifecycle = BinanceProtectedLifecycle(FakeGate(), client, journal_path=journal)
    result = lifecycle.reconcile_existing(
        symbol="BTCUSDT", list_client_order_id="good123"
    )
    assert result["protected"] is True
    assert result["halted"] is True
    assert result["status"] == "RECONCILIATION_REQUIRED"
    assert result["unresolved"][0]["order_list_id"] == "bad123"
    assert client.reconciliations == 2


def test_restart_reconciliation_records_exchange_query_failures_and_stays_halted(plan, tmp_path):
    journal = tmp_path / "private" / "binance-lifecycle.json"
    client = FakeClient({})
    first = BinanceProtectedLifecycle(FakeGate(), client, journal_path=journal)
    first.reconcile_existing(symbol="BTCUSDT", list_client_order_id="dominion123")

    class BrokenReconcileClient(FakeClient):
        def reconcile_protected_buy_otoco(self, **kwargs):
            raise TimeoutError("temporary network error")

    restarted = BinanceProtectedLifecycle(
        FakeGate(), BrokenReconcileClient({}), journal_path=journal
    )
    result = restarted.reconcile_after_restart()
    assert result["status"] == "RECONCILIATION_REQUIRED"
    assert result["halted"] is True
    assert result["unresolved"][0]["reason"] == "EXCHANGE_QUERY_FAILED"
    assert result["unresolved"][0]["error_type"] == "TimeoutError"


def test_confirmed_stop_loss_is_recorded_once_in_daily_loss_ledger(plan, tmp_path):
    from datetime import datetime, timezone
    from decimal import Decimal
    from engine.binance_daily_loss import BinanceDailyLossLedger

    journal = tmp_path / "private" / "binance-lifecycle.json"
    ledger = BinanceDailyLossLedger(tmp_path / "private" / "daily-loss.jsonl")

    class SequenceClient(FakeClient):
        def __init__(self):
            super().__init__({})
            self.states = [
                {"state": "PROTECTED", "protected": True, "action_required": False},
                {"state": "EXITED_STOP_LOSS", "protected": False, "action_required": False},
            ]
            self.last_state = self.states[0]

        def reconcile_protected_buy_otoco(self, **kwargs):
            self.reconciliations += 1
            if self.states:
                self.last_state = self.states.pop(0)
            return dict(self.last_state)

    client = SequenceClient()
    first = BinanceProtectedLifecycle(
        FakeGate(), client, journal_path=journal, daily_loss_ledger=ledger
    )
    first.submit_and_verify(plan, list_client_order_id="dominion123")
    restarted = BinanceProtectedLifecycle(
        FakeGate(), client, journal_path=journal, daily_loss_ledger=ledger
    )
    result = restarted.reconcile_after_restart()
    assert result["status"] == "RECONCILED"
    assert result["halted"] is False
    assert ledger.loss_for_day() == Decimal(plan.max_planned_loss_quote)
    repeated = restarted.reconcile_after_restart()
    assert repeated["status"] == "RECONCILED"
    assert ledger.loss_for_day() == Decimal(plan.max_planned_loss_quote)


def test_stop_loss_without_saved_risk_basis_stays_halted(plan, tmp_path):
    import json

    journal = tmp_path / "private" / "binance-lifecycle.json"
    journal.parent.mkdir(parents=True)
    journal.write_text(json.dumps({
        "version": 1,
        "submitted_ids": ["dominion123"],
        "submitted_symbols": {"dominion123": "BTCUSDT"},
        "halted": True,
        "last_result": None,
    }), encoding="utf-8")

    client = FakeClient({
        "state": "EXITED_STOP_LOSS", "protected": False, "action_required": False,
    })
    lifecycle = BinanceProtectedLifecycle(FakeGate(), client, journal_path=journal)
    result = lifecycle.reconcile_after_restart()
    assert result["status"] == "RECONCILIATION_REQUIRED"
    assert result["halted"] is True
    assert result["unresolved"][0]["reason"] == "STOP_LOSS_RISK_BASIS_MISSING"
    # The order-level status must reflect the final ledger/risk decision,
    # not merely the exchange's STOP_LOSS terminal state.
    assert result["orders"][0]["safe"] is False


def test_emergency_flatten_requires_explicit_operator_approval(plan, tmp_path):
    journal = tmp_path / "private" / "binance-lifecycle.json"

    class OrderEnabledClient(FakeClient):
        allow_orders = True

    client = OrderEnabledClient({})
    lifecycle = BinanceProtectedLifecycle(FakeGate(), client, journal_path=journal)
    lifecycle.reconcile_existing(symbol="BTCUSDT", list_client_order_id="dominion123")
    with pytest.raises(PermissionError, match="Explicit operator approval"):
        lifecycle.emergency_flatten(
            symbol="BTCUSDT", list_client_order_id="dominion123",
            reference_price="50000",
        )
    assert client.submissions == 0
    assert lifecycle.last_result["status"] != "EMERGENCY_CLOSE_PENDING"


def test_emergency_flatten_is_write_ahead_persisted_and_keeps_engine_halted(plan, tmp_path):
    journal = tmp_path / "private" / "binance-lifecycle.json"

    class EmergencyClient(FakeClient):
        allow_orders = True

        def query_order_by_client_id(self, *, symbol, client_order_id):
            statuses = {
                "dominion123E": {"status": "FILLED", "executedQty": "0.001"},
                "dominion123T": {"status": "CANCELED"},
                "dominion123S": {"status": "CANCELED"},
            }
            return dict(statuses[client_order_id])

        def account_open_orders(self, *, symbol):
            return []

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
            return {"balances": [
                {"asset": "BTC", "free": "0", "locked": "0"},
                {"asset": "USDT", "free": "100", "locked": "0"},
            ]}

    client = EmergencyClient({
        "state": "PROTECTION_UNCONFIRMED", "protected": False,
        "action_required": True,
    })
    lifecycle = BinanceProtectedLifecycle(FakeGate(), client, journal_path=journal)
    lifecycle.reconcile_existing(symbol="BTCUSDT", list_client_order_id="dominion123")
    result = lifecycle.emergency_flatten(
        symbol="BTCUSDT", list_client_order_id="dominion123",
        reference_price="50000", operator_approved=True,
    )
    assert result["status"] == "EMERGENCY_FLAT_CONFIRMED"
    assert result["sold_quantity"] == "0"
    assert lifecycle.halted is True

    restarted = BinanceProtectedLifecycle(FakeGate(), client, journal_path=journal)
    assert restarted.halted is True
    assert restarted.last_result["status"] == "EMERGENCY_FLAT_CONFIRMED"
    assert restarted.last_result["emergency_client_order_id"].startswith("em")
    repeated = restarted.emergency_flatten(
        symbol="BTCUSDT", list_client_order_id="dominion123",
        reference_price="50000", operator_approved=True,
    )
    assert repeated["status"] == "EMERGENCY_FLAT_CONFIRMED"


def test_uncertain_emergency_close_is_never_submitted_again(plan, tmp_path):
    journal = tmp_path / "private" / "binance-lifecycle.json"

    class UncertainClient(FakeClient):
        allow_orders = True

        def query_order_by_client_id(self, **kwargs):
            raise TimeoutError("exchange query timed out")

    client = UncertainClient({
        "state": "PROTECTION_UNCONFIRMED", "protected": False,
        "action_required": True,
    })
    lifecycle = BinanceProtectedLifecycle(FakeGate(), client, journal_path=journal)
    lifecycle.reconcile_existing(symbol="BTCUSDT", list_client_order_id="dominion123")
    first = lifecycle.emergency_flatten(
        symbol="BTCUSDT", list_client_order_id="dominion123",
        reference_price="50000", operator_approved=True,
    )
    assert first["status"] == "EMERGENCY_CLOSE_UNCONFIRMED"
    with pytest.raises(PermissionError, match="already attempted"):
        lifecycle.emergency_flatten(
            symbol="BTCUSDT", list_client_order_id="dominion123",
            reference_price="50000",
        )
