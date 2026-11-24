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


def test_fetches_three_public_spot_quotes_without_credentials():
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

    with pytest.raises(RuntimeError) as caught:
        PublicCryptoFeeds(fetch_json=partly_broken).snapshot("BTCUSDT")
    message = str(caught.value)
    assert "bitget: TimeoutError" in message
    assert "connection timed out" in message
    assert "htx: OSError" in message
    assert "TLS handshake failed" in message
