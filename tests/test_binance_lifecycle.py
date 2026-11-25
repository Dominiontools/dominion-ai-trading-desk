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
