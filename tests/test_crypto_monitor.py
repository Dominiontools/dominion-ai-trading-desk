import json
import threading
from datetime import datetime, timezone

import pytest

from engine.crypto_arbitrage import ExchangeQuote
from engine.crypto_monitor import CryptoPaperMonitor


class FakeFeeds:
    def __init__(self, quotes=None, error=None):
        self.quotes = quotes or []
        self.error = error

    def snapshot(self, symbol):
        if self.error:
            raise self.error
        return self.quotes


def make_quotes(now):
    return [
        ExchangeQuote("Binance", "BTC/USDT", 99.9, 100.0, now, 2, 2),
        ExchangeQuote("Bitget", "BTC/USDT", 101.0, 101.1, now, 2, 2),
        ExchangeQuote("HTX", "BTC/USDT", 99.8, 100.2, now, 2, 2),
    ]


FEES = {
    "Binance": (0.0, 1.0),
    "Bitget": (0.0, 1.0),
    "HTX": (0.0, 1.0),
}


def read_records(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_missing_fee_configuration_fails_closed(tmp_path):
    now = datetime.now(timezone.utc)
    log = tmp_path / "logs" / "decisions.jsonl"
    monitor = CryptoPaperMonitor(FakeFeeds(make_quotes(now)), decision_log=log,
                                 clock=lambda: now)
    result = monitor.poll_once("BTC/USDT")
    assert result["status"] == "BLOCKED"
    assert result["reason"] == "FEE_CONFIG_MISSING"
    assert result["orders_enabled"] is False
    assert read_records(log)[0]["missing_fee_exchanges"] == ["Binance", "Bitget", "HTX"]


def test_records_paper_opportunity_without_submitting_orders(tmp_path):
    now = datetime.now(timezone.utc)
    log = tmp_path / "decisions.jsonl"
    monitor = CryptoPaperMonitor(FakeFeeds(make_quotes(now)), decision_log=log,
                                 costs_by_exchange=FEES, min_net_edge_bps=10,
                                 clock=lambda: now)
    result = monitor.poll_once("BTC/USDT")
    assert result["status"] == "PAPER_OPPORTUNITY"
    assert result["orders_enabled"] is False
    assert result["opportunities"][0]["buy_exchange"] == "Binance"
    assert len(read_records(log)) == 1


def test_records_feed_failure(tmp_path):
    now = datetime.now(timezone.utc)
    log = tmp_path / "decisions.jsonl"
    monitor = CryptoPaperMonitor(FakeFeeds(error=TimeoutError("venue timed out")),
                                 decision_log=log, costs_by_exchange=FEES,
                                 clock=lambda: now)
    result = monitor.poll_once("BTC/USDT")
    assert result["status"] == "BLOCKED"
    assert result["reason"] == "MARKET_DATA_FETCH_FAILED"


def test_run_is_bounded_and_has_explicit_stop_event(tmp_path):
    now = datetime.now(timezone.utc)
    log = tmp_path / "decisions.jsonl"
    monitor = CryptoPaperMonitor(FakeFeeds(make_quotes(now)), decision_log=log,
                                 costs_by_exchange=FEES, clock=lambda: now)
    assert monitor.run("BTC/USDT", stop_event=threading.Event(), max_cycles=2) == 2
    assert len(read_records(log)) == 2


def test_interval_cannot_be_faster_than_one_second(tmp_path):
    with pytest.raises(ValueError):
        CryptoPaperMonitor(FakeFeeds(), decision_log=tmp_path / "x",
                           interval_seconds=0.5)
