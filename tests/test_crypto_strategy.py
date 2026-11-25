from datetime import datetime, timedelta, timezone

import pytest

from engine.crypto_arbitrage import ExchangeQuote
from engine.crypto_strategy import BinancePublicCandleFeed, ConfluencePaperStrategy, SmaPaperStrategy
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


def mtf_sample_candles(symbol, timeframe, count, start, step, spread, interval, end_age):
    now = datetime.now(timezone.utc)
    first = now - timedelta(seconds=end_age) - timedelta(seconds=interval * (count - 1))
    result = []
    for i in range(count):
        close = start + i * step
        result.append(Candle(
            symbol, "CRYPTO", timeframe, first + timedelta(seconds=interval * i),
            close - step / 3, close + spread, close - spread, close, 100 + i,
        ))
    previous = result[-2]
    result[-1] = Candle(
        symbol, "CRYPTO", timeframe, result[-1].timestamp,
        previous.close + 0.0002, previous.close + 0.0012,
        previous.close - 0.0003, previous.close + 0.0007, 500,
    )
    return result


def test_confluence_strategy_opens_risk_limited_paper_entry():
    now = datetime.now(timezone.utc)
    execution = mtf_sample_candles(
        "BTCUSDT", "15m", 240, 1.1, 0.0001, 0.0005, 15 * 60, 15 * 60
    )
    context = mtf_sample_candles(
        "BTCUSDT", "4h", 240, 1.0, 0.0005, 0.001, 4 * 60 * 60, 4 * 60 * 60
    )
    quote = ExchangeQuote("Binance", "BTCUSDT", 1.1242, 1.1243, now, 10, 10)
    desk = PaperTradingDesk(starting_equity=20)
    result = ConfluencePaperStrategy().run_once(execution, context, quote, desk, now=now)
    assert result["event"] == "PAPER_ENTRY"
    assert result["strategy"] == "MTF_CONFLUENCE_SMC"
    assert result["risk_amount"] <= 0.1 + 1e-9
    assert result["position"]["quantity"] * result["position"]["entry_price"] <= 8.0 + 1e-6
    assert result["target_3r"] > result["position"]["entry_price"]
    assert desk.snapshot()["orders_enabled"] is False


def test_confluence_strategy_blocks_stale_quote_before_position_management():
    now = datetime.now(timezone.utc)
    execution = mtf_sample_candles(
        "BTCUSDT", "15m", 240, 1.1, 0.0001, 0.0005, 15 * 60, 15 * 60
    )
    context = mtf_sample_candles(
        "BTCUSDT", "4h", 240, 1.0, 0.0005, 0.001, 4 * 60 * 60, 4 * 60 * 60
    )
    quote = ExchangeQuote("Binance", "BTCUSDT", 1.1242, 1.1243,
                          now - timedelta(seconds=5), 10, 10)
    result = ConfluencePaperStrategy().run_once(
        execution, context, quote, PaperTradingDesk(), now=now
    )
    assert result["status"] == "BLOCKED"
    assert result["reason"] == "STALE_QUOTE_DATA"



def test_confluence_strategy_routes_valid_setup_through_testnet_router():
    from types import SimpleNamespace

    now = datetime.now(timezone.utc)
    execution = mtf_sample_candles(
        "BTCUSDT", "15m", 240, 1.1, 0.0001, 0.0005, 15 * 60, 15 * 60
    )
    context = mtf_sample_candles(
        "BTCUSDT", "4h", 240, 1.0, 0.0005, 0.001, 4 * 60 * 60, 4 * 60 * 60
    )
    quote = ExchangeQuote("Binance", "BTCUSDT", 1.1242, 1.1243, now, 10, 10)
    setup = SimpleNamespace(
        market="CRYPTO", side="BUY", symbol="BTCUSDT",
        score=8, score_threshold=6, strategy="MTF_TEST",
        stop_loss=1.12, target_2r=1.13,
        execution_timeframe="15m", context_timeframe="4h",
    )

    class FakeStrategy:
        def evaluate(self, *args, **kwargs):
            return setup

    class FakeProvider:
        def snapshot(self, *, now=None):
            return SimpleNamespace(context=object(), account_snapshot_verified=True,
                                   daily_loss_verified=True)

    class FakeRouter:
        def __init__(self):
            self.calls = []

        def submit_verified_setup(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            return {
                "protected": True, "halted": False,
                "operator_action_required": False, "orders_enabled": True,
                "status": "PROTECTED",
                "plan": {"quantity": "10", "max_planned_loss_quote": "0.5"},
            }

    strategy = ConfluencePaperStrategy()
    strategy.strategy = FakeStrategy()
    router = FakeRouter()
    result = strategy.run_testnet_once(
        execution, context, quote, router=router,
        risk_context_provider=FakeProvider(), now=now,
    )
    assert result["event"] == "TESTNET_ORDER"
    assert result["mode"] == "BINANCE_SPOT_TESTNET"
    assert result["protected"] is True
    assert result["score"] == 8
    assert len(router.calls) == 1


def test_testnet_strategy_blocks_without_fresh_quote_or_validated_context():
    now = datetime.now(timezone.utc)
    execution = mtf_sample_candles(
        "BTCUSDT", "15m", 240, 1.1, 0.0001, 0.0005, 15 * 60, 15 * 60
    )
    context = mtf_sample_candles(
        "BTCUSDT", "4h", 240, 1.0, 0.0005, 0.001, 4 * 60 * 60, 4 * 60 * 60
    )
    quote = ExchangeQuote("Binance", "BTCUSDT", 1.1242, 1.1243,
                          now - timedelta(seconds=5), 10, 10)

    class NeverRouter:
        def submit_verified_setup(self, *args, **kwargs):
            pytest.fail("Stale quote must be rejected before routing.")

    class NeverProvider:
        def snapshot(self, **kwargs):
            pytest.fail("Stale quote must be rejected before account lookup.")

    result = ConfluencePaperStrategy().run_testnet_once(
        execution, context, quote, router=NeverRouter(),
        risk_context_provider=NeverProvider(), now=now,
    )
    assert result["event"] == "TESTNET_BLOCKED"
    assert result["reason"] == "STALE_QUOTE_DATA"


def test_testnet_strategy_reports_protection_failure_as_blocked():
    from types import SimpleNamespace

    now = datetime.now(timezone.utc)
    execution = mtf_sample_candles(
        "BTCUSDT", "15m", 240, 1.1, 0.0001, 0.0005, 15 * 60, 15 * 60
    )
    context = mtf_sample_candles(
        "BTCUSDT", "4h", 240, 1.0, 0.0005, 0.001, 4 * 60 * 60, 4 * 60 * 60
    )
    quote = ExchangeQuote("Binance", "BTCUSDT", 1.1242, 1.1243, now, 10, 10)
    setup = SimpleNamespace(
        market="CRYPTO", side="BUY", symbol="BTCUSDT",
        score=8, score_threshold=6, strategy="MTF_TEST",
        stop_loss=1.12, target_2r=1.13,
        execution_timeframe="15m", context_timeframe="4h",
    )

    class FakeStrategy:
        def evaluate(self, *args, **kwargs):
            return setup

    class FakeProvider:
        def snapshot(self, *, now=None):
            return object()

    class FakeRouter:
        def submit_verified_setup(self, *args, **kwargs):
            return {"protected": False, "halted": True,
                    "operator_action_required": True,
                    "orders_enabled": False, "status": "PROTECTION_UNCONFIRMED"}

    strategy = ConfluencePaperStrategy()
    strategy.strategy = FakeStrategy()
    result = strategy.run_testnet_once(
        execution, context, quote, router=FakeRouter(),
        risk_context_provider=FakeProvider(), now=now,
    )
    assert result["event"] == "TESTNET_BLOCKED"
    assert result["halted"] is True
    assert result["operator_action_required"] is True
