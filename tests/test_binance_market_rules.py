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



def commission_payload(symbol="BTCUSDT"):
    return {
        "symbol": symbol,
        "standardCommission": {
            "maker": "0.0008", "taker": "0.0010",
            "buyer": "0.0012", "seller": "0.0011",
        },
        "specialCommission": {
            "maker": "0", "taker": "0.0001",
            "buyer": "0", "seller": "0",
        },
        "taxCommission": {
            "maker": "0.000001", "taker": "0.000002",
            "buyer": "0.000003", "seller": "0.000002",
        },
        "discount": {
            "enabledForAccount": True, "enabledForSymbol": True,
            "discountAsset": "BNB", "discount": "0.75",
        },
    }


def test_account_commission_parser_uses_conservative_verified_rates():
    from engine.binance_market_rules import parse_account_commission
    fees = parse_account_commission(commission_payload(), "BTCUSDT")
    assert fees.verified is True
    # max(12 bps) + max(1 bps) + max(0.03 bps); BNB discount is ignored.
    assert fees.taker_fee_bps == D("13.03")


def test_account_commission_parser_rejects_symbol_mismatch_and_missing_groups():
    from engine.binance_market_rules import parse_account_commission
    with pytest.raises(ValueError, match="does not match"):
        parse_account_commission(commission_payload(), "ETHUSDT")
    data = commission_payload()
    del data["taxCommission"]
    with pytest.raises(ValueError, match="taxCommission"):
        parse_account_commission(data, "BTCUSDT")


def test_account_commission_parser_rejects_invalid_or_negative_rates():
    from engine.binance_market_rules import parse_account_commission
    data = commission_payload()
    data["standardCommission"]["taker"] = "NaN"
    with pytest.raises(ValueError, match="taker rate"):
        parse_account_commission(data, "BTCUSDT")
