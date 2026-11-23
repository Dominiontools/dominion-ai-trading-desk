from dataclasses import dataclass
from .agents import AGENTS
from .safety import RiskConfig, validate_risk

@dataclass(frozen=True)
class TradeCandidate:
    symbol: str
    market: str
    side: str
    risk_pct: float
    estimated_slippage_pct: float = 0.0

@dataclass(frozen=True)
class DeskDecision:
    approved: bool
    symbol: str
    reason: str
    mode: str = "PAPER_ONLY"

class DeskManager:
    """Coordinates specialist checks. This class has no live broker client."""
    def __init__(self, risk_config: RiskConfig | None = None):
        self.risk_config = risk_config or RiskConfig()

    def roster(self):
        return AGENTS

    def evaluate(self, candidate: TradeCandidate, *, open_positions: int = 0, daily_loss_pct: float = 0.0) -> DeskDecision:
        if candidate.market not in {"FOREX", "GOLD", "CRYPTO"}:
            return DeskDecision(False, candidate.symbol, "Unsupported market.")
        if candidate.side not in {"BUY", "SELL"}:
            return DeskDecision(False, candidate.symbol, "Side must be BUY or SELL.")
        ok, reason = validate_risk(
            self.risk_config,
            candidate.risk_pct,
            open_positions,
            daily_loss_pct,
            candidate.estimated_slippage_pct,
        )
        return DeskDecision(ok, candidate.symbol, reason if ok else reason)

    def live_execution_available(self) -> bool:
        return False
