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
from engine.agent_feeds import DexScreenerDiscovery, GeckoTerminalWhaleFeed, GoPlusSecurityFeed, PublicNewsRSS
from engine.specialist_agents import HypeAgent, WhaleAgent
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
        "agents": {
            "SCANNER": {"status": "RUNNING", "detail": "Public crypto price-gap scanner runs with the phone monitor."},
            "RISK": {"status": "PAPER_READY", "detail": "0.5% trade-risk and 2% daily-loss checks are implemented; not yet wired to broker orders."},
            "SNIPER": {"status": "PAPER_READY", "detail": "Risk-gated paper order proposals only; no exchange or broker order is sent."},
            "WHALE": {"status": "WAITING_FOR_FEED", "detail": "Large-trade analysis is implemented; a trade-flow feed is not connected."},
            "RUG": {"status": "WAITING_FOR_EVIDENCE", "detail": "Token safety checklist is implemented; on-chain contract/liquidity evidence is not connected."},
            "EXIT": {"status": "WAITING_FOR_POSITIONS", "detail": "Paper stop/target/trailing evaluation is implemented; no broker positions are connected."},
            "HYPE": {"status": "WAITING_FOR_FEED", "detail": "Text sentiment analysis is implemented; social/news collection is not connected."},
            "DESK MANAGER": {"status": "COORDINATOR_READY", "detail": "Specialist coordination component is implemented; full live workflow is not enabled."},
        },
    }
    stop_event = threading.Event()
    discovery_feed = DexScreenerDiscovery(timeout=8.0)
    whale_feed = GeckoTerminalWhaleFeed(timeout=8.0, min_notional_usd=100_000.0)
    security_feed = GoPlusSecurityFeed(token=os.getenv("DOMINION_GOPLUS_TOKEN", "").strip() or None, timeout=8.0)
    news_feed = PublicNewsRSS(timeout=8.0)
    network_map = {"ethereum":"eth", "bsc":"bsc", "base":"base", "solana":"solana", "polygon":"polygon_pos", "arbitrum":"arbitrum", "optimism":"optimism", "avalanche":"avax", "fantom":"fantom", "cronos":"cronos"}

    def agent_feed_loop() -> None:
        while not stop_event.is_set():
            try:
                discovered = discovery_feed.discover(limit=8)
                state["agents"]["SCANNER"] = {"status":"CONNECTED" if discovered else "CONNECTED_NO_NEW_TOKENS", "detail":f"DEX Screener connected; {len(discovered)} recent token pools enriched with price/liquidity/volume."}
                whale_trades = []
                whale_errors = 0
                for token in discovered[:5]:
                    network = network_map.get(token["chain_id"].lower())
                    if not network or not token.get("pair_address"):
                        continue
                    try:
                        whale_trades.extend(whale_feed.trades(network, token["pair_address"], token["symbol"]))
                    except Exception:
                        whale_errors += 1
                whale_result = WhaleAgent(min_notional_usd=100_000.0).analyze(whale_trades)
                state["agents"]["WHALE"] = {"status":"CONNECTED" if not whale_errors else "PARTIAL", "detail":f"GeckoTerminal checked {min(len(discovered), 5)} pools; {len(whale_result.findings)} trades met the USD 100,000 alert threshold.", "alerts":list(whale_result.findings[:5])}
                security_results = []
                for token in discovered[:5]:
                    if token["chain_id"].lower() not in GoPlusSecurityFeed.CHAIN_IDS:
                        continue
                    try:
                        security_results.append(security_feed.assess(token["chain_id"], token["token_address"]))
                    except Exception as exc:
                        security_results.append({"status":"FEED_ERROR", "error":type(exc).__name__})
                risk_count = sum(item.get("status") == "RISK_FLAGS_FOUND" for item in security_results)
                error_count = sum(item.get("status") == "FEED_ERROR" for item in security_results)
                if not security_results:
                    rug_status = "NO_SUPPORTED_TOKENS"
                elif error_count:
                    rug_status = "PARTIAL"
                else:
                    rug_status = "CONNECTED"
                state["agents"]["RUG"] = {
                    "status": rug_status,
                    "detail": f"GoPlus free-tier lookup attempted for {len(security_results)} supported EVM contracts; {risk_count} returned explicit risk flags and {error_count} requests failed. Missing fields remain unknown.",
                    "risk_flags": [item for item in security_results if item.get("risks")][:5],
                    "errors": error_count,
                }
                headlines = news_feed.headlines(limit=20)
                hype_result = HypeAgent().score(headlines)
                state["agents"]["HYPE"] = {"status":"CONNECTED" if headlines else "CONNECTED_NO_HEADLINES", "detail":f"Public Cointelegraph RSS checked; {len(headlines)} headlines analysed. Keyword sentiment is only a rough signal.", "summary":hype_result.summary}
                state["agents"]["DESK MANAGER"] = {"status":"RUNNING", "detail":"Completed public-feed cycle: token discovery, whale-trade scan, token-security lookup status and news sentiment."}
                state["agent_feed_last_cycle"] = datetime.now(timezone.utc).isoformat()
                state["agent_feed_error"] = None
            except Exception as exc:
                state["agent_feed_error"] = type(exc).__name__
                state["agents"]["DESK MANAGER"] = {"status":"PARTIAL", "detail":f"Agent feed cycle encountered {type(exc).__name__}; individual feed states are retained."}
            stop_event.wait(60.0)

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
    return stop_event, server, monitor_loop, agent_feed_loop, state, symbols, interval


def start_embedded(data_dir: str, port: int = 8766) -> dict:
    """Start the Python engine for the Android foreground service; return immediately."""
    global _runtime_stop, _runtime_server, _runtime_threads, _runtime_state
    with _runtime_lock:
        if _runtime_stop is not None and not _runtime_stop.is_set():
            return {"started": True, "already_running": True, "port": _runtime_server.server_address[1]}
        Path(data_dir).mkdir(parents=True, exist_ok=True)
        stop_event, server, monitor_loop, agent_feed_loop, state, symbols, interval = _runtime_config(data_dir, port)
        worker = threading.Thread(target=monitor_loop, name="dominion-crypto-paper", daemon=True)
        agent_worker = threading.Thread(target=agent_feed_loop, name="dominion-agent-feeds", daemon=True)
        api_thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.5}, daemon=True)
        _runtime_stop, _runtime_server = stop_event, server
        _runtime_threads = [worker, agent_worker, api_thread]
        _runtime_state = state
        worker.start()
        agent_worker.start()
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
