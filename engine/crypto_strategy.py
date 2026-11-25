"""Public-candle multi-timeframe confluence strategy feeding the paper-only execution desk.

Uses Binance public market data only. No credentials or order-placement code.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .crypto_arbitrage import ExchangeQuote, quote_age_seconds
from .market_data import Candle
from .paper_workflow import PaperSignal, PaperTradingDesk
from .strategies import MovingAverageCross


def _fetch_json(url: str, timeout: float) -> object:
    request = Request(url, headers={"User-Agent": "Dominion-AI-Trading-Desk/0.1"})
    with urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"Binance candle HTTP status: {response.status}")
        return json.loads(response.read().decode("utf-8"))


class BinancePublicCandleFeed:
    """Read-only Binance Spot klines adapter."""

    def __init__(self, fetch_json: Callable[[str, float], object] = _fetch_json,
                 timeout: float = 8.0):
        if timeout <= 0:
            raise ValueError("Timeout must be positive.")
        self.fetch_json = fetch_json
        self.timeout = timeout

    def candles(self, symbol: str, timeframe: str = "1m", limit: int = 80) -> list[Candle]:
        pair = symbol.replace("/", "").replace("-", "").upper()
        if not pair.isalnum() or not pair:
            raise ValueError("Invalid trading symbol.")
        if timeframe not in {"1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d"}:
            raise ValueError("Unsupported candle timeframe.")
        if not 31 <= limit <= 1000:
            raise ValueError("Candle limit must be between 31 and 1000.")
        query = urlencode({"symbol": pair, "interval": timeframe, "limit": limit})
        payload = self.fetch_json(
            f"https://data-api.binance.vision/api/v3/klines?{query}", self.timeout
        )
        if not isinstance(payload, list):
            raise RuntimeError("Unexpected Binance candle response.")
        result = []
        for row in payload:
            if not isinstance(row, list) or len(row) < 6:
                continue
            result.append(Candle(
                symbol=pair, market="CRYPTO", timeframe=timeframe,
                timestamp=datetime.fromtimestamp(int(row[0]) / 1000, timezone.utc),
                open=float(row[1]), high=float(row[2]), low=float(row[3]),
                close=float(row[4]), volume=float(row[5]),
            ))
        # Binance includes the currently forming candle. Drop it so the
        # crossover is evaluated only on completed bars.
        completed = result[:-1]
        if len(completed) < 31:
            raise RuntimeError("Binance returned fewer than 31 completed usable candles.")
        return completed


class SmaPaperStrategy:
    """10/30 SMA crossover with conservative fixed-distance paper protection."""

    def __init__(self, fast_period: int = 10, slow_period: int = 30,
                 stop_distance_pct: float = 0.01, reward_multiple: float = 2.0,
                 max_notional: float = 20.0, estimated_slippage_bps: float = 5.0):
        if not 0 < stop_distance_pct <= 0.05 or reward_multiple < 1:
            raise ValueError("Invalid stop distance or reward multiple.")
        if max_notional <= 0 or estimated_slippage_bps < 0:
            raise ValueError("Invalid notional or slippage configuration.")
        self.strategy = MovingAverageCross(fast_period, slow_period)
        self.stop_distance_pct = stop_distance_pct
        self.reward_multiple = reward_multiple
        self.max_notional = max_notional
        self.estimated_slippage_bps = estimated_slippage_bps

    def run_once(self, candles: list[Candle], quote: ExchangeQuote,
                 desk: PaperTradingDesk) -> dict:
        if not candles:
            return {"status": "BLOCKED", "reason": "NO_CANDLES", "mode": "PAPER_ONLY"}
        symbol = candles[-1].symbol.upper()
        stamp = candles[-1].timestamp
        if stamp.tzinfo is None:
            return {"status": "BLOCKED", "reason": "NAIVE_CANDLE_TIMESTAMP", "mode": "PAPER_ONLY"}
        candle_age = (datetime.now(timezone.utc) - stamp.astimezone(timezone.utc)).total_seconds()
        if candle_age < 0 or candle_age > 120:
            return {"status": "BLOCKED", "reason": "STALE_CANDLE_DATA", "mode": "PAPER_ONLY"}
        if quote.symbol.replace("/", "").replace("-", "").upper() != symbol:
            return {"status": "BLOCKED", "reason": "QUOTE_SYMBOL_MISMATCH", "mode": "PAPER_ONLY"}
        if desk.position is not None:
            if desk.position.symbol != symbol:
                return {"status": "WAITING", "reason": "ONE_POSITION_LIMIT", "mode": "PAPER_ONLY"}
            exit_price = quote.bid if desk.position.side == "BUY" else quote.ask
            return desk.update_price(symbol, exit_price)

        age = quote_age_seconds(quote)
        signal = self.strategy.evaluate(candles)
        if signal is None:
            return {"status": "NO_SIGNAL", "symbol": symbol, "mode": "PAPER_ONLY"}
        entry = quote.ask if signal.side == "BUY" else quote.bid
        distance = entry * self.stop_distance_pct
        risk_budget = desk.equity * desk.limits.max_risk_per_trade_pct
        quantity = min(risk_budget / distance, self.max_notional / entry)
        stop = entry - distance if signal.side == "BUY" else entry + distance
        target = entry + distance * self.reward_multiple if signal.side == "BUY" else entry - distance * self.reward_multiple
        mid = (quote.bid + quote.ask) / 2
        spread_bps = (quote.ask - quote.bid) / mid * 10_000
        paper_signal = PaperSignal(
            symbol=symbol, market=signal.market, side=signal.side,
            entry_price=entry, stop_loss=stop, take_profit=target,
            quantity=quantity, spread_bps=spread_bps,
            estimated_slippage_bps=self.estimated_slippage_bps,
            quote_age_seconds=age, trailing_distance=distance,
        )
        result = desk.open_from_signal(paper_signal)
        result["strategy"] = signal.strategy
        result["signal_reason"] = signal.reason
        return result


class ConfluencePaperStrategy:
    """Multi-timeframe EMA/MACD/RSI/SMC paper strategy with shared risk sizing."""

    _TIMEFRAME_SECONDS = {
        "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400,
    }

    def __init__(self, profile: str = "intraday", score_threshold: int = 6,
                 max_notional_fraction: float = 0.40,
                 estimated_slippage_bps: float = 5.0):
        from .confluence_strategy import MultiTimeframeConfluenceStrategy, StrategyConfig
        if not 0 < max_notional_fraction <= 0.40:
            raise ValueError("Maximum crypto notional allocation must be between 0 and 40% of equity.")
        if estimated_slippage_bps < 0:
            raise ValueError("Estimated slippage cannot be negative.")
        self.strategy = MultiTimeframeConfluenceStrategy(
            StrategyConfig(profile=profile, score_threshold=score_threshold)
        )
        self.profile = profile
        self.max_notional_fraction = max_notional_fraction
        self.estimated_slippage_bps = estimated_slippage_bps

    def run_once(self, execution_candles: list[Candle], context_candles: list[Candle],
                 quote: ExchangeQuote, desk: PaperTradingDesk,
                 *, now: datetime | None = None) -> dict:
        from .confluence_strategy import TIMEFRAME_PROFILES

        if not execution_candles or not context_candles:
            return {"status": "BLOCKED", "reason": "NO_CANDLES", "mode": "PAPER_ONLY"}
        symbol = execution_candles[-1].symbol.upper()
        execution_tf, context_tf = TIMEFRAME_PROFILES[self.profile]
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None or current.utcoffset() is None:
            return {"status": "BLOCKED", "reason": "NAIVE_EVALUATION_TIME", "mode": "PAPER_ONLY"}
        if any(c.symbol.upper() != symbol for c in context_candles):
            return {"status": "BLOCKED", "reason": "CONTEXT_SYMBOL_MISMATCH", "mode": "PAPER_ONLY"}
        if quote.symbol.replace("/", "").replace("-", "").upper() != symbol:
            return {"status": "BLOCKED", "reason": "QUOTE_SYMBOL_MISMATCH", "mode": "PAPER_ONLY"}
        try:
            age = quote_age_seconds(quote, now=current)
        except ValueError:
            return {"status": "BLOCKED", "reason": "INVALID_QUOTE_TIMESTAMP", "mode": "PAPER_ONLY"}
        if age > 2.0:
            return {"status": "BLOCKED", "reason": "STALE_QUOTE_DATA", "mode": "PAPER_ONLY"}
        if desk.position is not None:
            if desk.position.symbol != symbol:
                return {"status": "WAITING", "reason": "ONE_POSITION_LIMIT", "mode": "PAPER_ONLY"}
            exit_price = quote.bid if desk.position.side == "BUY" else quote.ask
            return desk.update_price(symbol, exit_price)

        for series, timeframe, label in (
            (execution_candles, execution_tf, "EXECUTION"),
            (context_candles, context_tf, "CONTEXT"),
        ):
            stamp = series[-1].timestamp
            if stamp.tzinfo is None or stamp.utcoffset() is None:
                return {"status": "BLOCKED", "reason": f"NAIVE_{label}_CANDLE_TIMESTAMP", "mode": "PAPER_ONLY"}
            candle_age = (current - stamp.astimezone(timezone.utc)).total_seconds()
            allowed_age = self._TIMEFRAME_SECONDS[timeframe] * 2 + 30
            if candle_age < 0 or candle_age > allowed_age:
                return {"status": "BLOCKED", "reason": f"STALE_{label}_CANDLE_DATA", "mode": "PAPER_ONLY"}

        setup = self.strategy.evaluate(execution_candles, context_candles, now=current)
        if setup is None:
            return {"status": "NO_SIGNAL", "symbol": symbol, "mode": "PAPER_ONLY"}

        entry = quote.ask if setup.side == "BUY" else quote.bid
        distance = setup.risk_distance
        risk_budget = desk.equity * desk.limits.max_risk_per_trade_pct
        notional_cap = desk.equity * self.max_notional_fraction
        quantity = min(risk_budget / distance, notional_cap / entry)
        if quantity <= 0:
            return {"status": "BLOCKED", "reason": "INVALID_POSITION_SIZE", "mode": "PAPER_ONLY"}
        stop = entry - distance if setup.side == "BUY" else entry + distance
        target = entry + 2.0 * distance if setup.side == "BUY" else entry - 2.0 * distance
        mid = (quote.bid + quote.ask) / 2
        spread_bps = (quote.ask - quote.bid) / mid * 10_000
        paper_signal = PaperSignal(
            symbol=symbol, market=setup.market, side=setup.side,
            entry_price=entry, stop_loss=stop, take_profit=target,
            quantity=quantity, spread_bps=spread_bps,
            estimated_slippage_bps=self.estimated_slippage_bps,
            quote_age_seconds=age, trailing_distance=distance,
        )
        result = desk.open_from_signal(paper_signal)
        result.update({
            "strategy": setup.strategy,
            "score": setup.score,
            "score_threshold": setup.score_threshold,
            "signal_reason": " ".join(setup.reasons),
            "target_3r": entry + 3.0 * distance if setup.side == "BUY" else entry - 3.0 * distance,
            "liquidity_reference": setup.liquidity_target,
            "execution_timeframe": setup.execution_timeframe,
            "context_timeframe": setup.context_timeframe,
            "max_notional_fraction": self.max_notional_fraction,
        })
        return result
