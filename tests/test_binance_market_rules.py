from decimal import Decimal as D
import pytest

from engine.binance_market_rules import parse_symbol_rules


def payload(status="TRADING"):
    return {"symbols": [{
        "symbol": "BTCUSDT", "status": status,
        "filters": [
            {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
            {"filterType": "LOT_SIZE", "stepSize": "0.0001",
             "minQty": "0.0001", "maxQty": "9000"},
            {"filterType": "MIN_NOTIONAL", "minNotional": "5"},
        ],
    }]}


def test_parses_live_exchange_filters_as_verified():
    rules = parse_symbol_rules(payload(), "btcusdt")
    assert rules.verified is True
    assert rules.tick_size == D("0.01")
    assert rules.step_size == D("0.0001")
    assert rules.min_quantity == D("0.0001")
    assert rules.max_quantity == D("9000")
    assert rules.min_notional == D("5")


def test_accepts_notional_filter_variant():
    data = payload()
    data["symbols"][0]["filters"][-1] = {
        "filterType": "NOTIONAL", "minNotional": "10"
    }
    assert parse_symbol_rules(data, "BTCUSDT").min_notional == D("10")


def test_rejects_inactive_or_missing_symbol():
    with pytest.raises(PermissionError, match="not currently trading"):
        parse_symbol_rules(payload("BREAK"), "BTCUSDT")
    with pytest.raises(ValueError, match="not uniquely returned"):
        parse_symbol_rules(payload(), "ETHUSDT")


def test_rejects_missing_duplicate_and_invalid_filters():
    data = payload()
    data["symbols"][0]["filters"] = data["symbols"][0]["filters"][:2]
    with pytest.raises(ValueError, match="notional filter"):
        parse_symbol_rules(data, "BTCUSDT")
    data = payload()
    data["symbols"][0]["filters"].append(data["symbols"][0]["filters"][0])
    with pytest.raises(ValueError, match="exactly one PRICE_FILTER"):
        parse_symbol_rules(data, "BTCUSDT")
    data = payload()
    data["symbols"][0]["filters"][0]["tickSize"] = "0"
    with pytest.raises(ValueError, match="tick size"):
        parse_symbol_rules(data, "BTCUSDT")
