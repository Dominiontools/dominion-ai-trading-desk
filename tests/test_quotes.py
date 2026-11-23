from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from engine.quotes import is_quote_fresh, quote_age_seconds


def make_quote(timestamp, bid=1.1, ask=1.1001):
    return SimpleNamespace(timestamp=timestamp, bid=bid, ask=ask)


def test_recent_quote_is_fresh_and_age_is_calculated():
    now = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)
    quote = make_quote(now - timedelta(seconds=3))
    assert quote_age_seconds(quote, now=now) == 3
    assert is_quote_fresh(quote, max_age_seconds=10, now=now)


def test_each_side_must_be_fresh_when_bid_and_ask_update_separately():
    now = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)
    quote = SimpleNamespace(
        timestamp=now,
        bid=1.1,
        ask=1.1001,
        bid_timestamp=now - timedelta(seconds=1),
        ask_timestamp=now - timedelta(seconds=11),
    )
    assert quote_age_seconds(quote, now=now) == 11
    assert not is_quote_fresh(quote, max_age_seconds=10, now=now)


def test_stale_quote_is_not_fresh():
    now = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)
    quote = make_quote(now - timedelta(seconds=11))
    assert not is_quote_fresh(quote, max_age_seconds=10, now=now)


def test_invalid_quotes_fail_closed():
    now = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)
    assert not is_quote_fresh(make_quote(now, bid=None), now=now)
    assert not is_quote_fresh(make_quote(now, bid=1.2, ask=1.1), now=now)
    assert not is_quote_fresh(make_quote(now.replace(tzinfo=None)), now=now)
    assert not is_quote_fresh(make_quote(now + timedelta(seconds=5)), now=now)


def test_freshness_limit_must_be_positive():
    now = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)
    try:
        is_quote_fresh(make_quote(now), max_age_seconds=0, now=now)
    except ValueError:
        pass
    else:
        raise AssertionError("Expected invalid max quote age to be rejected.")
