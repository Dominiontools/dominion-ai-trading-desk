import copy
from datetime import datetime, timedelta, timezone
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
        "<h2>Spot fee rates</h2><table><tr><td>0.1% / 0.1%</td></tr></table>",
        "Bitget",
    ) == (10.0, 10.0)
    assert _percent_pair(
        "<table><tr><td>Regular</td><td>0.0800%</td><td>0.1000%</td></tr></table>",
        "OKX",
    ) == (8.0, 10.0)


def test_public_fee_refresh_updates_only_when_official_row_is_parsed():
    pages = {
        "https://www.binance.com/en/fee/trading": "<p>Regular User</p><p>0.090% / 0.100%</p>",
        "https://www.bitget.com/fee/": "<p>Spot fee rates</p><p>0.10% / 0.10%</p>",
        "https://www.okx.com/en-gb/help/important-notice-consolidation-token-pairs": "<p>Regular</p><p>0.0800% 0.1000%</p>",
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
        "https://www.okx.com/en-gb/help/important-notice-consolidation-token-pairs": "<p>Regular</p><p>0.0800% 0.1000%</p>",
    }
    refresh_public_fee_policy(fetch_text=lambda url: pages[url])

    def unavailable(_url):
        raise OSError("offline")

    result = refresh_public_fee_policy(fetch_text=unavailable)
    assert set(result["fees"]) == set(PUBLIC_SPOT_FEES_BPS)
    assert result["sources"]["Binance"]["refresh_status"] == "REFRESH_FAILED_USING_LAST_KNOWN_RATE"
    assert "HTX" not in result["fees"]


def test_cold_start_retains_recent_official_baselines_when_refresh_is_unavailable():
    def unavailable(_url):
        raise OSError("offline")

    result = refresh_public_fee_policy(fetch_text=unavailable)
    assert result["fees"] == PUBLIC_SPOT_FEES_BPS
    for venue in ("Binance", "Bitget", "OKX"):
        assert result["sources"][venue]["verified"] is True
        assert result["sources"][venue]["refresh_status"] == "REFRESH_FAILED_USING_LAST_KNOWN_RATE"


def test_public_fee_baseline_expires_after_seven_days_without_refresh():
    fee_policy._cached_meta["Binance"]["last_refreshed_at"] = (
        datetime.now(timezone.utc) - timedelta(days=8)
    ).isoformat()

    def unavailable(_url):
        raise OSError("offline")

    result = refresh_public_fee_policy(fetch_text=unavailable)
    assert "Binance" not in result["fees"]
    assert result["sources"]["Binance"]["verified"] is False
    assert result["sources"]["Binance"]["refresh_status"] == "STALE_RATE_EXPIRED"
