"""Read-only public spot order-book ticker adapters for Binance, Bitget and HTX.

No API keys, account endpoints, wallet access, or order methods are used.
These are REST snapshots, not exchange WebSocket streams.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .crypto_arbitrage import ExchangeQuote


JsonFetcher = Callable[[str, float], object]


def _http_json(url: str, timeout: float = 5.0) -> object:
    request = Request(url, headers={"User-Agent": "Dominion-AI-Trading-Desk/0.1"})
    with urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"Market-data HTTP status: {response.status}")
        return json.loads(response.read().decode("utf-8"))


def _symbol_parts(symbol: str) -> tuple[str, str]:
    normalized = symbol.replace("/", "").replace("-", "").upper()
    if not normalized or not normalized.isalnum():
        raise ValueError("Use a valid symbol such as BTC/USDT.")
    for quote in ("USDT", "USDC", "BTC", "ETH", "USD", "EUR", "BNB"):
        if normalized.endswith(quote) and len(normalized) > len(quote):
            return normalized, quote
    raise ValueError("Could not identify the quote asset in the symbol.")


class PublicCryptoFeeds:
    """Fetch best-bid/best-ask snapshots from three public spot APIs."""

    def __init__(self, fetch_json: JsonFetcher = _http_json, timeout: float = 5.0):
        if timeout <= 0:
            raise ValueError("Timeout must be positive.")
        self.fetch_json = fetch_json
        self.timeout = timeout

    def _get(self, url: str) -> object:
        return self.fetch_json(url, self.timeout)

    def binance(self, symbol: str) -> ExchangeQuote:
        pair, _ = _symbol_parts(symbol)
        query = urlencode({"symbol": pair})
        payload = self._get(f"https://data-api.binance.vision/api/v3/ticker/bookTicker?{query}")
        if not isinstance(payload, dict) or payload.get("symbol") != pair:
            raise RuntimeError("Unexpected Binance book-ticker response.")
        # Binance bookTicker has no event timestamp; use local receipt time.
        return ExchangeQuote("Binance", symbol, float(payload["bidPrice"]),
                             float(payload["askPrice"]), datetime.now(timezone.utc),
                             float(payload["bidQty"]), float(payload["askQty"]))

    def bitget(self, symbol: str) -> ExchangeQuote:
        pair, _ = _symbol_parts(symbol)
        query = urlencode({"symbol": pair})
        payload = self._get(f"https://api.bitget.com/api/v2/spot/market/tickers?{query}")
        if not isinstance(payload, dict) or payload.get("code") != "00000":
            raise RuntimeError("Bitget market-data request was not successful.")
        rows = payload.get("data")
        if not isinstance(rows, list):
            raise RuntimeError("Unexpected Bitget ticker response.")
        row = next((item for item in rows if item.get("symbol") == pair), None)
        if row is None:
            raise RuntimeError(f"Bitget did not return {pair}.")
        stamp = datetime.fromtimestamp(int(row["ts"]) / 1000, timezone.utc)
        return ExchangeQuote("Bitget", symbol, float(row["bidPr"]), float(row["askPr"]),
                             stamp, float(row["bidSz"]), float(row["askSz"]))

    def htx(self, symbol: str) -> ExchangeQuote:
        pair, _ = _symbol_parts(symbol)
        query = urlencode({"symbol": pair.lower()})
        payload = self._get(f"https://api.huobi.pro/market/detail/merged?{query}")
        if not isinstance(payload, dict) or payload.get("status") != "ok":
            raise RuntimeError("HTX market-data request was not successful.")
        tick = payload.get("tick")
        if not isinstance(tick, dict) or not isinstance(tick.get("bid"), list) or not isinstance(tick.get("ask"), list):
            raise RuntimeError("Unexpected HTX merged-ticker response.")
        stamp = datetime.fromtimestamp(int(payload["ts"]) / 1000, timezone.utc)
        return ExchangeQuote("HTX", symbol, float(tick["bid"][0]), float(tick["ask"][0]),
                             stamp, float(tick["bid"][1]), float(tick["ask"][1]))

    def snapshot(self, symbol: str) -> list[ExchangeQuote]:
        """Fetch exchanges concurrently to reduce inter-venue collection skew.

        Any venue failure aborts the snapshot; partial sets are not presented as
        a complete three-exchange comparison.
        """
        methods = (self.binance, self.bitget, self.htx)
        failures = []
        quotes = []
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [(method.__name__, pool.submit(method, symbol)) for method in methods]
            for venue, future in futures:
                try:
                    quotes.append(future.result(timeout=self.timeout + 1.0))
                except Exception as exc:
                    # Keep the monitor fail-closed, but retain the exact venue
                    # and bounded exception detail for diagnosis in the app.
                    detail = str(exc).replace("\\n", " ")[:180] or type(exc).__name__
                    failures.append(f"{venue}: {type(exc).__name__}: {detail}")
        if failures:
            raise RuntimeError("Market-data venue failures: " + " | ".join(failures)[:700])
        return quotes
