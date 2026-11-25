"""Read-only public spot order-book ticker adapters for Binance, Bitget, HTX and OKX.

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
    """Fetch best-bid/best-ask snapshots from four public spot APIs."""

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

    def okx(self, symbol: str) -> ExchangeQuote:
        """Fetch one public OKX SPOT best-bid/best-ask ticker without credentials."""
        pair, quote = _symbol_parts(symbol)
        base = pair[:-len(quote)]
        instrument = f"{base}-{quote}"
        query = urlencode({"instId": instrument})
        payload = self._get(f"https://www.okx.com/api/v5/market/ticker?{query}")
        if not isinstance(payload, dict) or payload.get("code") != "0":
            raise RuntimeError("OKX market-data request was not successful.")
        rows = payload.get("data")
        if not isinstance(rows, list):
            raise RuntimeError("Unexpected OKX ticker response.")
        row = next((item for item in rows if isinstance(item, dict)
                    and item.get("instId") == instrument), None)
        if row is None:
            raise RuntimeError(f"OKX did not return {instrument}.")
        stamp = datetime.fromtimestamp(int(row["ts"]) / 1000, timezone.utc)
        return ExchangeQuote(
            "OKX", pair, float(row["bidPx"]), float(row["askPx"]), stamp,
            float(row.get("bidSz", 0)), float(row.get("askSz", 0)),
        )

    def snapshot_with_diagnostics(self, symbol: str) -> tuple[list[ExchangeQuote], dict[str, str]]:
        """Fetch venues concurrently and retain successful quotes independently.

        A single slow venue must not hide healthy venues. The caller decides
        whether enough independent, fresh venues remain for a comparison.
        """
        methods = (self.binance, self.bitget, self.htx, self.okx)
        venue_names = {"binance": "Binance", "bitget": "Bitget", "htx": "HTX", "okx": "OKX"}
        failures: dict[str, str] = {}
        quotes: list[ExchangeQuote] = []
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [(method.__name__, pool.submit(method, symbol)) for method in methods]
            for venue, future in futures:
                try:
                    quotes.append(future.result(timeout=self.timeout + 1.0))
                except Exception as exc:
                    detail = str(exc).replace("\\n", " ")[:180] or type(exc).__name__
                    failures[venue_names[venue]] = f"{type(exc).__name__}: {detail}"
        return quotes, failures

    def snapshot(self, symbol: str) -> list[ExchangeQuote]:
        """Compatibility wrapper returning only successful venue quotes."""
        quotes, _failures = self.snapshot_with_diagnostics(symbol)
        return quotes


    @staticmethod
    def _requested_pairs(symbols: tuple[str, ...] | list[str]) -> dict[str, str]:
        requested: dict[str, str] = {}
        for symbol in symbols:
            pair, _quote = _symbol_parts(symbol)
            requested[pair] = pair
        if not requested:
            raise ValueError("At least one market symbol is required.")
        if len(requested) > 100:
            raise ValueError("Batch market scan is limited to 100 symbols.")
        return requested

    def _binance_many(self, requested: dict[str, str]) -> list[ExchangeQuote]:
        payload = self._get("https://data-api.binance.vision/api/v3/ticker/bookTicker")
        if not isinstance(payload, list):
            raise RuntimeError("Unexpected Binance all-book-ticker response.")
        rows = {str(row.get("symbol", "")).upper(): row for row in payload if isinstance(row, dict)}
        received = datetime.now(timezone.utc)
        quotes = []
        for pair in requested:
            row = rows.get(pair)
            if row is None:
                continue
            try:
                quotes.append(ExchangeQuote(
                    "Binance", pair, float(row["bidPrice"]), float(row["askPrice"]),
                    received, float(row["bidQty"]), float(row["askQty"]),
                ))
            except (KeyError, TypeError, ValueError):
                continue
        return quotes

    def _bitget_many(self, requested: dict[str, str]) -> list[ExchangeQuote]:
        payload = self._get("https://api.bitget.com/api/v2/spot/market/tickers")
        if not isinstance(payload, dict) or payload.get("code") != "00000":
            raise RuntimeError("Bitget all-tickers request was not successful.")
        rows = payload.get("data")
        if not isinstance(rows, list):
            raise RuntimeError("Unexpected Bitget all-tickers response.")
        wanted = set(requested)
        quotes = []
        for row in rows:
            if not isinstance(row, dict) or str(row.get("symbol", "")).upper() not in wanted:
                continue
            try:
                stamp = datetime.fromtimestamp(int(row["ts"]) / 1000, timezone.utc)
                quotes.append(ExchangeQuote(
                    "Bitget", str(row["symbol"]).upper(),
                    float(row["bidPr"]), float(row["askPr"]), stamp,
                    float(row.get("bidSz", 0)), float(row.get("askSz", 0)),
                ))
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
        return quotes

    def _htx_many(self, requested: dict[str, str]) -> list[ExchangeQuote]:
        payload = self._get("https://api.huobi.pro/market/tickers")
        if not isinstance(payload, dict) or payload.get("status") != "ok":
            raise RuntimeError("HTX all-tickers request was not successful.")
        rows = payload.get("data")
        if not isinstance(rows, list):
            raise RuntimeError("Unexpected HTX all-tickers response.")
        try:
            stamp = datetime.fromtimestamp(int(payload["ts"]) / 1000, timezone.utc)
        except (KeyError, TypeError, ValueError, OverflowError):
            stamp = datetime.now(timezone.utc)
        wanted = set(pair.lower() for pair in requested)
        quotes = []
        for row in rows:
            if not isinstance(row, dict) or str(row.get("symbol", "")).lower() not in wanted:
                continue
            try:
                quotes.append(ExchangeQuote(
                    "HTX", str(row["symbol"]).upper(),
                    float(row["bid"]), float(row["ask"]), stamp,
                    float(row.get("bidSize", row.get("bid-size", 0))),
                    float(row.get("askSize", row.get("ask-size", 0))),
                ))
            except (KeyError, TypeError, ValueError):
                continue
        return quotes

    def _okx_many(self, requested: dict[str, str]) -> list[ExchangeQuote]:
        """Fetch one public OKX SPOT ticker snapshot for the requested pairs."""
        payload = self._get("https://www.okx.com/api/v5/market/tickers?instType=SPOT")
        if not isinstance(payload, dict) or payload.get("code") != "0":
            raise RuntimeError("OKX all-spot-tickers request was not successful.")
        rows = payload.get("data")
        if not isinstance(rows, list):
            raise RuntimeError("Unexpected OKX all-spot-tickers response.")
        wanted = set(requested)
        quotes = []
        for row in rows:
            if not isinstance(row, dict) or row.get("instType") != "SPOT":
                continue
            instrument = str(row.get("instId", "")).upper()
            pair = instrument.replace("-", "")
            if pair not in wanted:
                continue
            try:
                stamp = datetime.fromtimestamp(int(row["ts"]) / 1000, timezone.utc)
                bid, ask = float(row["bidPx"]), float(row["askPx"])
                bid_size, ask_size = float(row.get("bidSz", 0)), float(row.get("askSz", 0))
                if min(bid, ask) <= 0 or min(bid_size, ask_size) < 0:
                    continue
                quotes.append(ExchangeQuote(
                    "OKX", pair, bid, ask, stamp, bid_size, ask_size,
                ))
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
        return quotes

    def snapshot_many_with_diagnostics(
        self, symbols: tuple[str, ...] | list[str]
    ) -> tuple[list[ExchangeQuote], dict[str, str]]:
        """Fetch one all-symbol REST snapshot per venue for a multi-market scan."""
        requested = self._requested_pairs(symbols)
        methods = {
            "Binance": self._binance_many,
            "Bitget": self._bitget_many,
            "HTX": self._htx_many,
            "OKX": self._okx_many,
        }
        failures: dict[str, str] = {}
        quotes: list[ExchangeQuote] = []
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {name: pool.submit(method, requested) for name, method in methods.items()}
            for venue, future in futures.items():
                try:
                    quotes.extend(future.result(timeout=self.timeout + 1.0))
                except Exception as exc:
                    detail = str(exc).replace("\\n", " ")[:180] or type(exc).__name__
                    failures[venue] = f"{type(exc).__name__}: {detail}"
        return quotes, failures

    def snapshot_many(self, symbols: tuple[str, ...] | list[str]) -> list[ExchangeQuote]:
        quotes, _failures = self.snapshot_many_with_diagnostics(symbols)
        return quotes
