from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

@dataclass(frozen=True)
class Candle:
    symbol: str
    market: str
    timeframe: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    def __post_init__(self):
        if self.market not in {"FOREX", "GOLD", "CRYPTO"}:
            raise ValueError("Unsupported market.")
        if min(self.open, self.high, self.low, self.close) <= 0 or self.volume < 0:
            raise ValueError("Prices must be positive and volume cannot be negative.")
        if self.high < max(self.open, self.close, self.low) or self.low > min(self.open, self.close, self.high):
            raise ValueError("Candle high/low values are inconsistent.")

class MarketDataProvider(Protocol):
    def candles(self, symbol: str, timeframe: str, limit: int) -> list[Candle]: ...

class UnconfiguredMarketData:
    """Fails closed rather than inventing market data."""
    def candles(self, symbol: str, timeframe: str, limit: int) -> list[Candle]:
        raise RuntimeError("No market-data provider is configured.")
