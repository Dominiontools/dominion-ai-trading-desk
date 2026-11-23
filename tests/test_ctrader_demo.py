from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import pytest

from engine.ctrader_demo import CTraderDemoConfig, historical_window, is_confirmed_demo_account, market_for_symbol, spot_event_to_quote, trendbar_to_candle


def test_market_mapping_identifies_gold_and_forex():
    assert market_for_symbol("XAUUSD") == "GOLD"
    assert market_for_symbol("EUR/USD") == "FOREX"


def test_trendbar_prices_are_scaled_and_reconstructed():
    bar = SimpleNamespace(low=200000000, deltaOpen=100000, deltaClose=250000, deltaHigh=300000,
                          utcTimestampInMinutes=30000000, volume=123)
    candle = trendbar_to_candle(bar, "XAUUSD", "M5")
    assert candle.low == 2000.0
    assert candle.open == 2001.0
    assert candle.close == 2002.5
    assert candle.high == 2003.0
    assert candle.volume == 123.0
    assert candle.timestamp.tzinfo == timezone.utc


def test_connector_config_requires_all_secrets_and_account(monkeypatch):
    for name in ("CTRADER_CLIENT_ID", "CTRADER_CLIENT_SECRET", "CTRADER_ACCESS_TOKEN", "CTRADER_ACCOUNT_ID"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(RuntimeError, match="Missing required"):
        CTraderDemoConfig.from_env()


def test_connector_config_rejects_non_numeric_account(monkeypatch):
    monkeypatch.setenv("CTRADER_CLIENT_ID", "demo-client")
    monkeypatch.setenv("CTRADER_CLIENT_SECRET", "secret")
    monkeypatch.setenv("CTRADER_ACCESS_TOKEN", "token")
    monkeypatch.setenv("CTRADER_ACCOUNT_ID", "not-a-number")
    with pytest.raises(RuntimeError, match="must be an integer"):
        CTraderDemoConfig.from_env()


def test_account_must_explicitly_be_marked_demo():
    demo = SimpleNamespace(isLive=False, HasField=lambda name: name == "isLive")
    live = SimpleNamespace(isLive=True, HasField=lambda name: name == "isLive")
    unknown = SimpleNamespace(isLive=False, HasField=lambda name: False)
    assert is_confirmed_demo_account(demo)
    assert not is_confirmed_demo_account(live)
    assert not is_confirmed_demo_account(unknown)



def test_historical_window_is_bounded_to_requested_bar_count():
    end = 1_800_000_000_000
    start, returned_end = historical_window("M5", 200, end)
    assert returned_end == end
    assert end - start == 201 * 300_000


def test_historical_window_rejects_invalid_timeframe_and_limit():
    with pytest.raises(ValueError, match="Unsupported timeframe"):
        historical_window("Q1", 100, 1_800_000_000_000)
    with pytest.raises(ValueError, match="between 1 and 5000"):
        historical_window("M1", 0, 1_800_000_000_000)



def test_spot_event_converts_timestamped_bid_and_ask():
    event = SimpleNamespace(
        bid=115482,
        ask=115490,
        timestamp=1_800_000_000_000,
        HasField=lambda name: name in {"bid", "ask", "timestamp"},
    )
    quote = spot_event_to_quote(event, "EURUSD")
    assert quote is not None
    assert quote.symbol == "EURUSD"
    assert quote.bid == 1.15482
    assert quote.ask == 1.1549
    assert quote.timestamp.tzinfo == timezone.utc


def test_spot_event_rejects_missing_timestamp_or_crossed_market():
    missing_time = SimpleNamespace(
        bid=100000, ask=100001, timestamp=0,
        HasField=lambda name: name in {"bid", "ask"},
    )
    partial = SimpleNamespace(
        bid=100000, ask=0, timestamp=1_800_000_000_000,
        HasField=lambda name: name in {"bid", "timestamp"},
    )
    crossed = SimpleNamespace(
        bid=100002, ask=100001, timestamp=1_800_000_000_000,
        HasField=lambda name: name in {"bid", "ask", "timestamp"},
    )
    assert spot_event_to_quote(missing_time, "EURUSD") is None
    assert spot_event_to_quote(partial, "EURUSD") is None
    assert spot_event_to_quote(crossed, "EURUSD") is None



def test_incremental_spot_updates_preserve_each_side_timestamp():
    first_time = 1_800_000_000_000
    first_event = SimpleNamespace(
        bid=115482, ask=115490, timestamp=first_time,
        HasField=lambda name: name in {"bid", "ask", "timestamp"},
    )
    initial = spot_event_to_quote(first_event, "EURUSD")
    assert initial is not None

    bid_update = SimpleNamespace(
        bid=115483, ask=0, timestamp=first_time + 1000,
        HasField=lambda name: name in {"bid", "timestamp"},
    )
    updated = spot_event_to_quote(
        bid_update,
        "EURUSD",
        previous_bid=initial.bid,
        previous_ask=initial.ask,
        previous_bid_timestamp=initial.bid_timestamp,
        previous_ask_timestamp=initial.ask_timestamp,
    )
    assert updated is not None
    assert updated.bid == 1.15483
    assert updated.ask == 1.1549
    assert updated.bid_timestamp > updated.ask_timestamp
