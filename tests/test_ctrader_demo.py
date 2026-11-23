from datetime import datetime, timezone
from types import SimpleNamespace
import pytest

from engine.ctrader_demo import CTraderDemoConfig, is_confirmed_demo_account, market_for_symbol, trendbar_to_candle


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
