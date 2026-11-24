import pytest

from engine.crypto_service import _fee_config, _positive_float


def test_fee_config_is_empty_without_user_verified_values(monkeypatch):
    for name in ("DOMINION_FEE_BINANCE_TAKER_BPS", "DOMINION_FEE_BITGET_TAKER_BPS",
                 "DOMINION_FEE_HTX_TAKER_BPS"):
        monkeypatch.delenv(name, raising=False)
    assert _fee_config() == {}


def test_fee_config_reads_all_three_explicit_values(monkeypatch):
    monkeypatch.setenv("DOMINION_FEE_BINANCE_TAKER_BPS", "10")
    monkeypatch.setenv("DOMINION_FEE_BITGET_TAKER_BPS", "12")
    monkeypatch.setenv("DOMINION_FEE_HTX_TAKER_BPS", "8")
    result = _fee_config()
    assert result == {"Binance": (10.0, 10.0), "Bitget": (12.0, 12.0),
                      "HTX": (8.0, 8.0)}


def test_fee_config_rejects_negative_fee(monkeypatch):
    monkeypatch.setenv("DOMINION_FEE_BINANCE_TAKER_BPS", "-1")
    with pytest.raises(RuntimeError):
        _fee_config()


def test_positive_float_rejects_zero(monkeypatch):
    monkeypatch.setenv("DOMINION_TEST_INTERVAL", "0")
    with pytest.raises(RuntimeError):
        _positive_float("DOMINION_TEST_INTERVAL", 5.0)
