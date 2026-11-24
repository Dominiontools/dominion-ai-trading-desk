"""Phone-embedded public-crypto paper monitor and loopback read-only API.

No exchange account credentials, wallet access, or order-placement capability.
The embedded start/stop functions are called by the Android foreground service.
"""
from __future__ import annotations

import os
import signal
import threading
from datetime import datetime, timezone
from pathlib import Path

from engine.crypto_api import create_server
from engine.crypto_feeds import PublicCryptoFeeds
from engine.crypto_monitor import CryptoPaperMonitor

_runtime_lock = threading.RLock()
_runtime_stop: threading.Event | None = None
_runtime_server = None
_runtime_threads: list[threading.Thread] = []
_runtime_state: dict = {}


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
        fees[exchange] = (fee, fee)
    return fees


def _runtime_config(data_dir: str | Path, port: int | None = None):
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
    log_path = Path(data_dir) / "crypto_decisions.jsonl"
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
    stop_event = threading.Event()

    def status_provider() -> dict:
        with _runtime_lock:
            return dict(state)

    def monitor_loop() -> None:
        state["engine"] = "running"
        while not stop_event.is_set():
            cycle_started = datetime.now(timezone.utc).isoformat()
            for symbol in symbols:
                if stop_event.is_set():
                    break
                try:
                    monitor.poll_once(symbol)
                    state["last_error"] = None
                except Exception as exc:
                    state["last_error"] = type(exc).__name__
            state["last_cycle_at"] = cycle_started
            stop_event.wait(interval)
        state["engine"] = "stopped"

    api_port = port if port is not None else int(os.getenv("DOMINION_CRYPTO_API_PORT", "8766"))
    server = create_server(str(log_path), status_provider=status_provider,
                           host="127.0.0.1", port=api_port)
    return stop_event, server, monitor_loop, state, symbols, interval


def start_embedded(data_dir: str, port: int = 8766) -> dict:
    """Start the Python engine for the Android foreground service; return immediately."""
    global _runtime_stop, _runtime_server, _runtime_threads, _runtime_state
    with _runtime_lock:
        if _runtime_stop is not None and not _runtime_stop.is_set():
            return {"started": True, "already_running": True, "port": _runtime_server.server_address[1]}
        Path(data_dir).mkdir(parents=True, exist_ok=True)
        stop_event, server, monitor_loop, state, symbols, interval = _runtime_config(data_dir, port)
        worker = threading.Thread(target=monitor_loop, name="dominion-crypto-paper", daemon=True)
        api_thread = threading.Thread(target=server.serve_forever,
                                      kwargs={"poll_interval": 0.5}, daemon=True)
        _runtime_stop, _runtime_server = stop_event, server
        _runtime_threads = [worker, api_thread]
        _runtime_state = state
        worker.start()
        api_thread.start()
        return {"started": True, "already_running": False,
                "port": server.server_address[1], "symbols": list(symbols),
                "interval_seconds": interval, "orders_enabled": False}


def stop_embedded() -> dict:
    """Stop the embedded monitor and local API safely."""
    global _runtime_stop, _runtime_server, _runtime_threads, _runtime_state
    with _runtime_lock:
        stop_event, server, threads = _runtime_stop, _runtime_server, list(_runtime_threads)
        if stop_event is None:
            return {"stopped": True, "already_stopped": True}
        stop_event.set()
    if server is not None:
        server.shutdown()
        server.server_close()
    for thread in threads:
        if thread.is_alive():
            thread.join(timeout=5)
    with _runtime_lock:
        _runtime_stop = None
        _runtime_server = None
        _runtime_threads = []
        _runtime_state = {}
    return {"stopped": True, "orders_enabled": False}


def main() -> None:
    data_dir = os.getenv("DOMINION_DATA_DIR", "data")
    result = start_embedded(data_dir)
    print(f"Dominion paper API listening on http://127.0.0.1:{result['port']}")
    print(f"Symbols: {', '.join(result['symbols'])} | interval: {result['interval_seconds']}s | orders: disabled")
    stop_event = _runtime_stop
    if stop_event is None:
        return

    def request_stop(_signum=None, _frame=None):
        stop_event.set()

    signal.signal(signal.SIGINT, request_stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, request_stop)
    try:
        while not stop_event.wait(0.5):
            pass
    finally:
        stop_embedded()


if __name__ == "__main__":
    main()
