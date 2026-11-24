from decimal import Decimal as D
import pytest
from engine.risk_execution import (
    BinanceSymbolRules, BinanceTestnetRiskGate, SpotRiskContext, VerifiedFees,
)

@pytest.fixture
def gate():
    return BinanceTestnetRiskGate()

@pytest.fixture
def context():
    return SpotRiskContext(D("20"), D("20"), D("0"), 0)

@pytest.fixture
def rules():
    return BinanceSymbolRules(D("0.01"), D("0.00001"), D("0.00001"),
                              D("100"), D("5"), True)

@pytest.fixture
def fees():
    return VerifiedFees(D("10"), True)

def prepare(gate, context, rules, fees, **overrides):
    values = dict(symbol="BTCUSDT", entry_price="30000.00",
        stop_loss="29900.00", take_profit="30200.00", context=context,
        rules=rules, fees=fees, quote_age_seconds="1", spread_bps="2",
        estimated_slippage_bps="3")
    values.update(overrides)
    return gate.prepare_buy(**values)

def test_prepares_order_with_project_risk_cap(gate, context, rules, fees):
    plan = prepare(gate, context, rules, fees)
    assert plan.side == "BUY" and plan.symbol == "BTCUSDT"
    assert D(plan.max_planned_loss_quote) <= D("0.10")
    assert D(plan.notional_quote) >= D("5")

def test_blocks_unverified_symbol_filters(gate, context, rules, fees):
    unverified = BinanceSymbolRules(rules.tick_size, rules.step_size,
        rules.min_quantity, rules.max_quantity, rules.min_notional, False)
    with pytest.raises(PermissionError, match="filters"):
        prepare(gate, context, unverified, fees)

def test_blocks_unverified_fees(gate, context, rules):
    with pytest.raises(PermissionError, match="fees"):
        prepare(gate, context, rules, VerifiedFees(D("10"), False))

def test_blocks_daily_loss_limit(gate, rules, fees):
    ctx = SpotRiskContext(D("20"), D("20"), D("0.40"), 0)
    with pytest.raises(PermissionError, match="Daily loss"):
        prepare(gate, ctx, rules, fees)

def test_blocks_second_open_position(gate, rules, fees):
    ctx = SpotRiskContext(D("20"), D("20"), D("0"), 1)
    with pytest.raises(PermissionError, match="open-position"):
        prepare(gate, ctx, rules, fees)

def test_blocks_stale_quote(gate, context, rules, fees):
    with pytest.raises(PermissionError, match="stale"):
        prepare(gate, context, rules, fees, quote_age_seconds="11")

def test_blocks_bad_stop_target_direction(gate, context, rules, fees):
    with pytest.raises(ValueError, match="stop-loss"):
        prepare(gate, context, rules, fees, stop_loss="30100")

def test_blocks_minimum_order_exceeding_risk_size(gate, context, fees):
    restrictive = BinanceSymbolRules(D("0.01"), D("0.1"), D("0.1"),
                                     D("100"), D("5"), True)
    with pytest.raises(PermissionError, match="quantity filters"):
        prepare(gate, context, restrictive, fees)

def test_execution_never_sends_unprotected_entry(gate):
    class FakeClient:
        def place_limit_order(self, **kwargs):
            pytest.fail("No exchange request may be sent without protection.")
    with pytest.raises(PermissionError, match="protective"):
        gate.execute(FakeClient(), object())

def test_blocks_emergency_stop(gate, rules, fees):
    ctx = SpotRiskContext(D("20"), D("20"), D("0"), 0, emergency_stop=True)
    with pytest.raises(PermissionError, match="Emergency"):
        prepare(gate, ctx, rules, fees)

def test_blocks_insufficient_quote_balance(gate, context, rules, fees):
    poor_balance = SpotRiskContext(D("20"), D("1"), D("0"), 0)
    with pytest.raises(PermissionError, match="Available quote balance"):
        prepare(gate, poor_balance, rules, fees)
