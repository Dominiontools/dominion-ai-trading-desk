"""Start the local public-crypto paper monitor and read-only phone API.

Run on the same Android device as the dashboard. This process has no exchange
account keys and cannot place orders. It binds the API to loopback only.
"""
from __future__ import annotations

import os
import signal
import threading
from datetime import datetime, timezone

from engine.crypto_api import create_server
from engine.crypto_feeds import PublicCryptoFeeds
from engine.crypto_monitor import CryptoPaperMonitor


def _positive_float(name: str, default: float) -> float:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = float(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a number.") from exc
    if value <= 0:
        raise RuntimeError(f"{name} must be greater than zero.")
    return value


def _fee_config() -> dict[str, tuple[float, float]]:
    """Read user-verified taker fee estimates; never invent fee values."""
    fees: dict[str, tuple[float, float]] = {}
    for exchange, env_name in (
        ("Binance", "DOMINION_FEE_BINANCE_TAKER_BPS"),
        ("Bitget", "DOMINION_FEE_BITGET_TAKER_BPS"),
        ("HTX", "DOMINION_FEE_HTX_TAKER_BPS"),
    ):
        raw = os.getenv(env_name, "").strip()
        if not raw:
            continue
        try:
            fee = float(raw)
        except ValueError as exc:
            raise RuntimeError(f"{env_name} must be a number.") from exc
        if fee < 0 or fee > 500:
            raise RuntimeError(f"{env_name} must be between 0 and 500 basis points.")
        # Scanner consumes (maker, taker); maker is not used in this conservative model.
        fees[exchange] = (fee, fee)
    return fees


def main() -> None:
    symbols = tuple(
        item.strip().upper().replace("/", "")
        for item in os.getenv("DOMINION_CRYPTO_SYMBOLS", "BTCUSDT,ETHUSDT").split(",")
        if item.strip()
    )
    if not symbols or any(not item.isalnum() for item in symbols):
        raise RuntimeError("DOMINION_CRYPTO_SYMBOLS must contain valid pairs such as BTCUSDT.")
    interval = _positive_float("DOMINION_CRYPTO_INTERVAL_SECONDS", 5.0)
    if interval < 1.0:
        raise RuntimeError("Polling interval cannot be below one second.")
    log_path = os.getenv("DOMINION_CRYPTO_DECISION_LOG", "data/crypto_decisions.jsonl")
    fees = _fee_config()
    feeds = PublicCryptoFeeds(timeout=5.0)
    monitor = CryptoPaperMonitor(
        feeds,
        decision_log=log_path,
        costs_by_exchange=fees,
        interval_seconds=interval,
        max_quote_age_seconds=5.0,
        min_net_edge_bps=10.0,
        max_notional=20.0,
    )

    stop_event = threading.Event()
    state = {
        "engine": "starting",
        "mode": "PAPER_ONLY",
        "orders_enabled": False,
        "symbols": list(symbols),
        "exchanges": ["Binance", "Bitget", "HTX"],
        "poll_interval_seconds": interval,
        "fee_configuration": "complete" if len(fees) == 3 else "missing",
        "last_cycle_at": None,
        "last_error": None,
    }

    def status_provider() -> dict:
        return dict(state)

    def monitor_loop() -> None:
        state["engine"] = "running"
        while not stop_event.is_set():
            cycle_started = datetime.now(timezone.utc).isoformat()
            try:
                for symbol in symbols:
                    if stop_event.is_set():
                        break
                    monitor.poll_once(symbol)
                state["last_error"] = None
            except Exception as exc:  # fail closed and expose only error class
                state["last_error"] = type(exc).__name__
            state["last_cycle_at"] = cycle_started
            stop_event.wait(interval)

        state["engine"] = "stopped"

    api_port = int(os.getenv("DOMINION_CRYPTO_API_PORT", "8766"))
    server = create_server(log_path, status_provider=status_provider,
                           host="127.0.0.1", port=api_port)
    worker = threading.Thread(target=monitor_loop, name="dominion-crypto-paper",
                              daemon=True)

    def request_stop(_signum=None, _frame=None):
        stop_event.set()

    signal.signal(signal.SIGINT, request_stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, request_stop)

    worker.start()
    print(f"Dominion paper API listening on http://127.0.0.1:{api_port}")
    print(f"Symbols: {', '.join(symbols)} | interval: {interval}s | orders: disabled")
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        stop_event.set()
        server.server_close()
        worker.join(timeout=10)
        state["engine"] = "stopped"


if __name__ == "__main__":
    main()
