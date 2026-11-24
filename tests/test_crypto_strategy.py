from datetime import datetime, timezone

import pytest

from engine.crypto_arbitrage import ExchangeQuote
from engine.crypto_strategy import BinancePublicCandleFeed, SmaPaperStrategy
from engine.market_data import Candle
from engine.paper_workflow import PaperTradingDesk


def sample_candles():
    now = datetime.now(timezone.utc)
    # A controlled 30-bar baseline followed by a final upward jump crosses the averages.
    closes = [100.0] * 20 + [99.0] * 10 + [110.0]
    return [Candle("BTCUSDT", "CRYPTO", "1m", now, p, p + 1, p - 1, p, 10)
            for p in closes]

def test_binance_candle_feed_parses_klines():
    rows = [[datetime.now(timezone.utc).timestamp() * 1000, "100", "102", "99", "101", "12"] for _ in range(32)]
    calls = []
    feed = BinancePublicCandleFeed(fetch_json=lambda url, timeout: calls.append(url) or rows)
    result = feed.candles("BTC/USDT")
    assert len(result) == 31
    assert result[0].symbol == "BTCUSDT"
    assert result[0].close == 101
    assert "interval=1m" in calls[0]


def test_candle_feed_rejects_short_or_bad_payload():
    feed = BinancePublicCandleFeed(fetch_json=lambda url, timeout: [])
    with pytest.raises(RuntimeError):
        feed.candles("BTCUSDT")


def test_sma_strategy_creates_risk_limited_paper_entry():
    candles = sample_candles()
    quote = ExchangeQuote("Binance", "BTCUSDT", 109.9, 110.0,
                          datetime.now(timezone.utc), 10, 10)
    desk = PaperTradingDesk(starting_equity=20)
    result = SmaPaperStrategy().run_once(candles, quote, desk)
    assert result["event"] == "PAPER_ENTRY"
    assert result["strategy"] == "SMA_CROSS"
    assert result["risk_amount"] <= 0.1 + 1e-9
    assert desk.snapshot()["orders_enabled"] is False


def test_sma_strategy_updates_open_position_using_executable_side():
    candles = sample_candles()
    now = datetime.now(timezone.utc)
    desk = PaperTradingDesk()
    strategy = SmaPaperStrategy()
    quote = ExchangeQuote("Binance", "BTCUSDT", 109.9, 110.0, now, 10, 10)
    opened = strategy.run_once(candles, quote, desk)
    assert opened["event"] == "PAPER_ENTRY"
    moved = ExchangeQuote("Binance", "BTCUSDT", 112.0, 112.1, now, 10, 10)
    result = strategy.run_once(candles, moved, desk)
    assert result["event"] in {"POSITION_HOLD", "PAPER_EXIT"}


def test_strategy_rejects_mismatched_quote_symbol():
    desk = PaperTradingDesk()
    quote = ExchangeQuote("Binance", "ETHUSDT", 100, 101,
                          datetime.now(timezone.utc), 1, 1)
    result = SmaPaperStrategy().run_once(sample_candles(), quote, desk)
    assert result["status"] == "BLOCKED"
    assert result["reason"] == "QUOTE_SYMBOL_MISMATCH"
