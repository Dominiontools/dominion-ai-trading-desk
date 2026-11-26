import copy
import pytest
import engine.crypto_fee_policy as fee_policy
from engine.crypto_fee_policy import (
    PUBLIC_SPOT_FEES_BPS,
    _percent_pair,
    refresh_public_fee_policy,
)


@pytest.fixture(autouse=True)
def isolate_fee_cache():
    original_fees = dict(fee_policy._cached_fees)
    original_meta = copy.deepcopy(fee_policy._cached_meta)
    original_refresh = fee_policy._last_refresh_at
    fee_policy._cached_fees.clear()
    yield
    fee_policy._cached_fees.clear()
    fee_policy._cached_fees.update(original_fees)
    fee_policy._cached_meta.clear()
    fee_policy._cached_meta.update(original_meta)
    fee_policy._last_refresh_at = original_refresh


def test_parse_official_public_base_tier_fee_rows():
    assert _percent_pair(
        "<table><tr><td>Regular User</td><td>0.100% / 0.100%</td></tr></table>",
        "Binance",
    ) == (10.0, 10.0)
    assert _percent_pair(
        "<table><tr><td>VIP0</td><td>0.10% / 0.10%</td></tr></table>",
        "Bitget",
    ) == (10.0, 10.0)
    assert _percent_pair(
        "<table><tr><td>Regular</td><td>0.0800%</td><td>0.1000%</td></tr></table>",
        "OKX",
    ) == (8.0, 10.0)


def test_public_fee_refresh_updates_only_when_official_row_is_parsed():
    pages = {
        "https://www.binance.com/en/fee/trading": "<p>Regular User</p><p>0.090% / 0.100%</p>",
        "https://www.bitget.com/fee/": "<p>VIP0</p><p>0.10% / 0.10%</p>",
        "https://www.okx.com/fees": "<p>Regular</p><p>0.0800% 0.1000%</p>",
    }
    result = refresh_public_fee_policy(fetch_text=lambda url: pages[url])
    assert result["fees"]["Binance"] == (9.0, 10.0)
    assert result["fees"]["Bitget"] == (10.0, 10.0)
    assert result["fees"]["OKX"] == (8.0, 10.0)
    assert result["sources"]["Binance"]["refresh_status"] == "REFRESHED"
    assert "HTX" not in result["fees"]
    assert result["sources"]["HTX"]["refresh_status"] == "BLOCKED_NO_PUBLIC_BASE_RATE"


def test_failed_public_fee_refresh_keeps_last_known_rates_and_marks_failure():
    pages = {
        "https://www.binance.com/en/fee/trading": "<p>Regular User</p><p>0.100% / 0.100%</p>",
        "https://www.bitget.com/fee/": "<p>VIP0</p><p>0.10% / 0.10%</p>",
        "https://www.okx.com/fees": "<p>Regular</p><p>0.0800% 0.1000%</p>",
    }
    refresh_public_fee_policy(fetch_text=lambda url: pages[url])

    def unavailable(_url):
        raise OSError("offline")

    result = refresh_public_fee_policy(fetch_text=unavailable)
    assert set(result["fees"]) == set(PUBLIC_SPOT_FEES_BPS)
    assert result["sources"]["Binance"]["refresh_status"] == "REFRESH_FAILED_USING_LAST_KNOWN_RATE"
    assert "HTX" not in result["fees"]
