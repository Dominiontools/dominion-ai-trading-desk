from dataclasses import dataclass

@dataclass(frozen=True)
class RiskConfig:
    demo_only: bool = True
    live_trading_enabled: bool = False
    max_risk_per_trade_pct: float = 0.5
    max_daily_loss_pct: float = 2.0
    max_open_positions: int = 1
    max_slippage_pct: float = 0.15


def assert_demo_only(config: RiskConfig) -> None:
    if not config.demo_only or config.live_trading_enabled:
        raise RuntimeError("Safety lock: this foundation build permits demo/paper trading only.")


def validate_risk(config: RiskConfig, risk_pct: float, open_positions: int, daily_loss_pct: float, slippage_pct: float) -> tuple[bool, str]:
    assert_demo_only(config)
    if risk_pct <= 0 or risk_pct > config.max_risk_per_trade_pct:
        return False, "Trade risk exceeds configured per-trade limit."
    if open_positions >= config.max_open_positions:
        return False, "Maximum open positions reached."
    if daily_loss_pct >= config.max_daily_loss_pct:
        return False, "Daily loss limit reached."
    if slippage_pct < 0 or slippage_pct > config.max_slippage_pct:
        return False, "Slippage exceeds configured limit."
    return True, "Risk checks passed for simulation only."
