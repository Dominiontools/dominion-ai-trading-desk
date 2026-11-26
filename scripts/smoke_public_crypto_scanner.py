"""Read-only live smoke check for the 52-market public crypto scanner.

No credentials, private endpoints, order methods, or wallet access are used.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.crypto_fee_policy import refresh_public_fee_policy
from engine.crypto_feeds import PublicCryptoFeeds
from engine.crypto_monitor import CryptoPaperMonitor
from engine.crypto_universe import BinanceMarketUniverse


def main() -> int:
    universe = BinanceMarketUniverse(timeout=8.0)
    symbols = universe.top_usdt_symbols(limit=52, min_quote_volume=1_000_000.0)
    if len(symbols) < 2:
        print(json.dumps({
            "status": "BLOCKED",
            "reason": "BINANCE_PUBLIC_UNIVERSE_RETURNED_TOO_FEW_MARKETS",
            "symbols_scanned": len(symbols),
        }, sort_keys=True))
        return 1

    fee_policy = refresh_public_fee_policy()
    fees = fee_policy.get("fees", {})
    feeds = PublicCryptoFeeds(timeout=5.0, retries=0)
    with tempfile.TemporaryDirectory(prefix="dominion-public-smoke-") as temp_dir:
        monitor = CryptoPaperMonitor(
            feeds,
            decision_log=Path(temp_dir) / "scanner-smoke.jsonl",
            costs_by_exchange=fees,
            interval_seconds=1.0,
            max_quote_age_seconds=2.0,
            min_net_edge_bps=10.0,
            max_notional=8.0,
        )
        result = monitor.poll_many_once(symbols)

    summary = {
        "status": result.get("status"),
        "reason": result.get("reason"),
        "symbols_scanned": result.get("symbols_requested", len(symbols)),
        "symbols_with_two_venues": result.get("symbols_with_two_venues", 0),
        "fresh_quote_count": result.get("fresh_quote_count", 0),
        "fresh_exchanges": result.get("fresh_exchanges", []),
        "fee_verified_exchanges": sorted(fees),
        "missing_fee_exchanges": result.get("missing_fee_exchanges", []),
        "venue_errors": result.get("venue_errors", {}),
        "collection_duration_ms": result.get("collection_duration_ms"),
        "opportunities_count": result.get("opportunities_count", 0),
        "fee_refresh_status": {
            venue: {
                "status": meta.get("refresh_status"),
                "error": meta.get("last_error"),
                "detail": meta.get("last_error_detail"),
            }
            for venue, meta in fee_policy.get("sources", {}).items()
        },
        "orders_enabled": False,
    }
    print(json.dumps(summary, sort_keys=True))

    acceptable = {
        "PAPER_OPPORTUNITY",
        "NO_QUALIFYING_OPPORTUNITY",
        "PARTIAL_FEE_COVERAGE_PAPER_OPPORTUNITY",
        "PARTIAL_FEE_COVERAGE_NO_QUALIFYING_OPPORTUNITY",
        "PARTIAL_FEED_PAPER_OPPORTUNITY",
        "PARTIAL_FEED_NO_QUALIFYING_OPPORTUNITY",
    }
    return 0 if summary["status"] in acceptable else 1


if __name__ == "__main__":
    raise SystemExit(main())
