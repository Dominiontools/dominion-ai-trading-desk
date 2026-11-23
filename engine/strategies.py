from dataclasses import dataclass
from .market_data import Candle

@dataclass(frozen=True)
class StrategySignal:
    symbol: str
    market: str
    side: str
    strategy: str
    reason: str

class MovingAverageCross:
    """Baseline example strategy; not a claim of profitability."""
    name = "SMA_CROSS"

    def __init__(self, fast_period: int = 10, slow_period: int = 30):
        if fast_period < 2 or slow_period <= fast_period:
            raise ValueError("Require 2 <= fast_period < slow_period.")
        self.fast_period, self.slow_period = fast_period, slow_period

    def evaluate(self, candles: list[Candle]) -> StrategySignal | None:
        if len(candles) < self.slow_period + 1:
            return None
        last = candles[-1]
        if any(c.symbol != last.symbol or c.market != last.market for c in candles):
            raise ValueError("Input must contain one symbol and market.")
        closes = [c.close for c in candles]
        f, s = self.fast_period, self.slow_period
        fast_now = sum(closes[-f:]) / f
        slow_now = sum(closes[-s:]) / s
        fast_prev = sum(closes[-f-1:-1]) / f
        slow_prev = sum(closes[-s-1:-1]) / s
        side = "BUY" if fast_prev <= slow_prev and fast_now > slow_now else "SELL" if fast_prev >= slow_prev and fast_now < slow_now else None
        if side is None:
            return None
        return StrategySignal(last.symbol, last.market, side, self.name, "Fast SMA crossed the slow SMA.")
