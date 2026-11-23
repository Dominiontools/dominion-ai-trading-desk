"""Fail-closed validation for timestamped two-sided market quotes."""
from __future__ import annotations

from datetime import datetime, timezone


def quote_age_seconds(quote, *, now: datetime | None = None) -> float:
    """Return quote age; reject incomplete, naive, or materially future-dated quotes."""
    if quote.bid is None or quote.ask is None:
        raise ValueError("A complete bid/ask quote is required.")
    if quote.bid <= 0 or quote.ask <= 0 or quote.bid > quote.ask:
        raise ValueError("Quote prices are invalid or crossed.")
    timestamp = quote.timestamp
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("Quote timestamp must include a timezone.")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("Current time must include a timezone.")
    age = (current - timestamp).total_seconds()
    if age < -1:
        raise ValueError("Quote timestamp is in the future.")
    return max(0.0, age)


def is_quote_fresh(quote, *, max_age_seconds: float = 10.0,
                   now: datetime | None = None) -> bool:
    """Return False for stale or invalid quotes; never treat invalid data as fresh."""
    if max_age_seconds <= 0:
        raise ValueError("Maximum quote age must be positive.")
    try:
        return quote_age_seconds(quote, now=now) <= max_age_seconds
    except (AttributeError, TypeError, ValueError, OverflowError):
        return False
