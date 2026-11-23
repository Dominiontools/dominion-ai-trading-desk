"""Local read-only cTrader demo market-data worker.

This process only authenticates with view-only scope and streams demo quotes.
It has no order execution path. A disconnect or startup timeout stops the worker.
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import timezone

from engine.ctrader_demo import CTraderDemoConfig, CTraderDemoConnector
from engine.quotes import is_quote_fresh, quote_age_seconds

LOGGER = logging.getLogger("dominion.ctrader_worker")


def run_worker() -> None:
    try:
        from twisted.internet import reactor, task
    except ImportError as exc:
        raise RuntimeError("Install the worker dependencies with pip install -r requirements.txt") from exc

    config = CTraderDemoConfig.from_env()
    symbols = [item.strip() for item in os.getenv("CTRADER_SYMBOLS", "").split(",") if item.strip()]
    if not symbols:
        raise RuntimeError("Set CTRADER_SYMBOLS to a comma-separated list of enabled demo symbols.")
    try:
        max_quote_age = float(os.getenv("CTRADER_MAX_QUOTE_AGE_SECONDS", "10"))
    except ValueError as exc:
        raise RuntimeError("CTRADER_MAX_QUOTE_AGE_SECONDS must be a number.") from exc
    if max_quote_age <= 0:
        raise RuntimeError("CTRADER_MAX_QUOTE_AGE_SECONDS must be positive.")

    latest_quotes = {}
    stale_state: dict[str, bool | None] = {symbol: None for symbol in symbols}
    started_at = time.monotonic()
    subscribed = False
    connector: CTraderDemoConnector

    def on_quote(quote) -> None:
        latest_quotes[quote.symbol] = quote
        try:
            age = quote_age_seconds(quote)
        except ValueError as exc:
            LOGGER.warning("Rejected invalid quote for %s: %s", quote.symbol, exc)
            return
        LOGGER.info(json.dumps({
            "event": "quote",
            "symbol": quote.symbol,
            "bid": quote.bid,
            "ask": quote.ask,
            "timestamp": quote.timestamp.astimezone(timezone.utc).isoformat(),
            "age_seconds": round(age, 3),
            "fresh": age <= max_quote_age,
            "mode": "DEMO_READ_ONLY",
        }, separators=(",", ":")))

    connector = CTraderDemoConnector(config, on_quote=on_quote)

    def stop_worker(reason: str) -> None:
        LOGGER.error("Worker stopping: %s", reason)
        try:
            connector.stop()
        finally:
            if reactor.running:
                reactor.stop()

    def monitor() -> None:
        nonlocal subscribed
        if connector.state == "READY_DEMO_READ_ONLY" and not subscribed:
            try:
                connector.subscribe_spots(symbols)
            except Exception as exc:
                stop_worker(f"Could not subscribe to requested symbols: {exc}")
                return
            subscribed = True
            LOGGER.info("Subscribed to demo quotes for: %s", ", ".join(symbols))
        elif connector.state in {
            "ERROR", "DISCONNECTED", "ACCOUNT_NOT_GRANTED",
            "REFUSED_NON_DEMO_OR_UNVERIFIED_ACCOUNT",
        }:
            stop_worker(f"cTrader connection state is {connector.state}")
            return
        elif not subscribed and time.monotonic() - started_at > 30:
            stop_worker("Timed out waiting for cTrader demo authentication and symbol list")
            return

        if subscribed:
            for symbol in symbols:
                quote = latest_quotes.get(symbol)
                fresh = quote is not None and is_quote_fresh(quote, max_age_seconds=max_quote_age)
                if stale_state[symbol] != fresh:
                    stale_state[symbol] = fresh
                    if fresh:
                        LOGGER.info("Quote feed fresh for %s", symbol)
                    else:
                        LOGGER.warning("Quote feed missing or stale for %s; trading must remain blocked", symbol)

    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(),
                        format="%(asctime)s %(levelname)s %(message)s")
    monitor_loop = task.LoopingCall(monitor)
    monitor_loop.start(1.0, now=False)
    connector.start()
    LOGGER.info("Started cTrader demo read-only worker; requested symbols: %s", ", ".join(symbols))
    reactor.run()


if __name__ == "__main__":
    run_worker()
