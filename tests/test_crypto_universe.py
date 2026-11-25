import pytest

from engine.crypto_universe import BinanceMarketUniverse


def test_selects_top_liquid_usdt_pairs_and_excludes_stable_and_leveraged_tokens():
    rows = [
        {"symbol": "BTCUSDT", "quoteVolume": "100000000"},
        {"symbol": "ETHUSDT", "quoteVolume": "50000000"},
        {"symbol": "BNBUSDT", "quoteVolume": "10000000"},
        {"symbol": "DOGEUSDT", "quoteVolume": "8000000"},
        {"symbol": "USDCUSDT", "quoteVolume": "500000000"},
        {"symbol": "BTCDOWNUSDT", "quoteVolume": "90000000"},
        {"symbol": "BTCUPUSDT", "quoteVolume": "70000000"},
        {"symbol": "MINIUSDT", "quoteVolume": "500000"},
        {"symbol": "BTCBTC", "quoteVolume": "90000000"},
    ]

    def fake_fetch(url, timeout):
        assert "ticker/24hr" in url
        return rows

    symbols = BinanceMarketUniverse(fetch_json=fake_fetch).top_usdt_symbols(
        limit=3, min_quote_volume=1_000_000
    )
    assert symbols == ("BTCUSDT", "ETHUSDT", "BNBUSDT")


def test_market_universe_rejects_invalid_response_and_limits():
    with pytest.raises(RuntimeError, match="Unexpected Binance"):
        BinanceMarketUniverse(fetch_json=lambda url, timeout: {}).top_usdt_symbols()
    universe = BinanceMarketUniverse(fetch_json=lambda url, timeout: [])
    with pytest.raises(ValueError, match="between 1 and 100"):
        universe.top_usdt_symbols(limit=101)
    with pytest.raises(ValueError, match="cannot be negative"):
        universe.top_usdt_symbols(min_quote_volume=-1)


def test_market_universe_returns_empty_when_no_eligible_liquid_pairs():
    rows = [
        {"symbol": "USDCUSDT", "quoteVolume": "100000000"},
        {"symbol": "BTCDOWNUSDT", "quoteVolume": "90000000"},
        {"symbol": "TINYUSDT", "quoteVolume": "1000"},
    ]
    symbols = BinanceMarketUniverse(fetch_json=lambda url, timeout: rows).top_usdt_symbols()
    assert symbols == ()


def test_default_market_universe_returns_up_to_52_liquid_pairs():
    rows = [
        {"symbol": f"COIN{index}USDT", "quoteVolume": str(100_000_000 - index)}
        for index in range(60)
    ]
    symbols = BinanceMarketUniverse(fetch_json=lambda url, timeout: rows).top_usdt_symbols()
    assert len(symbols) == 52
    assert symbols[0] == "COIN0USDT"
    assert symbols[-1] == "COIN51USDT"
