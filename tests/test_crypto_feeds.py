from urllib.parse import urlparse

import pytest

from engine.crypto_feeds import PublicCryptoFeeds


STAMP = "1795521600000"


def fake_fetch(url, timeout):
    host = urlparse(url).netloc
    if "binance" in host:
        return {"symbol": "BTCUSDT", "bidPrice": "100", "bidQty": "1.2",
                "askPrice": "101", "askQty": "2.3"}
    if "bitget" in host:
        return {"code": "00000", "data": [{"symbol": "BTCUSDT", "bidPr": "99",
                "askPr": "100", "bidSz": "3", "askSz": "4", "ts": STAMP}]}
    if "huobi" in host:
        return {"status": "ok", "ts": int(STAMP), "tick": {
                "bid": [98, 5], "ask": [99, 6]}}
    if "okx.com" in host:
        return {"code": "0", "data": [{"instId": "BTC-USDT", "bidPx": "97",
                "askPx": "98", "bidSz": "7", "askSz": "8", "ts": STAMP}]}
    raise AssertionError(url)


def test_fetches_four_public_spot_quotes_without_credentials():
    quotes = PublicCryptoFeeds(fetch_json=fake_fetch).snapshot("BTC/USDT")
    assert [q.exchange for q in quotes] == ["Binance", "Bitget", "HTX", "OKX"]
    assert [(q.bid, q.ask) for q in quotes] == [(100, 101), (99, 100), (98, 99), (97, 98)]


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
    assert "OSError" in failures["HTX"]
    assert "TLS handshake failed" in failures["Htx"]
    assert "OSError" in failures["OKX"]


def test_batch_snapshot_fetches_all_requested_pairs_from_four_exchanges():
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
                {"symbol": "BTCUSDT", "bidPr": "102", "askPr": "103", "bidSz": "2", "askSz": "3", "ts": STAMP},
                {"symbol": "ETHUSDT", "bidPr": "202", "askPr": "203", "bidSz": "4", "askSz": "5", "ts": STAMP},
            ]}
        if "huobi" in url:
            return {"status": "ok", "ts": int(STAMP), "data": [
                {"symbol": "btcusdt", "bid": "99", "ask": "100", "bidSize": "1", "askSize": "2"},
                {"symbol": "ethusdt", "bid": "199", "ask": "200", "bidSize": "3", "askSize": "4"},
            ]}
        if "okx.com" in url:
            return {"code": "0", "data": [
                {"instType": "SPOT", "instId": "BTC-USDT", "bidPx": "98", "askPx": "99", "bidSz": "2", "askSz": "3", "ts": STAMP},
                {"instType": "SPOT", "instId": "ETH-USDT", "bidPx": "198", "askPx": "199", "bidSz": "4", "askSz": "5", "ts": STAMP},
            ]}
        raise AssertionError(url)

    quotes, failures = PublicCryptoFeeds(fetch_json=batch_fetch).snapshot_many_with_diagnostics(
        ["BTC/USDT", "ETHUSDT"]
    )
    assert not failures
    assert len(calls) == 4
    assert len(quotes) == 8
    assert {quote.symbol for quote in quotes} == {"BTCUSDT", "ETHUSDT"}
    assert {quote.exchange for quote in quotes} == {"Binance", "Bitget", "HTX", "OKX"}
