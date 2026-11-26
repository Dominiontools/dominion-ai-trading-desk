"""Exchange fee policy with conservative public schedules and automatic refresh.

All rates are basis points. Public schedules are not personal account rates.
HTX is deliberately omitted until an official public base-tier rate can be
verified without account login. Binance personal rates are accepted only when
the authenticated integration supplies both rates and marks them verified.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from html.parser import HTMLParser
from math import isfinite
import os
import re
from threading import RLock
from urllib.request import Request, urlopen

# Published regular/base spot rates. Scanner assumes taker on both legs.
PUBLIC_SPOT_FEES_BPS: dict[str, tuple[float, float]] = {
    "Binance": (10.0, 10.0),
    "Bitget": (10.0, 10.0),
    "OKX": (8.0, 10.0),
}
PUBLIC_FEE_URLS = {
    "Binance": "https://www.binance.com/en/fee/trading",
    "Bitget": "https://www.bitget.com/fee/",
    "OKX": "https://www.okx.com/fees",
}
PUBLIC_FEE_SOURCES = {
    "Binance": "BINANCE_PUBLIC_STANDARD_SPOT",
    "Bitget": "BITGET_PUBLIC_STANDARD_SPOT",
    "OKX": "OKX_PUBLIC_REGULAR_SPOT",
    "HTX": "PUBLIC_RATE_NOT_VERIFIABLE",
}
_REFRESH_INTERVAL_SECONDS = 6 * 60 * 60
_lock = RLock()
_cached_fees: dict[str, tuple[float, float]] = {}
_cached_meta: dict[str, dict] = {
    venue: {
        "source": PUBLIC_FEE_SOURCES[venue],
        "verified": False,
        "rate_type": "published_public_base_tier",
        "refresh_status": "BASELINE_AWAITING_REFRESH",
        "source_url": PUBLIC_FEE_URLS[venue],
        "last_refreshed_at": None,
    }
    for venue in PUBLIC_SPOT_FEES_BPS
}
_cached_meta["HTX"] = {
    "source": PUBLIC_FEE_SOURCES["HTX"],
    "verified": False,
    "rate_type": "unavailable",
    "refresh_status": "BLOCKED_NO_PUBLIC_BASE_RATE",
    "source_url": "https://www.htx.com/en-us/fee/?feeType=trading",
    "last_refreshed_at": None,
}
_last_refresh_at: str | None = None


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data and data.strip():
            self.parts.append(data.strip())

    def text(self) -> str:
        return " ".join(self.parts)


def _fetch_text(url: str, timeout: float = 3.0) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; DominionTradingDesk/1.0)",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read(2_000_000).decode(charset, errors="replace")


def _percent_pair(text: str, venue: str) -> tuple[float, float]:
    """Extract only the regular/base-tier maker/taker pair from official text."""
    extractor = _TextExtractor()
    extractor.feed(text)
    normalized = re.sub(r"\s+", " ", extractor.text()).replace(",", "")
    if venue == "Binance":
        marker = re.search(r"Regular User", normalized, re.IGNORECASE)
        if not marker:
            raise ValueError("Binance regular-user fee row not found.")
        tail = normalized[marker.end():marker.end() + 1800]
        pair = re.search(r"(\d+(?:\.\d+)?)\s*%\s*/\s*(\d+(?:\.\d+)?)\s*%", tail)
    elif venue == "Bitget":
        marker = re.search(r"VIP\s*0|VIP0|Regular", normalized, re.IGNORECASE)
        if not marker:
            raise ValueError("Bitget VIP0 fee row not found.")
        tail = normalized[marker.end():marker.end() + 1800]
        pair = re.search(r"(\d+(?:\.\d+)?)\s*%\s*/\s*(\d+(?:\.\d+)?)\s*%", tail)
        if not pair:
            # The fee page may render maker and taker as adjacent columns.
            pair = re.search(r"(\d+(?:\.\d+)?)\s*%\s+(\d+(?:\.\d+)?)\s*%", tail)
    else:
        marker = re.search(r"Regular", normalized, re.IGNORECASE)
        if not marker:
            raise ValueError("OKX Regular spot fee row not found.")
        tail = normalized[marker.end():marker.end() + 1800]
        pair = re.search(r"(\d+(?:\.\d+)?)\s*%\s+(\d+(?:\.\d+)?)\s*%", tail)
    if not pair:
        raise ValueError(f"{venue} regular spot maker/taker rates could not be parsed.")
    maker_pct, taker_pct = (float(pair.group(1)), float(pair.group(2)))
    values = (maker_pct * 100.0, taker_pct * 100.0)
    if any(not isfinite(value) or value < 0 or value > 500 for value in values):
        raise ValueError(f"{venue} returned an invalid public fee rate.")
    return values


def refresh_public_fee_policy(fetch_text=_fetch_text) -> dict:
    """Refresh official public schedules; preserve last-known rates on fetch errors.

    Returns a copy of rates and source metadata. A venue is only marked freshly
    verified when its official page was fetched and its base-tier row parsed.
    """
    global _last_refresh_at
    fetched_at = datetime.now(timezone.utc).isoformat()
    results: dict[str, tuple[float, float] | Exception] = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {
            pool.submit(fetch_text, url): venue
            for venue, url in PUBLIC_FEE_URLS.items()
        }
        for future in as_completed(futures):
            venue = futures[future]
            try:
                html = future.result()
                parser = _TextExtractor()
                parser.feed(html)
                results[venue] = _percent_pair(parser.text(), venue)
            except Exception as exc:
                results[venue] = exc

    with _lock:
        for venue, result in results.items():
            if isinstance(result, Exception):
                previous = dict(_cached_meta.get(venue, {}))
                previous.update({
                    "refresh_status": "REFRESH_FAILED_USING_LAST_KNOWN_RATE",
                    "last_refresh_attempt_at": fetched_at,
                    "last_error": type(result).__name__,
                })
                _cached_meta[venue] = previous
                continue
            _cached_fees[venue] = result
            _cached_meta[venue] = {
                "source": PUBLIC_FEE_SOURCES[venue],
                "verified": True,
                "rate_type": "official_public_base_tier",
                "refresh_status": "REFRESHED",
                "source_url": PUBLIC_FEE_URLS[venue],
                "last_refreshed_at": fetched_at,
            }
        _last_refresh_at = fetched_at
        return {
            "fees": dict(_cached_fees),
            "sources": {key: dict(value) for key, value in _cached_meta.items()},
            "last_refresh_at": _last_refresh_at,
            "next_refresh_in_seconds": _REFRESH_INTERVAL_SECONDS,
        }


def load_fee_policy() -> tuple[dict[str, tuple[float, float]], dict]:
    """Return the latest public rates and any explicitly verified Binance override."""
    with _lock:
        fees = dict(PUBLIC_SPOT_FEES_BPS)
        fees.update(_cached_fees)
        sources = {key: dict(value) for key, value in _cached_meta.items()}

    personal_maker = _read_bps("DOMINION_FEE_BINANCE_PERSONAL_MAKER_BPS")
    personal_taker = _read_bps("DOMINION_FEE_BINANCE_PERSONAL_TAKER_BPS")
    personal_verified = os.getenv("DOMINION_FEE_BINANCE_PERSONAL_VERIFIED", "").strip().upper() == "YES"
    if (personal_maker is None) != (personal_taker is None):
        raise RuntimeError("Set both Binance personal maker and taker rates together.")
    if personal_maker is not None:
        if not personal_verified:
            raise RuntimeError("Binance personal fee rates require DOMINION_FEE_BINANCE_PERSONAL_VERIFIED=YES.")
        fees["Binance"] = (personal_maker, personal_taker)
        sources["Binance"] = {
            "source": "BINANCE_PERSONAL_ACCOUNT_RATE",
            "verified": True,
            "rate_type": "personal_account_rate",
            "refresh_status": "AUTHENTICATED_ACCOUNT_RATE",
            "last_refreshed_at": datetime.now(timezone.utc).isoformat(),
        }
    else:
        sources["Binance"]["rate_type"] = (
            "official_public_base_tier" if "Binance" in _cached_fees
            else "published_public_fallback_not_yet_refreshed"
        )
    return fees, sources


def _read_bps(env_name: str) -> float | None:
    raw = os.getenv(env_name, "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError as exc:
        raise RuntimeError(f"{env_name} must be a number.") from exc
    if not isfinite(value) or value < 0 or value > 500:
        raise RuntimeError(f"{env_name} must be a finite value between 0 and 500 basis points.")
    return value


def fee_refresh_interval_seconds() -> int:
    return _REFRESH_INTERVAL_SECONDS
