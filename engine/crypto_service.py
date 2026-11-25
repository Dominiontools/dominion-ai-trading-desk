"""Phone-embedded public-crypto paper monitor and loopback read-only API.

No exchange account credentials, wallet access, or order-placement capability.
The embedded start/stop functions are called by the Android foreground service.
"""
from __future__ import annotations

import os
import signal
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from engine.crypto_api import create_server
from engine.agent_feeds import DexScreenerDiscovery, GeckoTerminalWhaleFeed, GoPlusSecurityFeed, PublicNewsRSS
from engine.specialist_agents import HypeAgent, WhaleAgent
from engine.crypto_feeds import PublicCryptoFeeds
from engine.crypto_universe import BinanceMarketUniverse
from engine.gmgn_api import GMGNReadOnlyClient, summarize_security_evidence, extract_trenches_tokens
from engine.gmgn_sniper import GMGNSniperAgent
from engine.crypto_monitor import CryptoPaperMonitor
from engine.paper_workflow import PaperTradingDesk
from engine.crypto_strategy import BinancePublicCandleFeed, ConfluencePaperStrategy
from engine.confluence_strategy import TIMEFRAME_PROFILES
from engine.readiness import build_readiness

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
        ("OKX", "DOMINION_FEE_OKX_TAKER_BPS"),
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


def _runtime_config(data_dir: str | Path, port: int | None = None, gmgn_api_key: str = ""):
    symbols = tuple(
        item.strip().upper().replace("/", "")
        for item in os.getenv("DOMINION_CRYPTO_SYMBOLS", "BTCUSDT,ETHUSDT,PAXGUSDT").split(",")
        if item.strip()
    )
    if not symbols or any(not item.isalnum() for item in symbols):
        raise RuntimeError("DOMINION_CRYPTO_SYMBOLS must contain valid pairs such as BTCUSDT.")
    raw_arbitrage_symbols = os.getenv("DOMINION_ARBITRAGE_SYMBOLS", "").strip()
    universe_feed = BinanceMarketUniverse(timeout=8.0)
    universe_error = None
    if raw_arbitrage_symbols:
        arbitrage_symbols = tuple(
            item.strip().upper().replace("/", "")
            for item in raw_arbitrage_symbols.split(",")
            if item.strip()
        )
        universe_status = "USER_CONFIGURED"
        universe_source = "DOMINION_ARBITRAGE_SYMBOLS"
    else:
        try:
            min_quote_volume = _positive_float("DOMINION_ARBITRAGE_MIN_QUOTE_VOLUME", 1_000_000.0)
            arbitrage_symbols = universe_feed.top_usdt_symbols(limit=52, min_quote_volume=min_quote_volume)
            if not arbitrage_symbols:
                raise RuntimeError("Binance returned no eligible liquid USDT markets.")
            universe_status = "DYNAMIC_TOP_52" if len(arbitrage_symbols) == 52 else "DYNAMIC_UNDER_52"
            universe_source = "BINANCE_24H_QUOTE_VOLUME"
        except Exception as exc:
            arbitrage_symbols = ("BTCUSDT",)
            universe_status = "FALLBACK_SINGLE_SYMBOL"
            universe_source = "STATIC_SAFETY_FALLBACK"
            universe_error = type(exc).__name__
    if not arbitrage_symbols or len(arbitrage_symbols) > 100 or any(not item.isalnum() for item in arbitrage_symbols):
        raise RuntimeError("DOMINION_ARBITRAGE_SYMBOLS must contain 1–100 valid pairs such as BTCUSDT.")
    interval = _positive_float("DOMINION_CRYPTO_INTERVAL_SECONDS", 1.0)
    if interval < 1.0:
        raise RuntimeError("Polling interval cannot be below one second.")
    log_path = Path(data_dir) / "crypto_decisions.jsonl"
    fees = _fee_config()
    feeds = PublicCryptoFeeds(timeout=5.0)
    paper_desk = PaperTradingDesk(
        starting_equity=20.0,
        journal=Path(data_dir) / "paper_trades.jsonl",
    )
    monitor = CryptoPaperMonitor(
        feeds,
        decision_log=log_path,
        costs_by_exchange=fees,
        interval_seconds=interval,
        max_quote_age_seconds=2.0,
        min_net_edge_bps=10.0,
        max_notional=paper_desk.starting_equity * 0.40,
    )
    candle_feed = BinancePublicCandleFeed(timeout=8.0)
    strategy_profile = os.getenv("DOMINION_CRYPTO_STRATEGY_PROFILE", "intraday").strip().lower()
    score_threshold = int(os.getenv("DOMINION_STRATEGY_SCORE_THRESHOLD", "6"))
    confluence_strategy = ConfluencePaperStrategy(
        profile=strategy_profile,
        score_threshold=score_threshold,
        max_notional_fraction=0.40,
    )
    state = {
        "engine": "starting",
        "mode": "PAPER_ONLY",
        "orders_enabled": False,
        "symbols": list(symbols),
        "arbitrage_symbols": list(arbitrage_symbols),
        "arbitrage_universe": {
            "status": universe_status, "source": universe_source,
            "target_count": 52, "actual_count": len(arbitrage_symbols),
            "last_refreshed_at": datetime.now(timezone.utc).isoformat(),
            "error": universe_error,
        },
        "exchanges": ["Binance", "Bitget", "HTX", "OKX"],
        "poll_interval_seconds": interval,
        "market_data_mode": "PUBLIC_REST_SNAPSHOT_LOCAL_RECEIPT_TIME",
        "market_data_note": "Dynamic top-52 liquid USDT cross-exchange scan uses one batched REST snapshot per venue; one-second polling is a target, not a guaranteed execution time.",
        "fee_configuration": "complete" if len(fees) == 4 else "missing",
        "arbitrage_scanner": {
            "status": "STARTING", "symbol": arbitrage_symbols[0],
            "symbols_scanned": len(arbitrage_symbols),
            "mode": "PAPER_ONLY", "orders_enabled": False,
            "detail": f"Waiting for one batched public quote snapshot per venue across {len(arbitrage_symbols)} symbols and verified fee settings.",
        },
        "last_cycle_at": None,
        "last_error": None,
        "strategy_engine": {"status": "STARTING", "strategy": "MTF_CONFLUENCE", "profile": strategy_profile, "score_threshold": score_threshold, "detail": "Waiting for completed execution/context candles and a fresh Binance quote."},
        "agents": {
            "SCANNER": {"status": "RUNNING", "detail": "Public crypto price-gap scanner runs with the phone monitor."},
            "RISK": {"status": "PAPER_READY", "detail": "Paper execution gate enforces 0.5% maximum risk per trade, 2% daily loss stop, one open position, quote age, spread and slippage limits."},
            "SNIPER": {"status": "READY_FOR_VALIDATED_SIGNALS", "detail": "Risk-gated paper entry lifecycle is available. No directional strategy signal source or real order route is connected."},
            "WHALE": {"status": "WAITING_FOR_FEED", "detail": "Large-trade analysis is implemented; a trade-flow feed is not connected."},
            "RUG": {"status": "WAITING_FOR_EVIDENCE", "detail": "Token safety checklist is implemented; on-chain contract/liquidity evidence is not connected."},
            "EXIT": {"status": "PAPER_BOOK_EMPTY", "detail": "Paper position book is connected to stop-loss, take-profit and trailing-stop management; waiting for a validated paper entry."},
            "HYPE": {"status": "WAITING_FOR_FEED", "detail": "Text sentiment analysis is implemented; social/news collection is not connected."},
            "DESK MANAGER": {"status": "COORDINATOR_READY", "detail": "Specialist coordination component is implemented; full live workflow is not enabled."},
        },
    }
    stop_event = threading.Event()
    discovery_feed = DexScreenerDiscovery(timeout=8.0)
    whale_feed = GeckoTerminalWhaleFeed(timeout=8.0, min_notional_usd=100_000.0)
    security_feed = GoPlusSecurityFeed(token=os.getenv("DOMINION_GOPLUS_TOKEN", "").strip() or None, timeout=8.0)
    news_feed = PublicNewsRSS(timeout=8.0)
    gmgn_client = GMGNReadOnlyClient(gmgn_api_key, timeout=8.0) if gmgn_api_key.strip() else None
    gmgn_last_trenches_refresh = 0.0
    gmgn_last_trending_refresh = 0.0
    gmgn_retry_after = 0.0
    gmgn_security_cursor = 0
    state["gmgn_feed"] = {
        "status": "READY_TO_CONNECT" if gmgn_client else "NOT_CONFIGURED",
        "detail": "Official GMGN read-only API key is stored in Android Keystore." if gmgn_client
            else "Add a GMGN API key from gmgn.ai/ai to enable official token discovery and trending data.",
        "last_checked_at": None,
        "trenches_preview": None,
        "trending_preview": None,
        "tokens": [],
        "security_checks": [],
    }
    state["gmgn_sniper"] = {
        "status": "WAITING_FOR_GMGN_FEED", "candidate_count": 0,
        "blocked_count": 0, "candidates": [], "blocked": [],
        "execution_enabled": False,
    }
    network_map = {"ethereum":"eth", "bsc":"bsc", "base":"base", "solana":"solana", "polygon":"polygon_pos", "arbitrum":"arbitrum", "optimism":"optimism", "avalanche":"avax", "avax":"avax", "fantom":"fantom", "cronos":"cronos"}

    def agent_feed_loop() -> None:
        nonlocal gmgn_last_trenches_refresh, gmgn_last_trending_refresh
        nonlocal gmgn_retry_after, gmgn_security_cursor
        while not stop_event.is_set():
            try:
                discovered = discovery_feed.discover(limit=8)
                prior_gmgn_tokens = state.get("gmgn_feed", {}).get("tokens", [])
                gmgn_token_count = len(prior_gmgn_tokens) if isinstance(prior_gmgn_tokens, list) else 0
                state["agents"]["SCANNER"] = {
                    "status": "CONNECTED" if discovered or gmgn_token_count else "CONNECTED_NO_NEW_TOKENS",
                    "detail": f"DEX Screener enriched {len(discovered)} recent pools; official GMGN Trenches supplied {gmgn_token_count} parsed Solana tokens. The independent dynamic top-52 cross-exchange REST scan targets a one-second cycle."
                }
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
                supported_candidates = [
                    token for token in discovered
                    if GoPlusSecurityFeed.supports_contract(token.get("chain_id", ""), token.get("token_address", ""))
                ]
                unsupported_count = len(discovered) - len(supported_candidates)
                # Do not let unsupported networks at the top hide supported EVM tokens later in the feed.
                for token in supported_candidates[:5]:
                    try:
                        result = security_feed.assess(token["chain_id"], token["token_address"])
                        result.update({"symbol": token.get("symbol"), "chain": token.get("chain_id"),
                                       "token_address": token.get("token_address")})
                        security_results.append(result)
                    except Exception as exc:
                        security_results.append({"status":"FEED_ERROR", "error":type(exc).__name__,
                                                 "symbol":token.get("symbol"), "chain":token.get("chain_id")})
                gmgn_security_results = []
                gmgn_security_errors = 0
                gmgn_now = time.monotonic()
                gmgn_trenches_due = gmgn_client is not None and gmgn_now - gmgn_last_trenches_refresh >= 300
                gmgn_trending_due = gmgn_client is not None and gmgn_now - gmgn_last_trending_refresh >= 300
                gmgn_market_refresh_due = gmgn_trenches_due or gmgn_trending_due
                gmgn_rate_limited = gmgn_now < gmgn_retry_after
                if gmgn_client is not None and not gmgn_market_refresh_due and not gmgn_rate_limited:
                    gmgn_chain_map = {
                        "solana": "sol", "ethereum": "eth", "bsc": "bsc",
                        "base": "base", "arbitrum": "arbitrum", "avalanche": "avalanche",
                    }
                    previous_gmgn_tokens = state.get("gmgn_feed", {}).get("tokens", [])
                    security_candidates = list(discovered)
                    if isinstance(previous_gmgn_tokens, list):
                        security_candidates.extend(previous_gmgn_tokens)
                    unique_candidates = []
                    seen_security_addresses = set()
                    for token in security_candidates:
                        gmgn_chain = str(token.get("chain") or "").lower() or gmgn_chain_map.get(str(token.get("chain_id", "")).lower())
                        address = str(token.get("token_address", "")).strip()
                        if not gmgn_chain or not address or address in seen_security_addresses:
                            continue
                        seen_security_addresses.add(address)
                        unique_candidates.append((token, gmgn_chain, address))
                    if unique_candidates:
                        batch_size = min(4, len(unique_candidates))
                        for offset in range(batch_size):
                            token, gmgn_chain, address = unique_candidates[
                                (gmgn_security_cursor + offset) % len(unique_candidates)
                            ]
                            try:
                                evidence = gmgn_client.token_security(gmgn_chain, address)
                                assessment = summarize_security_evidence(evidence, gmgn_chain)
                                gmgn_security_results.append({
                                    "symbol": token.get("symbol"), "chain": gmgn_chain,
                                    "token_address": address, "assessment": assessment,
                                    "checked_at": datetime.now(timezone.utc).isoformat(),
                                })
                            except Exception as exc:
                                gmgn_security_errors += 1
                                gmgn_security_results.append({
                                    "symbol": token.get("symbol"), "chain": gmgn_chain,
                                    "status": "GMGN_SECURITY_ERROR", "error": type(exc).__name__,
                                })
                        gmgn_security_cursor = (gmgn_security_cursor + batch_size) % len(unique_candidates)
                previous_security_checks = state.get("gmgn_feed", {}).get("security_checks", [])
                security_by_address = {
                    str(item.get("token_address", "")).lower(): item
                    for item in previous_security_checks
                    if isinstance(item, dict) and item.get("token_address")
                } if isinstance(previous_security_checks, list) else {}
                for item in gmgn_security_results:
                    if item.get("assessment") and item.get("token_address"):
                        security_by_address[str(item["token_address"]).lower()] = item
                gmgn_security_checks = list(security_by_address.values())[-50:]
                gmgn_tokens_for_sniper = state.get("gmgn_feed", {}).get("tokens", [])
                state["gmgn_sniper"] = GMGNSniperAgent().rank(
                    gmgn_tokens_for_sniper if isinstance(gmgn_tokens_for_sniper, list) else [],
                    gmgn_security_checks,
                )
                risk_count = sum(item.get("status") == "RISK_FLAGS_FOUND" for item in security_results)
                error_count = sum(item.get("status") == "FEED_ERROR" for item in security_results)
                checked_count = sum(item.get("status") not in {"FEED_ERROR", "UNSUPPORTED_CHAIN", "INVALID_CONTRACT_ADDRESS"} for item in security_results)
                gmgn_security_success_count = sum("assessment" in item for item in gmgn_security_checks)
                gmgn_security_flag_count = sum(
                    len(item.get("assessment", {}).get("risk_flags", []))
                    for item in gmgn_security_checks
                )
                gmgn_security_unknown_count = sum(
                    item.get("assessment", {}).get("status") == "INSUFFICIENT_EVIDENCE"
                    for item in gmgn_security_checks
                )
                total_security_checks = checked_count + gmgn_security_success_count
                total_security_errors = error_count + gmgn_security_errors
                gmgn_tokens_for_rug = state.get("gmgn_feed", {}).get("tokens", [])
                gmgn_token_count_for_rug = len(gmgn_tokens_for_rug) if isinstance(gmgn_tokens_for_rug, list) else 0
                total_discovered_for_rug = len(discovered) + gmgn_token_count_for_rug
                if total_discovered_for_rug == 0:
                    rug_status = "WAITING_FOR_TOKENS"
                elif total_security_checks == 0 and not supported_candidates and gmgn_token_count_for_rug == 0:
                    rug_status = "UNSUPPORTED_TOKENS"
                elif total_security_checks == 0:
                    rug_status = "WAITING_FOR_SECURITY_CHECKS"
                elif (total_security_errors or gmgn_security_unknown_count) and total_security_checks:
                    rug_status = "PARTIAL"
                elif total_security_errors:
                    rug_status = "FEED_ERROR"
                else:
                    rug_status = "CONNECTED"
                state["agents"]["RUG"] = {
                    "status": rug_status,
                    "detail": (f"DEX Screener discovered {len(discovered)} tokens and GMGN has {gmgn_token_count_for_rug} Trenches tokens: {len(supported_candidates)} DEX tokens have a supported EVM chain and valid contract address; "
                               f"{unsupported_count} are unsupported or have invalid addresses. GoPlus checked {checked_count}/"
                               f"{min(len(supported_candidates), 5)}; {risk_count} returned explicit risk flags and {error_count} requests failed. "
                               f"GMGN returned {gmgn_security_success_count}/"
                               f"{len(gmgn_security_results)} security responses, with {gmgn_security_flag_count} explicit risk flags and "
                               f"{gmgn_security_unknown_count} insufficient-evidence assessments. "
                               "No result is a safety guarantee; missing fields remain unknown."),
                    "checked_tokens": security_results[:5],
                    "gmgn_security_checks": gmgn_security_checks[:5],
                    "risk_flags": [item for item in security_results if item.get("risks")][:5],
                    "gmgn_risk_flags": [
                        {"symbol": item.get("symbol"), "chain": item.get("chain"),
                         "risk_flags": item.get("assessment", {}).get("risk_flags", [])}
                        for item in gmgn_security_checks
                        if item.get("assessment", {}).get("risk_flags")
                    ][:5],
                    "unsupported_tokens": unsupported_count,
                    "errors": error_count,
                }
                if gmgn_client is not None:
                    if gmgn_rate_limited:
                        state["gmgn_feed"]["status"] = "RATE_LIMITED"
                        state["gmgn_feed"]["detail"] = "GMGN requests are paused during the rate-limit cooldown; no retries are sent during this window."
                    elif gmgn_market_refresh_due:
                        try:
                            previous_feed = state.get("gmgn_feed", {})
                            trenches = gmgn_client.trenches("sol", limit=30) if gmgn_trenches_due else None
                            trending = gmgn_client.trending("sol", "1h", limit=20) if gmgn_trending_due else None
                            gmgn_tokens = extract_trenches_tokens(trenches, "sol", limit=30) if trenches is not None else previous_feed.get("tokens", [])
                            if gmgn_trenches_due:
                                gmgn_last_trenches_refresh = time.monotonic()
                            if gmgn_trending_due:
                                gmgn_last_trending_refresh = time.monotonic()
                            state["gmgn_feed"] = {
                                "status": "CONNECTED",
                                "detail": "Official GMGN read-only feed is active. Trenches and trending refresh every five minutes; token-security checks are staggered between refreshes to respect the Free-plan rate budget.",
                                "last_checked_at": datetime.now(timezone.utc).isoformat(),
                                "trenches_preview": __import__("json").dumps(trenches, ensure_ascii=False)[:5000] if trenches is not None else previous_feed.get("trenches_preview"),
                                "trending_preview": __import__("json").dumps(trending, ensure_ascii=False)[:5000] if trending is not None else previous_feed.get("trending_preview"),
                                "security_preview": __import__("json").dumps(gmgn_security_results, ensure_ascii=False)[:5000] if gmgn_security_results else previous_feed.get("security_preview"),
                                "security_errors": gmgn_security_errors,
                                "tokens": gmgn_tokens,
                                "security_checks": gmgn_security_checks,
                            }
                        except Exception as exc:
                            error_text = str(exc)
                            if "PLAN_UPGRADE_REQUIRED" in error_text:
                                gmgn_retry_after = float("inf")
                                error_status = "PLAN_UPGRADE_REQUIRED"
                            elif "429" in error_text or "RATE_LIMIT" in error_text:
                                cooldown_seconds = 300.0
                                if "RESET_AT:" in error_text:
                                    try:
                                        reset_text = error_text.split("RESET_AT:", 1)[1].split(":", 1)[0]
                                        cooldown_seconds = max(1.0, min(300.0, float(reset_text) - time.time()))
                                    except (TypeError, ValueError):
                                        cooldown_seconds = 300.0
                                gmgn_retry_after = time.monotonic() + cooldown_seconds
                                error_status = "RATE_LIMITED"
                            else:
                                gmgn_retry_after = time.monotonic() + 300
                                error_status = "API_ERROR"
                            previous_feed = state.get("gmgn_feed", {})
                            state["gmgn_feed"] = {
                                **previous_feed,
                                "status": error_status,
                                "detail": "GMGN requests are paused for five minutes after an API error to avoid repeated requests or extending a rate-limit ban.",
                                "last_checked_at": datetime.now(timezone.utc).isoformat(),
                                "error": error_text[:120],
                                "security_errors": gmgn_security_errors,
                            }
                    elif gmgn_security_results:
                        state["gmgn_feed"]["status"] = "CONNECTED"
                        state["gmgn_feed"]["last_checked_at"] = datetime.now(timezone.utc).isoformat()
                        state["gmgn_feed"]["security_preview"] = __import__("json").dumps(gmgn_security_checks, ensure_ascii=False)[:5000]
                        state["gmgn_feed"]["security_errors"] = gmgn_security_errors
                        state["gmgn_feed"]["security_checks"] = gmgn_security_checks
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
            snapshot = dict(state)
            snapshot["paper_trading"] = paper_desk.snapshot()
            snapshot["integration_readiness"] = build_readiness(
                phone_engine_running=state.get("engine") == "running",
                verified_fee_exchanges=tuple(fees.keys()),
                gmgn_read_only_status=str(state.get("gmgn_feed", {}).get("status", "NOT_CONFIGURED")),
            )
            return snapshot

    def monitor_loop() -> None:
        state["engine"] = "running"
        active_symbols = tuple(arbitrage_symbols)
        last_universe_refresh = datetime.now(timezone.utc)
        while not stop_event.is_set():
            cycle_started = datetime.now(timezone.utc)
            if not raw_arbitrage_symbols and (cycle_started - last_universe_refresh).total_seconds() >= 3600:
                try:
                    refreshed = universe_feed.top_usdt_symbols(
                        limit=52,
                        min_quote_volume=_positive_float("DOMINION_ARBITRAGE_MIN_QUOTE_VOLUME", 1_000_000.0),
                    )
                    if refreshed:
                        active_symbols = refreshed
                        state["arbitrage_symbols"] = list(active_symbols)
                        state["arbitrage_universe"] = {
                            "status": "DYNAMIC_TOP_52" if len(active_symbols) == 52 else "DYNAMIC_UNDER_52",
                            "source": "BINANCE_24H_QUOTE_VOLUME",
                            "target_count": 52,
                            "actual_count": len(active_symbols),
                            "last_refreshed_at": cycle_started.isoformat(),
                            "error": None,
                        }
                    last_universe_refresh = cycle_started
                except Exception as exc:
                    state["arbitrage_universe"]["error"] = type(exc).__name__
                    state["arbitrage_universe"]["status"] = "REFRESH_FAILED_USING_LAST_UNIVERSE"
            try:
                scan = monitor.poll_many_once(active_symbols)
                state["arbitrage_scanner"] = {
                    "status": scan.get("status", "UNKNOWN"),
                    "reason": scan.get("reason"),
                    "symbol": "MULTI_MARKET",
                    "symbols_scanned": scan.get("symbols_requested", len(active_symbols)),
                    "symbols_with_quotes": scan.get("symbols_with_quotes", 0),
                    "symbols_with_two_venues": scan.get("symbols_with_two_venues", 0),
                    "quote_count": scan.get("quote_count", 0),
                    "quotes_by_exchange": scan.get("quotes_by_exchange", {}),
                    "opportunities": scan.get("opportunities", []),
                    "opportunities_count": scan.get("opportunities_count", 0),
                    "available_exchanges": scan.get("available_exchanges", []),
                    "venue_errors": scan.get("venue_errors", {}),
                    "collection_duration_ms": scan.get("collection_duration_ms"),
                    "last_cycle_at": scan.get("recorded_at"),
                    "mode": "PAPER_ONLY",
                    "orders_enabled": False,
                }
                state["last_error"] = None
            except Exception as exc:
                state["last_error"] = type(exc).__name__
            state["last_cycle_at"] = cycle_started.isoformat()
            stop_event.wait(interval)
        state["engine"] = "stopped"

    def strategy_loop() -> None:
        while not stop_event.is_set():
            for symbol in symbols:
                if stop_event.is_set():
                    break
                try:
                    execution_tf, context_tf = TIMEFRAME_PROFILES[strategy_profile]
                    execution_candles = candle_feed.candles(symbol, timeframe=execution_tf, limit=220)
                    context_candles = candle_feed.candles(symbol, timeframe=context_tf, limit=220)
                    quote = feeds.binance(symbol)
                    result = confluence_strategy.run_once(
                        execution_candles, context_candles, quote, paper_desk,
                        now=datetime.now(timezone.utc),
                    )
                    event = result.get("event", result.get("status", "UNKNOWN"))
                    state["strategy_engine"] = {
                        "status": str(event), "strategy": "MTF_CONFLUENCE",
                        "profile": strategy_profile, "symbol": symbol,
                        "score": result.get("score"),
                        "score_threshold": result.get("score_threshold", score_threshold),
                        "execution_timeframe": result.get("execution_timeframe", execution_tf),
                        "context_timeframe": result.get("context_timeframe", context_tf),
                        "detail": str(result.get("reason") or result.get("signal_reason") or event),
                        "last_cycle_at": datetime.now(timezone.utc).isoformat(),
                    }
                    if event == "PAPER_ENTRY":
                        side = result.get("position", {}).get("side", "")
                        state["agents"]["RISK"] = {"status": "APPROVED_PAPER", "detail": "Signal passed the 0.5% risk cap, daily stop, spread, slippage and quote-age checks."}
                        state["agents"]["SNIPER"] = {"status": "PAPER_ENTRY", "detail": f"Opened a paper-only {side} position in {symbol}; no broker order was sent."}
                        state["agents"]["EXIT"] = {"status": "MANAGING_PAPER_POSITION", "detail": "Monitoring the paper position for stop-loss, take-profit and trailing-stop conditions."}
                    elif event == "PAPER_EXIT":
                        state["agents"]["EXIT"] = {"status": "PAPER_POSITION_CLOSED", "detail": f"Paper position closed: {result.get('exit_reason')}; realized P/L {result.get('realized_pnl')}."}
                        state["agents"]["SNIPER"] = {"status": "PAPER_CLOSED", "detail": "Paper position has been closed; no real order was sent."}
                        state["agents"]["RISK"] = {"status": "PAPER_READY", "detail": "Risk gate is ready for the next validated signal; daily loss and position limits remain active."}
                    elif event == "ENTRY_BLOCKED":
                        reasons = result.get("reasons", [str(result.get("reason", "risk gate"))])
                        state["agents"]["RISK"] = {"status": "BLOCKED", "detail": "Paper entry rejected: " + ", ".join(reasons)}
                        state["agents"]["SNIPER"] = {"status": "ENTRY_BLOCKED", "detail": "No paper position was opened because a validation gate rejected the candidate."}
                    elif event == "NO_SIGNAL":
                        if paper_desk.position is None:
                            state["agents"]["EXIT"] = {"status": "PAPER_BOOK_EMPTY", "detail": "No open paper position; waiting for a validated strategy entry."}
                            state["agents"]["RISK"] = {"status": "PAPER_READY", "detail": "0.5% trade-risk and 2% daily-loss checks are active; waiting for a strategy candidate."}
                            state["agents"]["SNIPER"] = {"status": "WAITING_FOR_SIGNAL", "detail": "No entry signal passed to the paper execution desk in this cycle."}
                except Exception as exc:
                    state["strategy_engine"] = {"status": "FEED_ERROR", "strategy": "MTF_CONFLUENCE", "profile": strategy_profile, "symbol": symbol, "detail": type(exc).__name__, "last_cycle_at": datetime.now(timezone.utc).isoformat()}
            stop_event.wait(60.0)
    api_port = port if port is not None else int(os.getenv("DOMINION_CRYPTO_API_PORT", "8766"))
    server = create_server(str(log_path), status_provider=status_provider,
                           host="127.0.0.1", port=api_port)
    return stop_event, server, monitor_loop, agent_feed_loop, strategy_loop, state, symbols, arbitrage_symbols, interval


def start_embedded(data_dir: str, port: int = 8766, gmgn_api_key: str = "") -> dict:
    """Start the Python engine for the Android foreground service; return immediately."""
    global _runtime_stop, _runtime_server, _runtime_threads, _runtime_state
    with _runtime_lock:
        if _runtime_stop is not None and not _runtime_stop.is_set():
            return {"started": True, "already_running": True, "port": _runtime_server.server_address[1]}
        Path(data_dir).mkdir(parents=True, exist_ok=True)
        stop_event, server, monitor_loop, agent_feed_loop, strategy_loop, state, symbols, arbitrage_symbols, interval = _runtime_config(data_dir, port, gmgn_api_key)
        worker = threading.Thread(target=monitor_loop, name="dominion-crypto-paper", daemon=True)
        agent_worker = threading.Thread(target=agent_feed_loop, name="dominion-agent-feeds", daemon=True)
        strategy_worker = threading.Thread(target=strategy_loop, name="dominion-paper-strategy", daemon=True)
        api_thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.5}, daemon=True)
        _runtime_stop, _runtime_server = stop_event, server
        _runtime_threads = [worker, agent_worker, strategy_worker, api_thread]
        _runtime_state = state
        worker.start()
        agent_worker.start()
        strategy_worker.start()
        api_thread.start()
        return {"started": True, "already_running": False,
                "port": server.server_address[1], "symbols": list(symbols),
                "arbitrage_symbols": list(arbitrage_symbols),
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
    print(f"Strategy symbols: {', '.join(result['symbols'])} | BTC/market scan: {', '.join(result['arbitrage_symbols'])} | interval: {result['interval_seconds']}s | orders: disabled")
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
