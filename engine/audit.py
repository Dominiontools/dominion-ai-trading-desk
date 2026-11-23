from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json

@dataclass(frozen=True)
class AuditEvent:
    event_type: str
    symbol: str
    detail: str
    mode: str = "PAPER_ONLY"
    timestamp: str = ""

    @classmethod
    def create(cls, event_type: str, symbol: str, detail: str):
        return cls(event_type, symbol, detail, "PAPER_ONLY", datetime.now(timezone.utc).isoformat())

def serialize_event(event: AuditEvent) -> str:
    if event.mode != "PAPER_ONLY":
        raise ValueError("Only paper-mode events are accepted in this build.")
    return json.dumps(asdict(event), sort_keys=True)
