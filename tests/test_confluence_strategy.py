from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from engine.confluence_strategy import (
    MultiTimeframeConfluenceStrategy, StrategyConfig, TIMEFRAME_PROFILES,
    atr, ema, rsi,
)
from engine.market_data import Candle


def candles(symbol, market, timeframe, count, start, step, spread=0.5):
    result = []
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i in range(count):
        close = start + i * step
        result.append(Candle(
            symbol=symbol, market=market, timeframe=timeframe,
            timestamp=stamp + timedelta(minutes=i),
            open=close - step / 3, high=close + spread,
            low=close - spread, close=close, volume=100 + i,
        ))
    return result


def test_profiles_match_user_timeframe_modes():
    assert TIMEFRAME_PROFILES == {
        "scalp": ("5m", "1h"),
        "intraday": ("15m", "4h"),
        "swing": ("4h", "1d"),
    }


def test_strategy_config_rejects_unsafe_stop_range_and_low_reward_risk():
    with pytest.raises(ValueError):
        StrategyConfig(max_stop_atr=3.0)
    with pytest.raises(ValueError):
        StrategyConfig(min_reward_risk=1.5)


def test_indicators_return_valid_values():
    values = [float(i + 1) for i in range(220)]
    assert ema(values, 50)[-1] > ema(values, 200)[-1]
    assert rsi(values, 14) == 100.0
    bars = candles("EURUSD", "FOREX", "15m", 30, 1.1, 0.0001)
    assert atr(bars, 14) > 0


def test_insufficient_context_returns_no_setup():
    strategy = MultiTimeframeConfluenceStrategy()
    execution = candles("EURUSD", "FOREX", "15m", 100, 1.1, 0.0001)
    context = candles("EURUSD", "FOREX", "4h", 100, 1.1, 0.0005)
    assert strategy.evaluate(execution, context) is None


def test_strategy_rejects_mismatched_timeframes():
    strategy = MultiTimeframeConfluenceStrategy()
    execution = candles("EURUSD", "FOREX", "5m", 220, 1.1, 0.0001)
    context = candles("EURUSD", "FOREX", "1h", 220, 1.1, 0.0005)
    with pytest.raises(ValueError, match="timeframe"):
        strategy.evaluate(execution, context)


def test_strategy_returns_explainable_setup_or_none_for_synthetic_data():
    strategy = MultiTimeframeConfluenceStrategy(StrategyConfig(profile="intraday", score_threshold=6))
    execution = candles("EURUSD", "FOREX", "15m", 240, 1.1, 0.0001)
    context = candles("EURUSD", "FOREX", "4h", 240, 1.0, 0.0005)
    setup = strategy.evaluate(execution, context)
    if setup is not None:
        assert setup.side in {"BUY", "SELL"}
        assert setup.stop_loss > 0
        assert setup.target_2r > 0 and setup.target_3r > 0
        assert setup.risk_distance > 0
        assert setup.score >= setup.score_threshold
        assert setup.reasons
        assert setup.mode == "SIGNAL_ONLY"

def test_uptrend_breakout_generates_setup_with_two_r_and_three_r_targets():
    strategy = MultiTimeframeConfluenceStrategy(
        StrategyConfig(profile="intraday", score_threshold=6)
    )
    execution = candles("EURUSD", "FOREX", "15m", 240, 1.1, 0.0001, spread=0.0005)
    previous = execution[-2]
    breakout = replace(
        execution[-1],
        open=previous.close + 0.0002,
        high=previous.close + 0.0012,
        low=previous.close - 0.0003,
        close=previous.close + 0.0007,
    )
    execution[-1] = breakout
    context = candles("EURUSD", "FOREX", "4h", 240, 1.0, 0.0005, spread=0.001)
    setup = strategy.evaluate(execution, context)
    assert setup is not None
    assert setup.side == "BUY"
    assert setup.score >= 6
    assert setup.target_2r == pytest.approx(setup.entry_price + 2 * setup.risk_distance)
    assert setup.target_3r == pytest.approx(setup.entry_price + 3 * setup.risk_distance)
    assert setup.entry_price > setup.stop_loss
