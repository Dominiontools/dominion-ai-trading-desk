from dataclasses import dataclass

@dataclass(frozen=True)
class RiskLimits:
    max_risk_per_trade_pct: float = 0.01
    max_daily_loss_pct: float = 0.03
    max_open_positions: int = 3
    max_spread_bps: float = 20.0
    max_slippage_bps: float = 15.0
    max_quote_age_seconds: int = 10
    allowed_markets: tuple[str, ...] = ("FOREX", "GOLD", "CRYPTO")

    def __post_init__(self):
        if not 0 < self.max_risk_per_trade_pct <= 0.02:
            raise ValueError("Per-trade risk must be greater than 0 and no more than 2%.")
        if not 0 < self.max_daily_loss_pct <= 0.10:
            raise ValueError("Daily loss limit must be greater than 0 and no more than 10%.")
        if self.max_open_positions < 1 or self.max_spread_bps <= 0 or self.max_slippage_bps <= 0 or self.max_quote_age_seconds < 1:
            raise ValueError("Position, spread, slippage, and quote-age limits must be positive.")
        if not self.allowed_markets or any(m not in {"FOREX", "GOLD", "CRYPTO"} for m in self.allowed_markets):
            raise ValueError("Allowed markets must be selected from FOREX, GOLD, and CRYPTO.")

@dataclass(frozen=True)
class TradeProposal:
    market: str
    risk_amount: float
    equity: float
    daily_loss_pct: float
    open_positions: int
    spread_bps: float
    estimated_slippage_bps: float
    quote_age_seconds: float
    emergency_stop: bool = False

@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    reasons: tuple[str, ...]


def evaluate_trade(proposal: TradeProposal, limits: RiskLimits = RiskLimits()) -> RiskDecision:
    """Fail-closed pre-trade gate. Approval is not an instruction to place a live order."""
    numeric = (proposal.risk_amount, proposal.equity, proposal.daily_loss_pct,
               proposal.spread_bps, proposal.estimated_slippage_bps, proposal.quote_age_seconds)
    if any(value < 0 for value in numeric) or proposal.equity <= 0:
        raise ValueError("Risk inputs must be non-negative and equity must be positive.")
    if proposal.open_positions < 0:
        raise ValueError("Open position count cannot be negative.")

    reasons: list[str] = []
    if proposal.emergency_stop:
        reasons.append("Emergency stop is active.")
    if proposal.market not in limits.allowed_markets:
        reasons.append("Market is not enabled by the risk policy.")
    if proposal.risk_amount <= 0 or proposal.risk_amount / proposal.equity > limits.max_risk_per_trade_pct:
        reasons.append("Trade risk is zero or exceeds the per-trade risk limit.")
    if proposal.daily_loss_pct >= limits.max_daily_loss_pct:
        reasons.append("Daily loss limit has been reached.")
    if proposal.open_positions >= limits.max_open_positions:
        reasons.append("Maximum number of open positions has been reached.")
    if proposal.spread_bps > limits.max_spread_bps:
        reasons.append("Spread exceeds the configured limit.")
    if proposal.estimated_slippage_bps > limits.max_slippage_bps:
        reasons.append("Estimated slippage exceeds the configured limit.")
    if proposal.quote_age_seconds > limits.max_quote_age_seconds:
        reasons.append("Market quote is stale.")
    return RiskDecision(not reasons, tuple(reasons))
