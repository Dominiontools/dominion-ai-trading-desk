from datetime import datetime, timedelta, timezone
from engine.market_data import Candle
from engine.strategies import MovingAverageCross
import pytest

def candles(prices):
    start = datetime.now(timezone.utc)
    return [Candle("BTCUSDT", "CRYPTO", "1h", start + timedelta(hours=i), p, p, p, p, 1) for i, p in enumerate(prices)]

def test_strategy_waits_for_enough_candles():
    assert MovingAverageCross(2, 3).evaluate(candles([10, 10, 10])) is None

def test_strategy_detects_buy_cross():
    signal = MovingAverageCross(2, 3).evaluate(candles([10, 10, 10, 20]))
    assert signal is not None and signal.side == "BUY"

def test_strategy_rejects_invalid_periods():
    with pytest.raises(ValueError):
        MovingAverageCross(3, 3)
