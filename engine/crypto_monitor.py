"""Controlled continuous paper monitor for public cross-exchange crypto quotes.

This module only observes public data and writes JSONL decisions. It has no
exchange account credentials, wallet access, or order-placement capability.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping

from .crypto_arbitrage import scan_arbitrage


class CryptoPaperMonitor:
    def __init__(
        self,
        feeds,
        *,
        decision_log: str | Path,
        costs_by_exchange: Mapping[str, tuple[float, float]] | None = None,
        interval_seconds: float = 5.0,
        max_quote_age_seconds: float = 2.0,
        min_net_edge_bps: float = 10.0,
        max_notional: float = 20.0,
        clock: Callable[[], datetime] | None = None,
    ):
        if interval_seconds < 1.0:
            raise ValueError("Polling interval must be at least 1 second.")
        self.feeds = feeds
        self.decision_log = Path(decision_log)
        self.costs_by_exchange = dict(costs_by_exchange or {})
        self.interval_seconds = interval_seconds
        self.max_quote_age_seconds = max_quote_age_seconds
        self.min_net_edge_bps = min_net_edge_bps
        self.max_notional = max_notional
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _write(self, record: dict) -> dict:
        self.decision_log.parent.mkdir(parents=True, exist_ok=True)
        if self.decision_log.exists() and self.decision_log.stat().st_size >= 5 * 1024 * 1024:
            backup = self.decision_log.with_name(self.decision_log.name + ".1")
            if backup.exists():
                backup.unlink()
            self.decision_log.replace(backup)
        with self.decision_log.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
            handle.flush()
        return record

    def poll_once(self, symbol: str) -> dict:
        started = self.clock()
        record = {
            "recorded_at": started.astimezone(timezone.utc).isoformat(),
            "symbol": symbol,
            "mode": "PAPER_ONLY",
            "orders_enabled": False,
        }
        required = {"Binance", "Bitget", "HTX"}
        venue_errors: dict[str, str] = {}
        try:
            if hasattr(self.feeds, "snapshot_with_diagnostics"):
                quotes, venue_errors = self.feeds.snapshot_with_diagnostics(symbol)
            else:
                quotes = self.feeds.snapshot(symbol)
        except Exception as exc:
            record.update(status="BLOCKED", reason="MARKET_DATA_FETCH_FAILED",
                          error_type=type(exc).__name__, error=str(exc)[:240])
            return self._write(record)

        finished = self.clock()
        exchanges_seen = {q.exchange for q in quotes}
        duplicates = len(exchanges_seen) != len(quotes)
        record["venue_errors"] = venue_errors
        record["available_exchanges"] = sorted(exchanges_seen)
        if venue_errors:
            record["error"] = " | ".join(f"{venue}: {detail}" for venue, detail in venue_errors.items())[:700]
        if duplicates or len(exchanges_seen) < 2:
            record.update(
                status="BLOCKED",
                reason="INSUFFICIENT_INDEPENDENT_EXCHANGES",
                missing_exchanges=sorted(required.difference(exchanges_seen)),
                exchanges_seen=sorted(exchanges_seen),
                quote_count=len(quotes),
                error="At least two independent exchanges with valid quotes are required.",
            )
            return self._write(record)

        duration_ms = max(0.0, (finished - started).total_seconds() * 1000)
        record["collection_duration_ms"] = round(duration_ms, 3)
        record["quote_count"] = len(quotes)
        record["quotes"] = [
            {
                "exchange": q.exchange,
                "bid": q.bid,
                "ask": q.ask,
                "bid_size": q.bid_size,
                "ask_size": q.ask_size,
                "exchange_or_receipt_timestamp": q.timestamp.astimezone(timezone.utc).isoformat(),
            }
            for q in quotes
        ]
        missing_fees = sorted(exchanges_seen.difference(self.costs_by_exchange))
        if missing_fees:
            record.update(
                status="BLOCKED", reason="FEE_CONFIG_MISSING",
                missing_fee_exchanges=missing_fees,
            )
            return self._write(record)

        opportunities = scan_arbitrage(
            quotes, self.costs_by_exchange, now=finished,
            max_quote_age_seconds=self.max_quote_age_seconds,
            min_net_edge_bps=self.min_net_edge_bps,
            max_notional=self.max_notional,
        )
        if opportunities:
            record.update(
                status="PAPER_OPPORTUNITY", reason="NET_EDGE_THRESHOLD_MET",
                opportunities=[
                    {
                        "buy_exchange": item.buy_exchange,
                        "sell_exchange": item.sell_exchange,
                        "buy_price": item.buy_price,
                        "sell_price": item.sell_price,
                        "gross_edge_bps": item.gross_edge_bps,
                        "estimated_cost_bps": item.estimated_cost_bps,
                        "net_edge_bps": item.net_edge_bps,
                        "max_notional_at_top_of_book": item.max_notional_at_top_of_book,
                    }
                    for item in opportunities
                ],
            )
        else:
            record.update(
                status="NO_QUALIFYING_OPPORTUNITY",
                reason=("No fresh, depth-backed cross-exchange price gap cleared "
                        "configured fees, provisional slippage and minimum net edge."),
            )
        return self._write(record)

    def run(self, symbol: str, *, stop_event: threading.Event,
            max_cycles: int | None = None) -> int:
        """Run until stop_event is set or max_cycles is reached."""
        if stop_event is None:
            raise ValueError("Pass a threading.Event to control shutdown.")
        if max_cycles is not None and max_cycles < 1:
            raise ValueError("max_cycles must be at least 1.")
        cycles = 0
        while not stop_event.is_set() and (max_cycles is None or cycles < max_cycles):
            self.poll_once(symbol)
            cycles += 1
            if max_cycles is not None and cycles >= max_cycles:
                break
            if stop_event.wait(self.interval_seconds):
                break
        return cycles


    def poll_many_once(self, symbols: list[str] | tuple[str, ...]) -> dict:
        """Scan a multi-market universe using one batched public request per venue."""
        started = self.clock()
        requested = tuple(dict.fromkeys(
            str(symbol).replace("/", "").replace("-", "").upper()
            for symbol in symbols if str(symbol).strip()
        ))
        record = {
            "recorded_at": started.astimezone(timezone.utc).isoformat(),
            "symbol": "MULTI_MARKET",
            "symbols_requested": len(requested),
            "symbols": list(requested),
            "mode": "PAPER_ONLY",
            "orders_enabled": False,
        }
        if not requested:
            record.update(status="BLOCKED", reason="EMPTY_MARKET_UNIVERSE")
            return self._write(record)
        if not hasattr(self.feeds, "snapshot_many_with_diagnostics"):
            record.update(status="BLOCKED", reason="BATCH_MARKET_FEED_NOT_AVAILABLE")
            return self._write(record)

        try:
            quotes, venue_errors = self.feeds.snapshot_many_with_diagnostics(requested)
        except Exception as exc:
            record.update(status="BLOCKED", reason="BATCH_MARKET_DATA_FETCH_FAILED",
                          error_type=type(exc).__name__, error=str(exc)[:240])
            return self._write(record)

        finished = self.clock()
        duration_ms = max(0.0, (finished - started).total_seconds() * 1000)
        keys = [(quote.exchange, quote.symbol) for quote in quotes]
        duplicates = len(keys) != len(set(keys))
        exchanges_seen = {quote.exchange for quote in quotes}
        coverage: dict[str, set[str]] = {}
        for quote in quotes:
            coverage.setdefault(quote.symbol, set()).add(quote.exchange)
        comparable_symbols = sorted(
            symbol for symbol, venues in coverage.items() if len(venues) >= 2
        )
        quote_by_key = {(quote.symbol, quote.exchange): quote for quote in quotes}
        record.update({
            "venue_errors": venue_errors,
            "available_exchanges": sorted(exchanges_seen),
            "collection_duration_ms": round(duration_ms, 3),
            "quote_count": len(quotes),
            "symbols_with_quotes": len(coverage),
            "symbols_with_two_venues": len(comparable_symbols),
            "comparable_symbols": comparable_symbols,
            "quotes_by_exchange": {
                venue: sum(quote.exchange == venue for quote in quotes)
                for venue in sorted(exchanges_seen)
            },
            "quotes_preview": [
                {
                    "exchange": quote_by_key[(symbol, venue)].exchange,
                    "symbol": quote_by_key[(symbol, venue)].symbol,
                    "bid": quote_by_key[(symbol, venue)].bid,
                    "ask": quote_by_key[(symbol, venue)].ask,
                    "bid_size": quote_by_key[(symbol, venue)].bid_size,
                    "ask_size": quote_by_key[(symbol, venue)].ask_size,
                    "timestamp": quote_by_key[(symbol, venue)].timestamp.astimezone(timezone.utc).isoformat(),
                }
                for symbol in comparable_symbols[:4]
                for venue in sorted(exchanges_seen)
                if (symbol, venue) in quote_by_key
            ],
        })
        if venue_errors:
            record["error"] = " | ".join(
                f"{venue}: {detail}" for venue, detail in venue_errors.items()
            )[:700]
        if duplicates:
            record.update(status="BLOCKED", reason="DUPLICATE_EXCHANGE_SYMBOL_QUOTES")
            return self._write(record)
        if len(exchanges_seen) < 2 or not comparable_symbols:
            record.update(
                status="BLOCKED",
                reason="INSUFFICIENT_INDEPENDENT_MARKET_QUOTES",
                error="At least two independent exchanges must quote the same symbol.",
            )
            return self._write(record)

        missing_fees = sorted(exchanges_seen.difference(self.costs_by_exchange))
        if missing_fees:
            record.update(
                status="BLOCKED", reason="FEE_CONFIG_MISSING",
                missing_fee_exchanges=missing_fees,
            )
            return self._write(record)

        opportunities = scan_arbitrage(
            quotes, self.costs_by_exchange, now=finished,
            max_quote_age_seconds=self.max_quote_age_seconds,
            min_net_edge_bps=self.min_net_edge_bps,
            max_notional=self.max_notional,
        )
        if opportunities:
            record.update(
                status="PAPER_OPPORTUNITY",
                reason="NET_EDGE_THRESHOLD_MET",
                opportunities=[
                    {
                        "symbol": item.symbol,
                        "buy_exchange": item.buy_exchange,
                        "sell_exchange": item.sell_exchange,
                        "buy_price": item.buy_price,
                        "sell_price": item.sell_price,
                        "gross_edge_bps": item.gross_edge_bps,
                        "estimated_cost_bps": item.estimated_cost_bps,
                        "net_edge_bps": item.net_edge_bps,
                        "max_notional_at_top_of_book": item.max_notional_at_top_of_book,
                    }
                    for item in opportunities[:20]
                ],
                opportunities_count=len(opportunities),
            )
        else:
            record.update(
                status="NO_QUALIFYING_OPPORTUNITY",
                reason="No fresh, depth-backed price gap cleared verified fees, provisional slippage and the minimum net edge.",
                opportunities_count=0,
            )
        return self._write(record)
