"""Exchange fee policy for conservative, paper-only cross-exchange estimates.

Published base rates are estimates, not claims about a user's personal account tier.
Binance personal rates override the public fallback only when explicitly marked verified.
"""
from __future__ import annotations

import os
from math import isfinite

# Basis points. Scanner uses the taker component conservatively on both legs.
PUBLIC_SPOT_FEES_BPS: dict[str, tuple[float, float]] = {
    "Binance": (10.0, 10.0),
    "Bitget": (10.0, 10.0),
    # OKX Regular / Standard fee-group public schedule.
    "OKX": (8.0, 10.0),
}
PUBLIC_FEE_SOURCES = {
    "Binance": "PUBLIC_STANDARD_SPOT",
    "Bitget": "PUBLIC_STANDARD_SPOT",
    "OKX": "PUBLIC_REGULAR_STANDARD_SPOT",
    # HTX's official fee page requires account login to expose applicable rates.
    "HTX": "PUBLIC_RATE_NOT_VERIFIABLE",
}


def _read_bps(env_name: str) -> float | None:
    raw = os.getenv(env_name, "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError as exc:
        raise RuntimeError(f"{env_name} must be a number.") from exc
    if not isfinite(value) or value < 0 or value > 500:
        raise RuntimeError(f"{env_name} must be a finite value between 0 and 500 basis points.")
    return value


def load_fee_policy() -> tuple[dict[str, tuple[float, float]], dict]:
    """Return usable rates and transparent provenance for each venue."""
    fees = dict(PUBLIC_SPOT_FEES_BPS)
    sources = {
        venue: {"source": source, "verified": False, "rate_type": "public_estimate"}
        for venue, source in PUBLIC_FEE_SOURCES.items()
    }

    personal_maker = _read_bps("DOMINION_FEE_BINANCE_PERSONAL_MAKER_BPS")
    personal_taker = _read_bps("DOMINION_FEE_BINANCE_PERSONAL_TAKER_BPS")
    personal_verified = os.getenv("DOMINION_FEE_BINANCE_PERSONAL_VERIFIED", "").strip().upper() == "YES"

    if (personal_maker is None) != (personal_taker is None):
        raise RuntimeError("Set both Binance personal maker and taker rates together.")
    if personal_maker is not None:
        if not personal_verified:
            raise RuntimeError("Binance personal fee rates require DOMINION_FEE_BINANCE_PERSONAL_VERIFIED=YES.")
        fees["Binance"] = (personal_maker, personal_taker)
        sources["Binance"] = {
            "source": "BINANCE_PERSONAL_ACCOUNT_RATE",
            "verified": True,
            "rate_type": "personal_account_rate",
        }
    else:
        sources["Binance"] = {
            "source": "BINANCE_PUBLIC_STANDARD_FALLBACK",
            "verified": False,
            "rate_type": "public_fallback_estimate",
        }

    # HTX remains intentionally absent until its current public rate can be
    # verified from an accessible official schedule. This blocks net qualification
    # whenever HTX is one of the fresh venues being compared.
    return fees, sources
