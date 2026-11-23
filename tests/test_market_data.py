from datetime import datetime, timezone
import pytest
from engine.market_data import Candle, UnconfiguredMarketData

def make_candle(**changes):
    values = dict(symbol="EURUSD", market="FOREX", timeframe="1h", timestamp=datetime.now(timezone.utc), open=1.1, high=1.2, low=1.0, close=1.15, volume=10)
    values.update(changes)
    return Candle(**values)

def test_rejects_inconsistent_candle():
    with pytest.raises(ValueError):
        make_candle(high=1.05)

def test_unconfigured_provider_fails_closed():
    with pytest.raises(RuntimeError, match="No market-data provider"):
        UnconfiguredMarketData().candles("EURUSD", "1h", 100)
