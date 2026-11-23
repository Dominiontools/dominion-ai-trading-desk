from dataclasses import dataclass
from enum import Enum

class AgentStatus(str, Enum):
    STAGED = "STAGED"
    READY = "READY"
    PAUSED = "PAUSED"

@dataclass(frozen=True)
class Agent:
    name: str
    purpose: str
    market_scope: str
    status: AgentStatus = AgentStatus.STAGED

AGENTS = (
    Agent("SCANNER", "Detect configured market opportunities", "Forex, Gold, Crypto", AgentStatus.READY),
    Agent("RISK", "Validate size, exposure, liquidity and limits", "All markets", AgentStatus.READY),
    Agent("SNIPER", "Route approved simulated orders", "Separate market adapters"),
    Agent("WHALE", "Monitor large participant activity", "Crypto first; Forex flow proxies"),
    Agent("RUG", "Detect contract, liquidity and wallet risks", "Crypto; Forex feed anomaly checks"),
    Agent("EXIT", "Manage simulated stops, targets and trailing exits", "All markets"),
    Agent("HYPE", "Assess social and economic sentiment", "Crypto social; Forex news"),
    Agent("DESK MANAGER", "Coordinate agents and audit decisions", "All markets", AgentStatus.READY),
)

class DeskManager:
    """Coordinates analysis only; it never submits orders."""
    def roster(self) -> tuple[Agent, ...]:
        return AGENTS

    def can_route_live_orders(self) -> bool:
        return False
