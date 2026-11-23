import pytest
from engine.desk import DeskManager, TradeCandidate
from engine.paper import PaperSniper

def test_approved_candidate_can_only_create_paper_fill():
    desk = DeskManager()
    candidate = TradeCandidate("EURUSD", "FOREX", "BUY", 0.25, 0.05)
    decision = desk.evaluate(candidate)
    assert decision.approved
    fill = PaperSniper().submit(candidate, decision)
    assert fill.status == "SIMULATED_FILL"
    assert fill.mode == "PAPER_ONLY"

def test_rejected_candidate_cannot_be_submitted():
    desk = DeskManager()
    candidate = TradeCandidate("XAUUSD", "GOLD", "BUY", 2.0, 0.05)
    decision = desk.evaluate(candidate)
    assert not decision.approved
    with pytest.raises(ValueError):
        PaperSniper().submit(candidate, decision)

def test_live_execution_is_unavailable():
    assert DeskManager().live_execution_available() is False
