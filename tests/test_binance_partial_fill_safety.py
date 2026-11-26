from engine.binance_lifecycle import BinanceProtectedLifecycle
from engine.risk_execution import BinanceOrderPlan, BinanceTestnetRiskGate


def _plan():
    return BinanceOrderPlan(
        symbol="BTCUSDT",
        side="BUY",
        quantity="0.001",
        limit_price="50000",
        stop_loss="49000",
        take_profit="52000",
        max_planned_loss_quote="1.2",
        estimated_round_trip_fee_quote="0.1",
        estimated_round_trip_slippage_quote="0.1",
        estimated_spread_cost_quote="0.1",
        notional_quote="50",
    )


class _Gate(BinanceTestnetRiskGate):
    def __init__(self):
        self.submissions = 0

    def execute(self, client, plan, *, list_client_order_id):
        self.submissions += 1
        return {"orderListId": 123, "clientOrderId": list_client_order_id}


class _PartialFillClient:
    allow_orders = True

    def __init__(self):
        self.queries = 0

    def reconcile_protected_buy_otoco(self, *, symbol, list_client_order_id):
        self.queries += 1
        return {
            "state": "UNPROTECTED_PARTIAL_FILL",
            "protected": False,
            "action_required": True,
            "working_status": "PARTIALLY_FILLED",
            "take_profit_status": None,
            "stop_loss_status": None,
        }


def test_partial_fill_is_never_reported_as_protected_or_safe():
    gate = _Gate()
    client = _PartialFillClient()
    lifecycle = BinanceProtectedLifecycle(
        gate, client, reconcile_attempts=2, wait=lambda _: None
    )

    result = lifecycle.submit_and_verify(
        _plan(), list_client_order_id="dompartial123"
    )

    assert result["protected"] is False
    assert result["halted"] is True
    assert result["operator_action_required"] is True
    assert result["exchange_state"]["state"] == "UNPROTECTED_PARTIAL_FILL"
    assert gate.submissions == 1
    assert client.queries == 2


def test_partial_fill_halt_survives_restart_and_blocks_new_entries(tmp_path):
    journal = tmp_path / "binance-lifecycle.json"
    gate = _Gate()
    client = _PartialFillClient()
    first = BinanceProtectedLifecycle(
        gate, client, journal_path=journal, reconcile_attempts=1
    )

    first.submit_and_verify(_plan(), list_client_order_id="dompartial123")

    restarted = BinanceProtectedLifecycle(
        gate, client, journal_path=journal, reconcile_attempts=1
    )
    assert restarted.halted is True
    result = restarted.reconcile_after_restart()
    assert result["status"] == "RECONCILIATION_REQUIRED"
    assert result["halted"] is True
    assert result["unresolved"][0]["state"] == "UNPROTECTED_PARTIAL_FILL"
    try:
        restarted.submit_and_verify(_plan(), list_client_order_id="dompartial124")
    except PermissionError as exc:
        assert "halted" in str(exc)
    else:
        raise AssertionError("A new entry must remain blocked after a partial fill.")
    assert gate.submissions == 1
