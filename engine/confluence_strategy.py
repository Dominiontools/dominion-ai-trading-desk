"""Configurable multi-timeframe confluence strategy for Forex, Gold and Crypto.

This module only produces explainable trade setups. It never routes orders.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Sequence

from .market_data import Candle

TIMEFRAME_PROFILES = {
    "scalp": ("5m", "1h"),
    "intraday": ("15m", "4h"),
    "swing": ("4h", "1d"),
}


@dataclass(frozen=True)
class StrategyConfig:
    profile: str = "intraday"
    score_threshold: int = 6
    atr_period: int = 14
    swing_lookback: int = 20
    min_stop_atr: float = 0.8
    max_stop_atr: float = 2.5
    min_reward_risk: float = 2.0
    use_session_filter: bool = False

    def __post_init__(self):
        if self.profile not in TIMEFRAME_PROFILES:
            raise ValueError("Profile must be scalp, intraday, or swing.")
        if not 1 <= self.score_threshold <= 15:
            raise ValueError("Score threshold must be between 1 and 15.")
        if self.atr_period < 2 or self.swing_lookback < 5:
            raise ValueError("ATR period and swing lookback are too small.")
        if not 0.8 <= self.min_stop_atr <= self.max_stop_atr <= 2.5:
            raise ValueError("Stop ATR range must be positive and no wider than 2.5 ATR.")
        if self.min_reward_risk < 2.0:
            raise ValueError("Minimum reward-to-risk cannot be below 2R.")


@dataclass(frozen=True)
class TradeSetup:
    symbol: str
    market: str
    side: str
    strategy: str
    entry_price: float
    stop_loss: float
    target_2r: float
    target_3r: float
    liquidity_target: float
    risk_distance: float
    score: int
    score_threshold: int
    execution_timeframe: str
    context_timeframe: str
    reasons: tuple[str, ...]
    created_at: datetime
    mode: str = "SIGNAL_ONLY"


def _validate_series(candles: Sequence[Candle], symbol: str, timeframe: str) -> list[Candle]:
    result = list(candles)
    if not result:
        raise ValueError("Candle series is empty.")
    if any(c.symbol != symbol or c.timeframe != timeframe for c in result):
        raise ValueError("Candle series contains a different symbol or timeframe.")
    if any(c.timestamp.tzinfo is None or c.timestamp.utcoffset() is None for c in result):
        raise ValueError("All candle timestamps must be timezone-aware.")
    if any(result[i].timestamp >= result[i + 1].timestamp for i in range(len(result) - 1)):
        raise ValueError("Candles must be strictly ordered oldest to newest.")
    if any(not all(isfinite(v) for v in (c.open, c.high, c.low, c.close, c.volume))
           for c in result):
        raise ValueError("Candle values must be finite.")
    return result


def ema(values: Sequence[float], period: int) -> list[float]:
    if period < 2 or len(values) < period:
        raise ValueError("Not enough values for EMA.")
    alpha = 2.0 / (period + 1.0)
    current = sum(values[:period]) / period
    result = [current]
    for value in values[period:]:
        current = value * alpha + current * (1.0 - alpha)
        result.append(current)
    return result


def rsi(values: Sequence[float], period: int = 14) -> float:
    if period < 2 or len(values) <= period:
        raise ValueError("Not enough values for RSI.")
    changes = [values[i] - values[i - 1] for i in range(1, len(values))]
    gains = [max(change, 0.0) for change in changes[:period]]
    losses = [max(-change, 0.0) for change in changes[:period]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    for change in changes[period:]:
        avg_gain = (avg_gain * (period - 1) + max(change, 0.0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-change, 0.0)) / period
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def atr(candles: Sequence[Candle], period: int = 14) -> float:
    if period < 2 or len(candles) <= period:
        raise ValueError("Not enough candles for ATR.")
    true_ranges = []
    for index in range(1, len(candles)):
        current, previous = candles[index], candles[index - 1]
        true_ranges.append(max(
            current.high - current.low,
            abs(current.high - previous.close),
            abs(current.low - previous.close),
        ))
    return sum(true_ranges[-period:]) / period


def _macd_direction(closes: Sequence[float]) -> str | None:
    if len(closes) < 35:
        return None
    fast, slow = ema(closes, 12), ema(closes, 26)
    # Align the two EMA series at the newest common index.
    macd_line = fast[-len(slow):]
    macd_line = [a - b for a, b in zip(macd_line, slow)]
    signal = ema(macd_line, 9)
    if len(signal) < 2:
        return None
    aligned_macd = macd_line[-len(signal):]
    previous_macd, current_macd = aligned_macd[-2], aligned_macd[-1]
    previous_signal, current_signal = signal[-2], signal[-1]
    if previous_macd <= previous_signal and current_macd > current_signal:
        return "BUY"
    if previous_macd >= previous_signal and current_macd < current_signal:
        return "SELL"
    if current_macd > current_signal:
        return "BUY"
    if current_macd < current_signal:
        return "SELL"
    return None


def _in_major_session(timestamp: datetime) -> bool:
    utc = timestamp.astimezone(timezone.utc)
    minute = utc.hour * 60 + utc.minute
    # UTC windows are deliberately configurable approximations; DST changes
    # are not inferred from the broker's local session calendar.
    return 7 * 60 <= minute < 11 * 60 or 12 * 60 <= minute < 16 * 60


class MultiTimeframeConfluenceStrategy:
    """Score higher-timeframe trend, pullback, momentum and structure evidence."""

    name = "MTF_CONFLUENCE_SMC"

    def __init__(self, config: StrategyConfig | None = None):
        self.config = config or StrategyConfig()

    def evaluate(
        self,
        execution_candles: Sequence[Candle],
        context_candles: Sequence[Candle],
        *,
        now: datetime | None = None,
    ) -> TradeSetup | None:
        execution_tf, context_tf = TIMEFRAME_PROFILES[self.config.profile]
        if not execution_candles or not context_candles:
            return None
        symbol = execution_candles[-1].symbol
        market = execution_candles[-1].market
        execution = _validate_series(execution_candles, symbol, execution_tf)
        context = _validate_series(context_candles, symbol, context_tf)
        minimum = max(200, self.config.atr_period + 2, self.config.swing_lookback + 2)
        if len(execution) < minimum or len(context) < 200:
            return None

        closes = [c.close for c in execution]
        context_closes = [c.close for c in context]
        last = execution[-1]
        current_time = now or last.timestamp
        if current_time.tzinfo is None or current_time.utcoffset() is None:
            raise ValueError("Evaluation time must be timezone-aware.")
        if self.config.use_session_filter and market in {"FOREX", "GOLD"} and not _in_major_session(current_time):
            return None

        htf_fast, htf_slow = ema(context_closes, 50)[-1], ema(context_closes, 200)[-1]
        exec_fast, exec_slow = ema(closes, 20)[-1], ema(closes, 50)[-1]
        momentum = _macd_direction(closes)
        strength = rsi(closes, 14)
        volatility = atr(execution, self.config.atr_period)
        if volatility <= 0 or not isfinite(volatility):
            return None

        prior = execution[-self.config.swing_lookback - 1:-1]
        swing_high = max(c.high for c in prior)
        swing_low = min(c.low for c in prior)
        impulse_range = swing_high - swing_low
        if impulse_range <= 0:
            return None

        bullish_sweep = last.low < swing_low and last.close > swing_low
        bearish_sweep = last.high > swing_high and last.close < swing_high
        bullish_bos = last.close > swing_high
        bearish_bos = last.close < swing_low
        internal_high = max(c.high for c in execution[-6:-1])
        internal_low = min(c.low for c in execution[-6:-1])
        bullish_choch = htf_fast <= htf_slow and last.close > internal_high
        bearish_choch = htf_fast >= htf_slow and last.close < internal_low
        recent_opposite_bull = next(
            (c for c in reversed(execution[-7:-1]) if c.close < c.open), None
        )
        recent_opposite_bear = next(
            (c for c in reversed(execution[-7:-1]) if c.close > c.open), None
        )
        bullish_ob_retest = bool(
            recent_opposite_bull and last.low <= recent_opposite_bull.high
            and last.close >= recent_opposite_bull.low and last.close > last.open
        )
        bearish_ob_retest = bool(
            recent_opposite_bear and last.high >= recent_opposite_bear.low
            and last.close <= recent_opposite_bear.high and last.close < last.open
        )
        bullish_fvg = last.low > execution[-3].high
        bearish_fvg = last.high < execution[-3].low
        fib_bull_discount = swing_high - 0.786 * impulse_range <= last.close <= swing_high - 0.5 * impulse_range
        fib_bear_premium = swing_low + 0.5 * impulse_range <= last.close <= swing_low + 0.786 * impulse_range

        buy_score = 0
        sell_score = 0
        buy_reasons: list[str] = []
        sell_reasons: list[str] = []

        if htf_fast > htf_slow:
            buy_score += 2
            buy_reasons.append("Higher-timeframe EMA50 is above EMA200.")
        elif htf_fast < htf_slow:
            sell_score += 2
            sell_reasons.append("Higher-timeframe EMA50 is below EMA200.")

        if exec_fast > exec_slow:
            buy_score += 1
            buy_reasons.append("Execution-timeframe EMA20 is above EMA50.")
        elif exec_fast < exec_slow:
            sell_score += 1
            sell_reasons.append("Execution-timeframe EMA20 is below EMA50.")

        if momentum == "BUY":
            buy_score += 1
            buy_reasons.append("MACD momentum is bullish.")
        elif momentum == "SELL":
            sell_score += 1
            sell_reasons.append("MACD momentum is bearish.")

        if 50 <= strength < 70:
            buy_score += 1
            buy_reasons.append("RSI confirms bullish strength without an overbought reading.")
        elif 30 < strength <= 50:
            sell_score += 1
            sell_reasons.append("RSI confirms bearish strength without an oversold reading.")

        if bullish_bos:
            buy_score += 2
            buy_reasons.append("Price closed above the recent swing high (bullish BOS).")
        if bearish_bos:
            sell_score += 2
            sell_reasons.append("Price closed below the recent swing low (bearish BOS).")
        if bullish_choch:
            buy_score += 2
            buy_reasons.append("Internal structure shifted bullish against the prior higher-timeframe trend (CHoCH).")
        if bearish_choch:
            sell_score += 2
            sell_reasons.append("Internal structure shifted bearish against the prior higher-timeframe trend (CHoCH).")
        if bullish_ob_retest:
            buy_score += 1
            buy_reasons.append("Price retested a recent bearish-candle order-block zone.")
        if bearish_ob_retest:
            sell_score += 1
            sell_reasons.append("Price retested a recent bullish-candle order-block zone.")
        if bullish_sweep:
            buy_score += 2
            buy_reasons.append("Price swept the prior swing low and closed back above it.")
        if bearish_sweep:
            sell_score += 2
            sell_reasons.append("Price swept the prior swing high and closed back below it.")
        if bullish_fvg:
            buy_score += 1
            buy_reasons.append("A bullish three-candle fair-value gap is present.")
        if bearish_fvg:
            sell_score += 1
            sell_reasons.append("A bearish three-candle fair-value gap is present.")
        if fib_bull_discount:
            buy_score += 1
            buy_reasons.append("Price is in the 50–78.6% discount retracement zone.")
        if fib_bear_premium:
            sell_score += 1
            sell_reasons.append("Price is in the 50–78.6% premium retracement zone.")

        if market in {"FOREX", "GOLD"} and _in_major_session(current_time):
            if buy_score:
                buy_score += 1
                buy_reasons.append("London/New York active-session filter passed.")
            if sell_score:
                sell_score += 1
                sell_reasons.append("London/New York active-session filter passed.")

        if buy_score >= self.config.score_threshold and buy_score >= sell_score + 2:
            side, score, reasons = "BUY", buy_score, buy_reasons
            stop = min(c.low for c in execution[-5:]) - self.config.min_stop_atr * volatility
            distance = last.close - stop
            liquidity_target = swing_high
            if distance <= 0 or distance / volatility > self.config.max_stop_atr:
                return None
            if liquidity_target < last.close + self.config.min_reward_risk * distance:
                liquidity_target = last.close + self.config.min_reward_risk * distance
            target_2r = last.close + 2.0 * distance
            target_3r = last.close + 3.0 * distance
        elif sell_score >= self.config.score_threshold and sell_score >= buy_score + 2:
            side, score, reasons = "SELL", sell_score, sell_reasons
            stop = max(c.high for c in execution[-5:]) + self.config.min_stop_atr * volatility
            distance = stop - last.close
            liquidity_target = swing_low
            if distance <= 0 or distance / volatility > self.config.max_stop_atr:
                return None
            if liquidity_target > last.close - self.config.min_reward_risk * distance:
                liquidity_target = last.close - self.config.min_reward_risk * distance
            target_2r = last.close - 2.0 * distance
            target_3r = last.close - 3.0 * distance
        else:
            return None

        return TradeSetup(
            symbol=symbol, market=market, side=side, strategy=self.name,
            entry_price=last.close, stop_loss=stop, target_2r=target_2r,
            target_3r=target_3r, liquidity_target=liquidity_target,
            risk_distance=distance, score=score,
            score_threshold=self.config.score_threshold,
            execution_timeframe=execution_tf, context_timeframe=context_tf,
            reasons=tuple(reasons), created_at=current_time.astimezone(timezone.utc),
        )
