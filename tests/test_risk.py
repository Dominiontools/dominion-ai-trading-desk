import pytest
from engine.risk import RiskLimits, TradeProposal, evaluate_trade

def proposal(**changes):
    values = dict(market="GOLD", risk_amount=5, equity=1000, daily_loss_pct=0.01,
                  open_positions=0, spread_bps=5, estimated_slippage_bps=5,
                  quote_age_seconds=2)
    values.update(changes)
    return TradeProposal(**values)

def test_safe_proposal_passes_gate():
    assert evaluate_trade(proposal()).approved

def test_emergency_stop_blocks_trade():
    decision = evaluate_trade(proposal(emergency_stop=True))
    assert not decision.approved and any("Emergency stop" in reason for reason in decision.reasons)

def test_risk_over_two_percent_is_blocked():
    decision = evaluate_trade(proposal(risk_amount=21))
    assert not decision.approved

def test_stale_quote_is_blocked():
    decision = evaluate_trade(proposal(quote_age_seconds=11))
    assert not decision.approved

def test_max_daily_loss_is_blocked():
    decision = evaluate_trade(proposal(daily_loss_pct=0.03))
    assert not decision.approved

def test_policy_rejects_more_than_two_percent_per_trade():
    with pytest.raises(ValueError):
        RiskLimits(max_risk_per_trade_pct=0.05)
