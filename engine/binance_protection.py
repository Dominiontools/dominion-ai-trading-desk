"""Fail-closed reconciliation for Binance Spot Testnet OTOCO brackets."""
from __future__ import annotations

TERMINAL_NO_FILL = {"CANCELED", "EXPIRED", "REJECTED"}
ACTIVE = {"NEW"}


def classify_otoco(working_status: str, take_profit_status: str | None = None,
                   stop_loss_status: str | None = None) -> dict:
    """Classify an entry/bracket using exchange-reported child order statuses.

    PROTECTED is returned only after a full entry fill and both exit legs are
    confirmed NEW. A FOK partial fill is treated as an emergency condition.
    """
    working = (working_status or "").upper()
    tp = (take_profit_status or "").upper()
    sl = (stop_loss_status or "").upper()
    if working in TERMINAL_NO_FILL:
        return {"state": "NO_POSITION", "protected": False, "action_required": False}
    if working == "PARTIALLY_FILLED":
        return {"state": "UNPROTECTED_PARTIAL_FILL", "protected": False, "action_required": True}
    if working != "FILLED":
        return {"state": "ENTRY_PENDING", "protected": False, "action_required": False}
    if tp == "FILLED" and sl in {"CANCELED", "EXPIRED"}:
        return {"state": "EXITED_TAKE_PROFIT", "protected": False, "action_required": False}
    if sl == "FILLED" and tp in {"CANCELED", "EXPIRED"}:
        return {"state": "EXITED_STOP_LOSS", "protected": False, "action_required": False}
    if tp in ACTIVE and sl in ACTIVE:
        return {"state": "PROTECTED", "protected": True, "action_required": False}
    return {"state": "PROTECTION_UNCONFIRMED", "protected": False, "action_required": True}
