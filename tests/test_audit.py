import json
import pytest
from engine.audit import AuditEvent, serialize_event

def test_audit_event_is_paper_only():
    event = AuditEvent.create("SIGNAL", "EURUSD", "Test event")
    payload = json.loads(serialize_event(event))
    assert payload["mode"] == "PAPER_ONLY"
    assert payload["symbol"] == "EURUSD"

def test_audit_rejects_non_paper_event():
    with pytest.raises(ValueError):
        serialize_event(AuditEvent("ORDER", "EURUSD", "blocked", mode="LIVE"))
