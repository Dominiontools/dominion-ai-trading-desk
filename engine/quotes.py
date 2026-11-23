"""Fail-closed validation for timestamped two-sided market quotes."""
from __future__ import annotations

from datetime import datetime, timezone


def quote_age_seconds(quote, *, now: datetime | None = None) -> float:
    """Return the older side's age; reject incomplete, naive, or future-dated quotes."""
    if quote.bid is None or quote.ask is None:
        raise ValueError("A complete bid/ask quote is required.")
    if quote.bid <= 0 or quote.ask <= 0 or quote.bid > quote.ask:
        raise ValueError("Quote prices are invalid or crossed.")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("Current time must include a timezone.")

    # cTrader may update bid and ask separately. Both sides must be recent.
    fallback_timestamp = getattr(quote, "timestamp", None)
    side_timestamps = (
        getattr(quote, "bid_timestamp", fallback_timestamp),
        getattr(quote, "ask_timestamp", fallback_timestamp),
    )
    ages = []
    for timestamp in side_timestamps:
        if timestamp is None or timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("Both quote sides must have timezone-aware timestamps.")
        age = (current - timestamp).total_seconds()
        if age < -1:
            raise ValueError("Quote timestamp is in the future.")
        ages.append(max(0.0, age))
    return max(ages)


def is_quote_fresh(quote, *, max_age_seconds: float = 10.0,
                   now: datetime | None = None) -> bool:
    """Return False for stale or invalid quotes; never treat invalid data as fresh."""
    if max_age_seconds <= 0:
        raise ValueError("Maximum quote age must be positive.")
    try:
        return quote_age_seconds(quote, now=now) <= max_age_seconds
    except (AttributeError, TypeError, ValueError, OverflowError):
        return False
