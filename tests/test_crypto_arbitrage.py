from datetime import datetime, timezone, timedelta

import pytest

from engine.crypto_arbitrage import ExchangeQuote, scan_arbitrage


NOW = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)


def q(exchange, bid, ask, *, age=0, bid_size=2, ask_size=2):
    return ExchangeQuote(exchange, "BTC/USDT", bid, ask,
                         NOW - timedelta(seconds=age), bid_size, ask_size)


def fees():
    return {"Binance": (1.0, 5.0), "Bitget": (1.0, 5.0), "HTX": (1.0, 5.0)}


def test_finds_positive_net_gap_and_is_paper_only():
    result = scan_arbitrage([q("Binance", 100000, 100010),
                             q("Bitget", 100500, 100510)],
                            fees(), now=NOW, min_net_edge_bps=10)
    assert len(result) == 1
    assert result[0].buy_exchange == "Binance"
    assert result[0].sell_exchange == "Bitget"
    assert result[0].mode == "PAPER_ONLY"
    assert result[0].net_edge_bps > 0


def test_rejects_gap_erased_by_fees_and_slippage():
    result = scan_arbitrage([q("Binance", 100000, 100010),
                             q("Bitget", 100050, 100060)],
                            fees(), now=NOW, min_net_edge_bps=1)
    assert result == []


def test_ignores_stale_quotes_and_missing_depth():
    result = scan_arbitrage([q("Binance", 100000, 100010, age=5),
                             q("Bitget", 100500, 100510),
                             q("HTX", 100600, 100610, bid_size=0)],
                            fees(), now=NOW)
    assert result == []


def test_ignores_same_exchange_and_different_symbols():
    result = scan_arbitrage([q("Binance", 100000, 100010),
                             ExchangeQuote("Binance", "BTC/USDT", 100500, 100510, NOW, 2, 2),
                             ExchangeQuote("Bitget", "ETH/USDT", 3000, 3010, NOW, 2, 2)],
                            fees(), now=NOW)
    assert result == []



@pytest.mark.parametrize("bid,ask,bid_size,ask_size", [
    (float("nan"), 11, 1, 1),
    (10, float("inf"), 1, 1),
    (10, 11, float("nan"), 1),
    (10, 11, 1, float("inf")),
])
def test_rejects_non_finite_market_quote_values(bid, ask, bid_size, ask_size):
    with pytest.raises(ValueError, match="finite"):
        ExchangeQuote("Binance", "BTC/USDT", bid, ask, NOW, bid_size, ask_size)


def test_arbitrage_scanner_rejects_non_finite_fee_inputs():
    result = scan_arbitrage(
        [q("Binance", 100000, 100010), q("Bitget", 100500, 100510)],
        {"Binance": (1.0, float("nan")), "Bitget": (1.0, 5.0)},
        now=NOW,
    )
    assert result == []


def test_rejects_invalid_naive_timestamp():
    with pytest.raises(ValueError):
        ExchangeQuote("Binance", "BTC/USDT", 10, 11, datetime(2026, 1, 1))
