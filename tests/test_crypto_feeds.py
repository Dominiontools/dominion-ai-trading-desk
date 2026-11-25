from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qs

import pytest

from engine.crypto_feeds import PublicCryptoFeeds


def fake_fetch(url, timeout):
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    if "binance" in parsed.netloc:
        return {"symbol": "BTCUSDT", "bidPrice": "100", "bidQty": "1.2",
                "askPrice": "101", "askQty": "2.3"}
    if "bitget" in parsed.netloc:
        return {"code": "00000", "data": [{"symbol": "BTCUSDT", "bidPr": "99",
                "askPr": "100", "bidSz": "3", "askSz": "4", "ts": "1795521600000"}]}
    if "huobi" in parsed.netloc:
        return {"status": "ok", "ts": 1795521600000, "tick": {
                "bid": [98, 5], "ask": [99, 6]}}
    raise AssertionError(url)


def test_fetches_four_public_spot_quotes_without_credentials():
    feeds = PublicCryptoFeeds(fetch_json=fake_fetch)
    quotes = feeds.snapshot("BTC/USDT")
    assert [q.exchange for q in quotes] == ["Binance", "Bitget", "HTX"]
    assert [(q.bid, q.ask) for q in quotes] == [(100, 101), (99, 100), (98, 99)]
    assert all(q.symbol == "BTC/USDT" for q in quotes)


def test_bitget_rejects_api_error():
    def bad(url, timeout):
        return {"code": "40000", "data": []}
    with pytest.raises(RuntimeError, match="Bitget"):
        PublicCryptoFeeds(fetch_json=bad).bitget("BTCUSDT")


def test_htx_rejects_unexpected_payload():
    def bad(url, timeout):
        return {"status": "error"}
    with pytest.raises(RuntimeError, match="HTX"):
        PublicCryptoFeeds(fetch_json=bad).htx("BTCUSDT")


def test_rejects_invalid_symbol():
    with pytest.raises(ValueError):
        PublicCryptoFeeds(fetch_json=fake_fetch).binance("BTC/USDT!")


def test_snapshot_reports_each_failed_venue_without_returning_partial_quotes():
    def partly_broken(url, timeout):
        if "binance" in url:
            return {"symbol": "BTCUSDT", "bidPrice": "100", "bidQty": "1",
                    "askPrice": "101", "askQty": "1"}
        if "bitget" in url:
            raise TimeoutError("connection timed out")
        raise OSError("TLS handshake failed")

    quotes, failures = PublicCryptoFeeds(fetch_json=partly_broken).snapshot_with_diagnostics("BTCUSDT")
    assert [quote.exchange for quote in quotes] == ["Binance"]
    assert "TimeoutError" in failures["Bitget"]
    assert "connection timed out" in failures["Bitget"]
    assert "OSError" in failures["Htx"]
    assert "TLS handshake failed" in failures["Htx"]


def test_batch_snapshot_fetches_all_requested_pairs_with_one_request_per_exchange():
    calls = []

    def batch_fetch(url, timeout):
        calls.append(url)
        if "binance" in url:
            return [
                {"symbol": "BTCUSDT", "bidPrice": "100", "bidQty": "1", "askPrice": "101", "askQty": "2"},
                {"symbol": "ETHUSDT", "bidPrice": "200", "bidQty": "3", "askPrice": "201", "askQty": "4"},
            ]
        if "bitget" in url:
            return {"code": "00000", "data": [
                {"symbol": "BTCUSDT", "bidPr": "102", "askPr": "103", "bidSz": "2", "askSz": "3", "ts": "1795521600000"},
                {"symbol": "ETHUSDT", "bidPr": "202", "askPr": "203", "bidSz": "4", "askSz": "5", "ts": "1795521600000"},
            ]}
        if "huobi" in url:
            return {"status": "ok", "ts": 1795521600000, "data": [
                {"symbol": "btcusdt", "bid": "99", "ask": "100", "bidSize": "1", "askSize": "2"},
                {"symbol": "ethusdt", "bid": "199", "ask": "200", "bidSize": "3", "askSize": "4"},
            ]}
        raise AssertionError(url)

    quotes, failures = PublicCryptoFeeds(fetch_json=batch_fetch).snapshot_many_with_diagnostics(
        ["BTC/USDT", "ETHUSDT"]
    )
    assert not failures
    assert len(calls) == 3
    assert len(quotes) == 6
    assert {quote.symbol for quote in quotes} == {"BTCUSDT", "ETHUSDT"}
    assert {quote.exchange for quote in quotes} == {"Binance", "Bitget", "HTX", "OKX"}


def test_okx_rejects_api_error():
    def bad(url, timeout):
        return {"code": "50000", "data": []}
    with pytest.raises(RuntimeError, match="OKX"):
        PublicCryptoFeeds(fetch_json=bad).okx("BTCUSDT")


def test_okx_rejects_missing_instrument():
    def missing(url, timeout):
        return {"code": "0", "data": []}
    with pytest.raises(RuntimeError, match="did not return"):
        PublicCryptoFeeds(fetch_json=missing).okx("BTCUSDT")
