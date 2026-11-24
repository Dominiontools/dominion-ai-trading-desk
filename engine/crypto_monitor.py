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
        missing_fees = sorted(required.difference(self.costs_by_exchange))
        if missing_fees:
            record.update(status="BLOCKED", reason="FEE_CONFIG_MISSING",
                          missing_fee_exchanges=missing_fees)
            return self._write(record)

        try:
            quotes = self.feeds.snapshot(symbol)
        except Exception as exc:
            record.update(status="BLOCKED", reason="MARKET_DATA_FETCH_FAILED",
                          error_type=type(exc).__name__, error=str(exc)[:240])
            return self._write(record)

        finished = self.clock()
        exchanges_seen = {q.exchange for q in quotes}
        missing_exchanges = sorted(required.difference(exchanges_seen))
        if missing_exchanges or len(exchanges_seen) != len(quotes):
            record.update(
                status="BLOCKED",
                reason="INCOMPLETE_OR_DUPLICATE_EXCHANGE_SNAPSHOT",
                missing_exchanges=missing_exchanges,
                exchanges_seen=sorted(exchanges_seen),
                quote_count=len(quotes),
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
