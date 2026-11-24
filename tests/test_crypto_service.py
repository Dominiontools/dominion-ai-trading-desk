import json
import time
from urllib.request import urlopen

import pytest
import engine.crypto_service as service


class FakeFeeds:
    def __init__(self, timeout=5.0):
        self.timeout = timeout


class FakeMonitor:
    def __init__(self, feeds, **kwargs):
        self.calls = 0

    def poll_once(self, symbol):
        self.calls += 1
        return {"symbol": symbol, "status": "BLOCKED", "reason": "FEE_CONFIG_MISSING"}


class FakeCandleFeed:
    def __init__(self, timeout=8.0):
        self.timeout = timeout

    def candles(self, symbol, timeframe="1m", limit=80):
        raise RuntimeError("offline test fixture")


def test_fee_config_is_empty_without_user_verified_values(monkeypatch):
    for name in ("DOMINION_FEE_BINANCE_TAKER_BPS", "DOMINION_FEE_BITGET_TAKER_BPS",
                 "DOMINION_FEE_HTX_TAKER_BPS"):
        monkeypatch.delenv(name, raising=False)
    assert service._fee_config() == {}


def test_fee_config_reads_all_three_explicit_values(monkeypatch):
    monkeypatch.setenv("DOMINION_FEE_BINANCE_TAKER_BPS", "10")
    monkeypatch.setenv("DOMINION_FEE_BITGET_TAKER_BPS", "12")
    monkeypatch.setenv("DOMINION_FEE_HTX_TAKER_BPS", "8")
    assert service._fee_config() == {"Binance": (10.0, 10.0),
                                     "Bitget": (12.0, 12.0), "HTX": (8.0, 8.0)}


def test_fee_config_rejects_negative_fee(monkeypatch):
    monkeypatch.setenv("DOMINION_FEE_BINANCE_TAKER_BPS", "-1")
    with pytest.raises(RuntimeError):
        service._fee_config()


def test_positive_float_rejects_zero(monkeypatch):
    monkeypatch.setenv("DOMINION_TEST_INTERVAL", "0")
    with pytest.raises(RuntimeError):
        service._positive_float("DOMINION_TEST_INTERVAL", 5.0)


def test_embedded_service_starts_read_only_api_and_stops(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "PublicCryptoFeeds", FakeFeeds)
    monkeypatch.setattr(service, "CryptoPaperMonitor", FakeMonitor)
    monkeypatch.setattr(service, "BinancePublicCandleFeed", FakeCandleFeed)
    monkeypatch.delenv("DOMINION_FEE_BINANCE_TAKER_BPS", raising=False)
    monkeypatch.delenv("DOMINION_FEE_BITGET_TAKER_BPS", raising=False)
    monkeypatch.delenv("DOMINION_FEE_HTX_TAKER_BPS", raising=False)

    started = service.start_embedded(str(tmp_path), port=0)
    assert started["started"] is True
    assert started["orders_enabled"] is False
    assert started["port"] > 0

    try:
        deadline = time.time() + 2
        status = None
        while time.time() < deadline:
            try:
                with urlopen(f"http://127.0.0.1:{started['port']}/api/crypto/status", timeout=1) as response:
                    status = json.loads(response.read())
                break
            except OSError:
                time.sleep(0.05)
        assert status is not None
        assert status["mode"] == "PAPER_ONLY"
        assert status["orders_enabled"] is False
        assert status["engine"] == "running"
        assert status["paper_trading"]["mode"] == "PAPER_ONLY"
        assert status["paper_trading"]["starting_equity"] == 20.0
        assert status["paper_trading"]["open_position"] is None
        assert status["paper_trading"]["orders_enabled"] is False
        assert status["agents"]["SNIPER"]["status"] == "READY_FOR_VALIDATED_SIGNALS"
    finally:
        stopped = service.stop_embedded()

    assert stopped["stopped"] is True
    assert service.stop_embedded()["already_stopped"] is True
