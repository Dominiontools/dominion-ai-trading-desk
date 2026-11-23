from dataclasses import dataclass
from .desk import DeskDecision, TradeCandidate

@dataclass(frozen=True)
class PaperFill:
    symbol: str
    side: str
    status: str
    mode: str = "PAPER_ONLY"

class PaperSniper:
    """Produces a simulated fill record only; never connects to a broker."""
    def submit(self, candidate: TradeCandidate, decision: DeskDecision) -> PaperFill:
        if not decision.approved:
            raise ValueError("Candidate was not approved by the Risk Agent.")
        return PaperFill(candidate.symbol, candidate.side, "SIMULATED_FILL")
