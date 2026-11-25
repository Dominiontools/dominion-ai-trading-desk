"""Dynamic liquid USDT spot-market universe from Binance public data."""
from __future__ import annotations

import json
from typing import Callable
from urllib.request import Request, urlopen


JsonFetcher = Callable[[str, float], object]


def _fetch_json(url: str, timeout: float) -> object:
    request = Request(url, headers={"User-Agent": "Dominion-AI-Trading-Desk/0.1"})
    with urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"Binance universe HTTP status: {response.status}")
        return json.loads(response.read().decode("utf-8"))


class BinanceMarketUniverse:
    """Select the most liquid eligible USDT spot pairs, excluding leveraged tokens."""

    STABLE_BASES = {
        "USDC", "FDUSD", "TUSD", "USDP", "DAI", "USDE", "BUSD", "USTC",
        "USDD", "EUR", "TRY", "BRL", "BIDR", "AUD", "GBP", "JPY", "RUB",
        "ZAR", "PLN", "RON", "UAH", "ARS", "NGN",
    }
    LEVERAGED_SUFFIXES = ("UP", "DOWN", "BULL", "BEAR", "2L", "2S", "3L", "3S", "5L", "5S")

    def __init__(self, fetch_json: JsonFetcher = _fetch_json, timeout: float = 8.0):
        if timeout <= 0:
            raise ValueError("Timeout must be positive.")
        self.fetch_json = fetch_json
        self.timeout = timeout

    def top_usdt_symbols(self, limit: int = 52, min_quote_volume: float = 1_000_000.0) -> tuple[str, ...]:
        if not 1 <= limit <= 100:
            raise ValueError("Market universe limit must be between 1 and 100.")
        if min_quote_volume < 0:
            raise ValueError("Minimum quote volume cannot be negative.")
        payload = self.fetch_json(
            "https://data-api.binance.vision/api/v3/ticker/24hr", self.timeout
        )
        if not isinstance(payload, list):
            raise RuntimeError("Unexpected Binance 24-hour ticker response.")

        ranked: list[tuple[float, str]] = []
        seen: set[str] = set()
        for row in payload:
            if not isinstance(row, dict):
                continue
            symbol = str(row.get("symbol", "")).upper()
            if not symbol.endswith("USDT") or len(symbol) <= 4 or symbol in seen:
                continue
            base = symbol[:-4]
            if base in self.STABLE_BASES or base.endswith(self.LEVERAGED_SUFFIXES):
                continue
            try:
                quote_volume = float(row.get("quoteVolume", 0))
            except (TypeError, ValueError):
                continue
            if quote_volume < min_quote_volume:
                continue
            seen.add(symbol)
            ranked.append((quote_volume, symbol))

        ranked.sort(key=lambda item: (-item[0], item[1]))
        return tuple(symbol for _volume, symbol in ranked[:limit])
