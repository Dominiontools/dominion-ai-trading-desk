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



def test_two_independent_venues_can_be_scanned_when_third_is_unavailable(tmp_path):
    now = datetime.now(timezone.utc)
    log = tmp_path / "decisions.jsonl"
    monitor = CryptoPaperMonitor(
        FakeFeeds(make_quotes(now)[:2]), decision_log=log,
        costs_by_exchange=FEES, clock=lambda: now,
    )
    result = monitor.poll_once("BTC/USDT")
    assert result["status"] in {"NO_QUALIFYING_OPPORTUNITY", "PAPER_OPPORTUNITY"}
    assert result["available_exchanges"] == ["Binance", "Bitget"]
    assert result["orders_enabled"] is False


def test_one_exchange_is_not_enough_for_comparison(tmp_path):
    now = datetime.now(timezone.utc)
    log = tmp_path / "decisions.jsonl"
    monitor = CryptoPaperMonitor(
        FakeFeeds(make_quotes(now)[:1]), decision_log=log,
        costs_by_exchange=FEES, clock=lambda: now,
    )
    result = monitor.poll_once("BTC/USDT")
    assert result["status"] == "BLOCKED"
    assert result["reason"] == "INSUFFICIENT_INDEPENDENT_EXCHANGES"
    assert result["orders_enabled"] is False


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


class FakeBatchFeeds:
    def __init__(self, quotes=None, errors=None):
        self.quotes = quotes or []
        self.errors = errors or {}

    def snapshot_many_with_diagnostics(self, symbols):
        self.symbols = tuple(symbols)
        return self.quotes, self.errors


def make_multi_quotes(now):
    return [
        ExchangeQuote("Binance", "BTCUSDT", 99.9, 100.0, now, 2, 2),
        ExchangeQuote("Bitget", "BTCUSDT", 101.0, 101.1, now, 2, 2),
        ExchangeQuote("Binance", "ETHUSDT", 199.9, 200.0, now, 2, 2),
        ExchangeQuote("HTX", "ETHUSDT", 202.0, 202.1, now, 2, 2),
    ]


def test_multi_market_scan_compares_multiple_pairs_in_one_batch(tmp_path):
    now = datetime.now(timezone.utc)
    log = tmp_path / "multi.jsonl"
    monitor = CryptoPaperMonitor(
        FakeBatchFeeds(make_multi_quotes(now)), decision_log=log,
        costs_by_exchange=FEES, max_notional=8.0, clock=lambda: now,
    )
    result = monitor.poll_many_once(["BTCUSDT", "ETHUSDT"])
    assert result["status"] == "PAPER_OPPORTUNITY"
    assert result["symbols_requested"] == 2
    assert result["symbols_with_two_venues"] == 2
    assert result["orders_enabled"] is False
    assert result["opportunities_count"] >= 2
    assert len(result["quotes_preview"]) == 4
    assert {item["symbol"] for item in result["quotes_preview"]} == {"BTCUSDT", "ETHUSDT"}
    assert len(read_records(log)) == 1


def test_multi_market_scan_blocks_without_two_venues_for_any_pair(tmp_path):
    now = datetime.now(timezone.utc)
    log = tmp_path / "multi.jsonl"
    quotes = [ExchangeQuote("Binance", "BTCUSDT", 99.9, 100.0, now, 2, 2)]
    monitor = CryptoPaperMonitor(
        FakeBatchFeeds(quotes), decision_log=log,
        costs_by_exchange=FEES, clock=lambda: now,
    )
    result = monitor.poll_many_once(["BTCUSDT", "ETHUSDT"])
    assert result["status"] == "BLOCKED"
    assert result["reason"] == "INSUFFICIENT_FRESH_INDEPENDENT_MARKET_QUOTES"


def test_multi_market_scan_requires_fee_configuration_for_seen_venues(tmp_path):
    now = datetime.now(timezone.utc)
    log = tmp_path / "multi.jsonl"
    monitor = CryptoPaperMonitor(
        FakeBatchFeeds(make_multi_quotes(now)), decision_log=log,
        costs_by_exchange={"Binance": (0, 1)}, clock=lambda: now,
    )
    result = monitor.poll_many_once(["BTCUSDT", "ETHUSDT"])
    assert result["status"] == "AWAITING_VERIFIED_FEES"
    assert result["reason"].startswith("Market quotes are being compared")
    assert result["missing_fee_exchanges"] == ["Bitget", "HTX"]
    assert result["execution_blocked"] is True
    assert result["opportunities_count"] == 0
    assert result["gross_price_gaps_count"] > 0
    assert result["gross_price_gaps"][0]["fees_verified"] is False
    assert result["gross_price_gaps"][0]["net_edge"] is None


def test_decision_log_rotates_to_keep_android_storage_bounded(tmp_path):
    log = tmp_path / "decisions.jsonl"
    log.write_bytes(b"x" * (5 * 1024 * 1024))
    monitor = CryptoPaperMonitor(
        FakeBatchFeeds(), decision_log=log,
        costs_by_exchange=FEES,
    )
    monitor._write({"status": "ROTATION_TEST"})
    backup = tmp_path / "decisions.jsonl.1"
    assert backup.exists()
    assert log.stat().st_size < 1024
    assert read_records(log)[0]["status"] == "ROTATION_TEST"


def test_multi_market_scan_reports_partial_feed_without_hiding_healthy_venues(tmp_path):
    now = datetime.now(timezone.utc)
    log = tmp_path / "multi-partial.jsonl"
    monitor = CryptoPaperMonitor(
        FakeBatchFeeds(make_multi_quotes(now), errors={"OKX": "TimeoutError: TLS handshake timed out"}),
        decision_log=log,
        costs_by_exchange={"Binance": (0, 1)},
        clock=lambda: now,
    )
    result = monitor.poll_many_once(["BTCUSDT", "ETHUSDT"])
    assert result["status"] == "PARTIAL_FEED_AWAITING_VERIFIED_FEES"
    assert result["available_exchanges"] == ["Binance", "Bitget", "HTX"]
    assert result["venue_errors"]["OKX"].startswith("TimeoutError")
    assert result["symbols_with_two_venues"] == 2
    assert result["execution_blocked"] is True
    assert result["orders_enabled"] is False


def test_multi_market_scan_blocks_when_all_same_symbol_quotes_are_stale(tmp_path):
    from datetime import timedelta

    now = datetime.now(timezone.utc)
    stale_quotes = [
        ExchangeQuote("Binance", "BTCUSDT", 99.9, 100.0, now - timedelta(seconds=5), 2, 2),
        ExchangeQuote("Bitget", "BTCUSDT", 101.0, 101.1, now - timedelta(seconds=6), 2, 2),
    ]
    monitor = CryptoPaperMonitor(
        FakeBatchFeeds(stale_quotes), decision_log=tmp_path / "stale.jsonl",
        costs_by_exchange=FEES, clock=lambda: now,
    )
    result = monitor.poll_many_once(["BTCUSDT"])
    assert result["status"] == "BLOCKED"
    assert result["reason"] == "INSUFFICIENT_FRESH_INDEPENDENT_MARKET_QUOTES"
    assert result["symbols_with_any_quotes"] == 1
    assert result["symbols_with_quotes"] == 0
    assert result["symbols_with_two_venues"] == 0
    assert result["fresh_quote_count"] == 0
    assert result["orders_enabled"] is False


def test_multi_market_scan_uses_fresh_coverage_when_stale_and_fresh_quotes_mix(tmp_path):
    from datetime import timedelta

    now = datetime.now(timezone.utc)
    quotes = [
        ExchangeQuote("Binance", "BTCUSDT", 99.9, 100.0, now, 2, 2),
        ExchangeQuote("Bitget", "BTCUSDT", 101.0, 101.1, now, 2, 2),
        ExchangeQuote("HTX", "BTCUSDT", 102.0, 102.1, now - timedelta(seconds=8), 2, 2),
    ]
    monitor = CryptoPaperMonitor(
        FakeBatchFeeds(quotes), decision_log=tmp_path / "mixed.jsonl",
        costs_by_exchange=FEES, clock=lambda: now,
    )
    result = monitor.poll_many_once(["BTCUSDT"])
    assert result["symbols_with_any_quotes"] == 1
    assert result["symbols_with_quotes"] == 1
    assert result["symbols_with_two_venues"] == 1
    assert result["fresh_quote_count"] == 2
    assert result["quotes_by_exchange"] == {"Binance": 1, "Bitget": 1}
    assert result["orders_enabled"] is False