import pytest
from engine.binance_protection import classify_otoco


@pytest.mark.parametrize("status", ["CANCELED", "EXPIRED", "REJECTED"])
def test_fok_entry_without_fill_means_no_position(status):
    assert classify_otoco(status)["state"] == "NO_POSITION"


def test_working_entry_is_not_yet_protected():
    assert classify_otoco("NEW")["state"] == "ENTRY_PENDING"


def test_fok_partial_fill_is_emergency_state():
    result = classify_otoco("PARTIALLY_FILLED")
    assert result["state"] == "UNPROTECTED_PARTIAL_FILL"
    assert result["action_required"] is True


def test_full_fill_is_protected_only_when_both_exit_legs_are_new():
    result = classify_otoco("FILLED", "NEW", "NEW")
    assert result == {"state": "PROTECTED", "protected": True, "action_required": False}


def test_pending_new_response_is_not_yet_confirmed_protection():
    result = classify_otoco("FILLED", "PENDING_NEW", "PENDING_NEW")
    assert result["state"] == "PROTECTION_UNCONFIRMED"
    assert result["action_required"] is True


def test_missing_or_rejected_exit_leg_never_claims_protection():
    for tp, sl in [(None, "NEW"), ("NEW", None), ("REJECTED", "NEW"), ("NEW", "EXPIRED")]:
        assert classify_otoco("FILLED", tp, sl)["protected"] is False


def test_filled_take_profit_means_bracket_closed():
    assert classify_otoco("FILLED", "FILLED", "CANCELED")["state"] == "EXITED_TAKE_PROFIT"


def test_filled_stop_loss_means_bracket_closed():
    assert classify_otoco("FILLED", "EXPIRED", "FILLED")["state"] == "EXITED_STOP_LOSS"
