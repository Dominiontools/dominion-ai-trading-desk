"""Phone-embedded crypto monitor with paper-first, opt-in Binance Spot Testnet routing.

Testnet order routing is disabled by default and requires an explicit Android
setting plus credentials stored in the native Keystore. Live exchange hosts and
wallet signing are not supported by this service.
"""
from __future__ import annotations

import json
import os
import signal
import threading
import time
from math import isfinite
from datetime import datetime, timezone
from pathlib import Path

from engine.crypto_api import create_server
from engine.agent_feeds import DexScreenerDiscovery, GeckoTerminalWhaleFeed, GoPlusSecurityFeed, PublicNewsRSS
from engine.specialist_agents import HypeAgent, WhaleAgent
from engine.crypto_feeds import PublicCryptoFeeds
from engine.crypto_universe import BinanceMarketUniverse
from engine.crypto_monitor import CryptoPaperMonitor
from engine.crypto_fee_policy import load_fee_policy, refresh_public_fee_policy, fee_refresh_interval_seconds
from engine.paper_workflow import PaperTradingDesk
from engine.crypto_strategy import BinancePublicCandleFeed, ConfluencePaperStrategy
from engine.confluence_strategy import TIMEFRAME_PROFILES
from engine.readiness import build_readiness
from engine.binance_testnet import BinanceSpotTestnetClient
from engine.binance_lifecycle import BinanceProtectedLifecycle
from engine.binance_daily_loss import BinanceDailyLossLedger
from engine.binance_risk_context import BinanceRiskContextProvider
from engine.binance_signal_router import BinanceTestnetSignalRouter
from engine.risk_execution import BinanceTestnetRiskGate

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
    """Load conservative public estimates and verified Binance personal overrides."""
    fees, _sources = load_fee_policy()
    return fees


def _runtime_config(
    data_dir: str | Path, port: int | None = None,
    binance_api_key: str = "", binance_api_secret: str = "",
    binance_testnet_orders_enabled: bool = False,
):
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
    fees, fee_sources = load_fee_policy()
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
    testnet_execution_enabled = bool(
        binance_testnet_orders_enabled and binance_api_key and binance_api_secret
    )
    os.environ["DOMINION_ENABLE_BINANCE_TESTNET_ORDERS"] = (
        "YES" if testnet_execution_enabled else "NO"
    )
    testnet_router = None
    testnet_risk_context = None
    if testnet_execution_enabled:
        testnet_client = BinanceSpotTestnetClient(
            binance_api_key, binance_api_secret, allow_orders=True
        )
        daily_loss_ledger = BinanceDailyLossLedger(Path(data_dir) / "binance-daily-loss.jsonl")
        testnet_lifecycle = BinanceProtectedLifecycle(
            BinanceTestnetRiskGate(), testnet_client,
            journal_path=Path(data_dir) / "binance-lifecycle.json",
            daily_loss_ledger=daily_loss_ledger,
        )
        testnet_risk_context = BinanceRiskContextProvider(
            testnet_client, testnet_lifecycle, daily_loss_ledger, quote_asset="USDT"
        )
        testnet_router = BinanceTestnetSignalRouter(
            testnet_client, testnet_lifecycle, BinanceTestnetRiskGate()
        )
    state = {
        "engine": "starting",
        "mode": "BINANCE_SPOT_TESTNET" if testnet_execution_enabled else "PAPER_ONLY",
        "orders_enabled": testnet_execution_enabled,
        "binance_testnet_execution": {
            "enabled": testnet_execution_enabled,
            "status": "ENABLED_TESTNET" if testnet_execution_enabled
                      else "DISABLED_OR_CREDENTIALS_MISSING",
            "orders_enabled": testnet_execution_enabled,
            "halted": False,
            "environment": "BINANCE_SPOT_TESTNET",
        },
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
        "fee_configuration": "complete" if len(fees) == 4 else "partial",
        "fee_policy": {
            "rates_bps": {venue: {"maker": rates[0], "taker": rates[1]} for venue, rates in fees.items()},
            "sources": fee_sources,
            "net_profit_qualification": "BLOCKED_FOR_UNCONFIGURED_VENUES",
            "note": "Public rates are estimates; Binance personal rates override only when explicitly verified.",
        },
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
    network_map = {"ethereum":"eth", "bsc":"bsc", "base":"base", "solana":"solana", "polygon":"polygon_pos", "arbitrum":"arbitrum", "optimism":"optimism", "avalanche":"avax", "avax":"avax", "fantom":"fantom", "cronos":"cronos"}

    def agent_feed_loop() -> None:
        while not stop_event.is_set():
            try:
                discovered = discovery_feed.discover(limit=8)
                state["agents"]["SCANNER"] = {
                    "status": "CONNECTED" if discovered else "CONNECTED_NO_NEW_TOKENS",
                    "detail": f"DEX Screener enriched {len(discovered)} recent pools. The independent dynamic top-52 cross-exchange REST scan targets a one-second cycle."
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
                risk_count = sum(item.get("status") == "RISK_FLAGS_FOUND" for item in security_results)
                error_count = sum(item.get("status") == "FEED_ERROR" for item in security_results)
                checked_count = sum(
                    item.get("status") not in {"FEED_ERROR", "UNSUPPORTED_CHAIN", "INVALID_CONTRACT_ADDRESS"}
                    for item in security_results
                )
                if not discovered:
                    rug_status = "WAITING_FOR_TOKENS"
                elif checked_count == 0 and not supported_candidates:
                    rug_status = "UNSUPPORTED_TOKENS"
                elif error_count and checked_count:
                    rug_status = "PARTIAL"
                elif error_count:
                    rug_status = "FEED_ERROR"
                elif checked_count == 0:
                    rug_status = "WAITING_FOR_SECURITY_CHECKS"
                else:
                    rug_status = "CONNECTED"
                state["agents"]["RUG"] = {
                    "status": rug_status,
                    "detail": (f"DEX Screener discovered {len(discovered)} tokens: {len(supported_candidates)} have a supported EVM chain and valid contract address; "
                               f"{unsupported_count} are unsupported or have invalid addresses. GoPlus checked {checked_count}/"
                               f"{min(len(supported_candidates), 5)}; {risk_count} returned explicit risk flags and {error_count} requests failed. "
                               "No result is a safety guarantee; missing fields remain unknown."),
                    "checked_tokens": security_results[:5],
                    "risk_flags": [item for item in security_results if item.get("risks")][:5],
                    "unsupported_tokens": unsupported_count,
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
            snapshot = dict(state)
            snapshot["paper_trading"] = paper_desk.snapshot()
            scanner = snapshot.get("arbitrage_scanner")
            scanner = scanner if isinstance(scanner, dict) else {}
            available_exchanges = set(scanner.get("available_exchanges", []))
            venue_errors = scanner.get("venue_errors")
            scanner_verified = (
                scanner.get("status") in {"PAPER_OPPORTUNITY", "NO_QUALIFYING_OPPORTUNITY"}
                and scanner.get("symbols_scanned", 0) >= 52
                and len(available_exchanges) == 4
                and not venue_errors
                and not scanner.get("reason") in {
                    "FEE_CONFIG_MISSING", "INSUFFICIENT_INDEPENDENT_MARKET_QUOTES",
                    "BATCH_MARKET_DATA_FETCH_FAILED",
                }
            )
            snapshot["integration_readiness"] = build_readiness(
                phone_engine_running=state.get("engine") == "running",
                verified_fee_exchanges=tuple(fees.keys()),
                cross_exchange_scan_verified=scanner_verified,
            )
            return snapshot

    def monitor_loop() -> None:
        state["engine"] = "running"
        active_symbols = tuple(arbitrage_symbols)
        last_universe_refresh = datetime.now(timezone.utc)
        last_fee_refresh = None
        while not stop_event.is_set():
            cycle_started = datetime.now(timezone.utc)
            if (last_fee_refresh is None or
                    (cycle_started - last_fee_refresh).total_seconds() >= fee_refresh_interval_seconds()):
                try:
                    refreshed_policy = refresh_public_fee_policy()
                    refreshed_fees = refreshed_policy.get("fees", {})
                    if isinstance(refreshed_fees, dict):
                        fees.clear()
                        fees.update(refreshed_fees)
                        if hasattr(monitor, "costs_by_exchange"):
                            monitor.costs_by_exchange.clear()
                            monitor.costs_by_exchange.update(refreshed_fees)
                    with _runtime_lock:
                        state["fee_configuration"] = "complete" if len(fees) == 4 else "partial"
                        state["fee_policy"] = {
                            "rates_bps": {
                                venue: {"maker": rates[0], "taker": rates[1]}
                                for venue, rates in fees.items()
                            },
                            "sources": refreshed_policy.get("sources", fee_sources),
                            "net_profit_qualification": "BLOCKED_FOR_UNCONFIGURED_VENUES",
                            "last_refresh_at": refreshed_policy.get("last_refresh_at"),
                            "next_refresh_in_seconds": refreshed_policy.get("next_refresh_in_seconds"),
                            "note": "Official public schedules refresh every six hours. Binance personal rates override only when authenticated and verified; HTX remains blocked until its public base rate is verifiable.",
                        }
                    last_fee_refresh = cycle_started
                except Exception as exc:
                    state["fee_policy"]["refresh_error"] = type(exc).__name__
                    state["fee_policy"]["refresh_status"] = "FAILED_USING_LAST_KNOWN_RATES"
                    last_fee_refresh = cycle_started
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
                    "symbols_with_any_quotes": scan.get("symbols_with_any_quotes", scan.get("symbols_with_quotes", 0)),
                    "symbols_with_quotes": scan.get("symbols_with_quotes", 0),
                    "symbols_with_two_venues": scan.get("symbols_with_two_venues", 0),
                    "quote_count": scan.get("quote_count", 0),
                    "fresh_quote_count": scan.get("fresh_quote_count", 0),
                    "fresh_exchanges": scan.get("fresh_exchanges", []),
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
                event = "FEED_ERROR"
                try:
                    execution_tf, context_tf = TIMEFRAME_PROFILES[strategy_profile]
                    execution_candles = candle_feed.candles(symbol, timeframe=execution_tf, limit=220)
                    context_candles = candle_feed.candles(symbol, timeframe=context_tf, limit=220)
                    quote = feeds.binance(symbol)
                    cycle_now = datetime.now(timezone.utc)
                    if testnet_execution_enabled and testnet_router is not None and testnet_risk_context is not None:
                        if paper_desk.position is not None:
                            result = {
                                "event": "TESTNET_BLOCKED",
                                "reason": "PAPER_POSITION_OPEN",
                                "mode": "BINANCE_SPOT_TESTNET",
                                "orders_enabled": False,
                            }
                        else:
                            result = confluence_strategy.run_testnet_once(
                                execution_candles, context_candles, quote,
                                router=testnet_router,
                                risk_context_provider=testnet_risk_context,
                                now=cycle_now,
                            )
                    else:
                        result = confluence_strategy.run_once(
                            execution_candles, context_candles, quote, paper_desk,
                            now=cycle_now,
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
                    if event == "TESTNET_ORDER":
                        state["binance_testnet_execution"]["status"] = "PROTECTED_POSITION_OPEN"
                        state["agents"]["RISK"] = {"status": "APPROVED_TESTNET", "detail": "Binance Testnet order passed the verified 0.5% risk cap, daily-loss ledger, account balance, symbol filters and fee checks."}
                        state["agents"]["SNIPER"] = {"status": "TESTNET_ORDER_PROTECTED", "detail": f"Binance Spot Testnet BUY order for {symbol} was confirmed with exchange-held stop-loss and take-profit legs."}
                        state["agents"]["EXIT"] = {"status": "EXCHANGE_PROTECTED_TESTNET_POSITION", "detail": "Binance holds the protective stop-loss and take-profit orders; restart reconciliation checks their state before another entry."}
                    elif event == "TESTNET_POSITION_OPEN":
                        state["binance_testnet_execution"]["status"] = "PROTECTED_POSITION_OPEN"
                        state["agents"]["RISK"] = {"status": "POSITION_LIMIT_ACTIVE", "detail": "An existing or unmanaged Spot holding is present; no additional Testnet entry is permitted."}
                        state["agents"]["SNIPER"] = {"status": "WAITING_FOR_EXIT", "detail": "The one-position rule blocks new entries while the current holding remains open."}
                        state["agents"]["EXIT"] = {"status": "EXCHANGE_PROTECTED_TESTNET_POSITION", "detail": "Existing exchange-held protection remains responsible for the open Testnet position."}
                    elif event == "TESTNET_BLOCKED":
                        if result.get("halted") is True:
                            state["binance_testnet_execution"]["status"] = "HALTED_REQUIRES_REVIEW"
                            state["binance_testnet_execution"]["halted"] = True
                            state["binance_testnet_execution"]["orders_enabled"] = False
                            state["orders_enabled"] = False
                        else:
                            state["binance_testnet_execution"]["status"] = "ENTRY_BLOCKED"
                        state["agents"]["RISK"] = {"status": "BLOCKED", "detail": f"Testnet entry blocked: {result.get('reason', 'risk or protection gate')}."}
                        state["agents"]["SNIPER"] = {"status": "TESTNET_ENTRY_BLOCKED", "detail": "No new Testnet order was accepted by the execution gates."}
                    elif event == "PAPER_ENTRY":
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
                if (testnet_execution_enabled and event == "TESTNET_BLOCKED"
                        and result.get("reason") == "UNSUPPORTED_SPOT_SIDE_OR_MARKET"):
                    continue
                if testnet_execution_enabled and event in {"TESTNET_ORDER", "TESTNET_POSITION_OPEN", "TESTNET_BLOCKED"}:
                    break
            stop_event.wait(60.0)
    api_port = port if port is not None else int(os.getenv("DOMINION_CRYPTO_API_PORT", "8766"))
    server = create_server(str(log_path), status_provider=status_provider,
                           host="127.0.0.1", port=api_port)
    return stop_event, server, monitor_loop, agent_feed_loop, strategy_loop, state, symbols, arbitrage_symbols, interval


def start_embedded(
    data_dir: str, port: int = 8766,
    binance_recovery_json: str = "", binance_api_key: str = "",
    binance_api_secret: str = "", binance_testnet_orders_enabled: bool = False,
) -> dict:
    """Start the Python engine for the Android foreground service; return immediately."""
    global _runtime_stop, _runtime_server, _runtime_threads, _runtime_state
    with _runtime_lock:
        if _runtime_stop is not None and not _runtime_stop.is_set():
            return {"started": True, "already_running": True, "port": _runtime_server.server_address[1]}
        Path(data_dir).mkdir(parents=True, exist_ok=True)
        try:
            stop_event, server, monitor_loop, agent_feed_loop, strategy_loop, state, symbols, arbitrage_symbols, interval = _runtime_config(
                data_dir, port, binance_api_key,
                binance_api_secret, binance_testnet_orders_enabled,
            )
        except Exception:
            os.environ["DOMINION_ENABLE_BINANCE_TESTNET_ORDERS"] = "NO"
            raise
        try:
            recovery = json.loads(binance_recovery_json) if binance_recovery_json else {}
            if not isinstance(recovery, dict):
                raise ValueError("Recovery status must be an object.")
            state["binance_testnet_recovery"] = {
                "status": str(recovery.get("status", "NOT_RUN"))[:48],
                "halted": bool(recovery.get("halted", True)),
                "reconciled": int(recovery.get("reconciled", 0) or 0),
                "unresolved_count": len(recovery.get("unresolved", []))
                    if isinstance(recovery.get("unresolved", []), list) else 1,
                "operator_action_required": bool(recovery.get("operator_action_required", False)),
                "orders_enabled": False,
                "environment": "BINANCE_SPOT_TESTNET",
            }
            if state["binance_testnet_execution"]["enabled"] and recovery.get("halted") is True:
                state["binance_testnet_execution"]["status"] = "HALTED_REQUIRES_REVIEW"
                state["binance_testnet_execution"]["halted"] = True
                state["binance_testnet_execution"]["orders_enabled"] = False
                state["orders_enabled"] = False
            risk_context = recovery.get("risk_context", {})
            if isinstance(risk_context, dict):
                state["binance_testnet_risk_context"] = {
                    "verified": risk_context.get("verified") is True,
                    "status": str(risk_context.get("status", "NOT_AVAILABLE"))[:32],
                    "quote_asset": str(risk_context.get("quote_asset", "USDT"))[:12],
                    "equity_quote": str(risk_context.get("equity_quote", "0"))[:32],
                    "available_quote": str(risk_context.get("available_quote", "0"))[:32],
                    "actual_equity_quote": str(risk_context.get("actual_equity_quote", risk_context.get("equity_quote", "0")))[:32],
                    "risk_capital_cap_quote": str(risk_context.get("risk_capital_cap_quote", "20"))[:32],
                    "daily_loss_quote": str(risk_context.get("daily_loss_quote", "0"))[:32],
                    "open_positions": max(0, min(100, int(risk_context.get("open_positions", 0) or 0))),
                    "exchange_open_orders": max(0, min(100, int(risk_context.get("exchange_open_orders", 0) or 0))),
                    "journaled_order_lists": max(0, min(100, int(risk_context.get("journaled_order_lists", 0) or 0))),
                    "orders_enabled": False,
                    "environment": "BINANCE_SPOT_TESTNET",
                }
            else:
                state["binance_testnet_risk_context"] = {
                    "verified": False, "status": "INVALID",
                    "quote_asset": "USDT", "orders_enabled": False,
                    "environment": "BINANCE_SPOT_TESTNET",
                }
        except (TypeError, ValueError, json.JSONDecodeError):
            state["binance_testnet_recovery"] = {
                "status": "RECOVERY_STATUS_INVALID", "halted": True,
                "reconciled": 0, "unresolved_count": 1,
                "operator_action_required": True, "orders_enabled": False,
                "environment": "BINANCE_SPOT_TESTNET",
            }
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
                "interval_seconds": interval, "orders_enabled": state["orders_enabled"],
                "mode": state["mode"]}


def stop_embedded() -> dict:
    """Stop the embedded monitor and local API safely."""
    global _runtime_stop, _runtime_server, _runtime_threads, _runtime_state
    with _runtime_lock:
        stop_event, server, threads = _runtime_stop, _runtime_server, list(_runtime_threads)
        if stop_event is None:
            os.environ["DOMINION_ENABLE_BINANCE_TESTNET_ORDERS"] = "NO"
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
        os.environ["DOMINION_ENABLE_BINANCE_TESTNET_ORDERS"] = "NO"
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
