"""Public, read-only discovery feeds for the specialist crypto agents.

DEX Screener supplies token/pair metadata, GeckoTerminal supplies recent pool
trades, GoPlus supplies optional EVM token-security evidence, and a public RSS
feed supplies news headlines. No wallet keys or trading endpoints are used.
"""
from __future__ import annotations

import json
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def http_json(url: str, timeout: float = 8.0, headers: dict | None = None):
    request = Request(url, headers={"User-Agent": "Dominion-AI-Trading-Desk/0.1", **(headers or {})})
    with urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP status {response.status}")
        return json.loads(response.read().decode("utf-8"))


def http_text(url: str, timeout: float = 8.0) -> str:
    request = Request(url, headers={"User-Agent": "Dominion-AI-Trading-Desk/0.1"})
    with urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP status {response.status}")
        return response.read().decode("utf-8", errors="replace")


class DexScreenerDiscovery:
    """Fetch latest token profiles and enrich them with pool liquidity/volume."""

    BASE = "https://api.dexscreener.com"

    def __init__(self, fetch_json=http_json, timeout: float = 8.0):
        self.fetch_json, self.timeout = fetch_json, timeout

    def discover(self, limit: int = 12) -> list[dict]:
        if not 1 <= limit <= 30:
            raise ValueError("limit must be between 1 and 30")
        profiles = self.fetch_json(self.BASE + "/token-profiles/latest/v1", self.timeout)
        if not isinstance(profiles, list):
            raise RuntimeError("Unexpected DEX Screener token-profile response")
        results = []
        seen = set()
        for profile in profiles:
            if not isinstance(profile, dict):
                continue
            chain, address = str(profile.get("chainId", "")), str(profile.get("tokenAddress", ""))
            if not chain or not address or (chain, address.lower()) in seen:
                continue
            seen.add((chain, address.lower()))
            try:
                pairs = self.fetch_json(
                    f"{self.BASE}/token-pairs/v1/{chain}/{address}", self.timeout
                )
            except Exception:
                continue
            if not isinstance(pairs, list) or not pairs:
                continue
            valid = []
            for pair in pairs:
                if not isinstance(pair, dict):
                    continue
                liquidity = (pair.get("liquidity") or {}).get("usd")
                try:
                    liquidity = float(liquidity)
                    price = float(pair.get("priceUsd") or 0)
                except (TypeError, ValueError):
                    continue
                if liquidity < 0 or price <= 0:
                    continue
                valid.append((liquidity, pair, price))
            if not valid:
                continue
            liquidity, pair, price = max(valid, key=lambda item: item[0])
            token = pair.get("baseToken") or {}
            txns = pair.get("txns") or {}
            h24 = txns.get("h24") or {}
            volume = (pair.get("volume") or {}).get("h24")
            created = pair.get("pairCreatedAt")
            age_hours = None
            if created:
                age_hours = max(0.0, (datetime.now(timezone.utc).timestamp() * 1000 - float(created)) / 3_600_000)
            results.append({
                "chain_id": chain, "token_address": address,
                "symbol": str(token.get("symbol") or profile.get("symbol") or "UNKNOWN"),
                "name": str(token.get("name") or profile.get("name") or "Unknown"),
                "pair_address": str(pair.get("pairAddress") or ""),
                "price_usd": price, "liquidity_usd": liquidity,
                "volume_24h_usd": float(volume or 0),
                "buys_24h": int(h24.get("buys") or 0),
                "sells_24h": int(h24.get("sells") or 0),
                "pair_age_hours": age_hours, "dex_url": pair.get("url"),
                "profile_description": str(profile.get("description") or "")[:1000],
                "source": "DEXSCREENER",
            })
            if len(results) >= limit:
                break
        return results


class GeckoTerminalWhaleFeed:
    """Fetch recent DEX pool trades and normalize large notional swaps."""

    BASE = "https://api.geckoterminal.com/api/v2"

    def __init__(self, fetch_json=http_json, timeout: float = 8.0,
                 min_notional_usd: float = 100_000.0):
        self.fetch_json, self.timeout = fetch_json, timeout
        self.min_notional_usd = min_notional_usd

    def trades(self, network: str, pool_address: str, symbol: str) -> list[dict]:
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,40}", network) or not pool_address:
            raise ValueError("Invalid GeckoTerminal network or pool address")
        url = f"{self.BASE}/networks/{network}/pools/{pool_address}/trades"
        payload = self.fetch_json(url, self.timeout, headers={"Accept": "application/json;version=20230302"})
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            raise RuntimeError("Unexpected GeckoTerminal trades response")
        output = []
        for item in data:
            attrs = item.get("attributes") if isinstance(item, dict) else None
            if not isinstance(attrs, dict):
                continue
            try:
                notional = float(attrs.get("volume_in_usd") or 0)
            except (TypeError, ValueError):
                continue
            if notional < self.min_notional_usd:
                continue
            kind = str(attrs.get("kind") or "").lower()
            side = "BUY" if kind == "buy" else "SELL" if kind == "sell" else ""
            stamp = attrs.get("block_timestamp") or attrs.get("timestamp")
            if not side or not stamp:
                continue
            output.append({
                "symbol": symbol.upper(), "side": side, "notional_usd": notional,
                "timestamp": stamp, "wallet": attrs.get("tx_from_address"),
                "tx_hash": attrs.get("tx_hash"), "source": "GECKOTERMINAL",
            })
        return output


class GoPlusSecurityFeed:
    """Optional GoPlus EVM token-security lookup; requires user-supplied API token."""

    BASE = "https://api.gopluslabs.io/api/v1/token_security"
    CHAIN_IDS = {
        "ethereum": "1", "bsc": "56", "polygon": "137",
        "arbitrum": "42161", "optimism": "10", "base": "8453",
        "avalanche": "43114", "fantom": "250", "cronos": "25",
    }

    def __init__(self, fetch_json=http_json, token: str | None = None, timeout: float = 8.0):
        self.fetch_json, self.token, self.timeout = fetch_json, token, timeout

    def assess(self, chain: str, address: str) -> dict:
        chain_id = self.CHAIN_IDS.get(chain.lower())
        if not chain_id:
            return {"status": "UNSUPPORTED_CHAIN", "source": "GOPLUS"}
        if not self.token:
            return {"status": "WAITING_FOR_API_TOKEN", "source": "GOPLUS"}
        query = urlencode({"contract_addresses": address})
        payload = self.fetch_json(
            f"{self.BASE}/{chain_id}?{query}", self.timeout,
            headers={"Authorization": self.token},
        )
        if not isinstance(payload, dict) or str(payload.get("code")) != "1":
            raise RuntimeError("GoPlus security request failed")
        rows = payload.get("result") or {}
        item = rows.get(address.lower()) or rows.get(address)
        if not isinstance(item, dict):
            return {"status": "NO_SECURITY_RECORD", "source": "GOPLUS"}
        # Keep raw flags; never turn missing fields into a clean bill of health.
        risks = []
        if item.get("is_honeypot") == "1": risks.append("HONEYPOT")
        if item.get("cannot_sell_all") == "1": risks.append("CANNOT_SELL_ALL")
        if item.get("is_mintable") == "1": risks.append("MINTABLE")
        if item.get("hidden_owner") == "1": risks.append("HIDDEN_OWNER")
        if item.get("is_open_source") == "0": risks.append("UNVERIFIED_CONTRACT")
        holders = item.get("holders") or []
        top_holder_pct = None
        try:
            top_holder_pct = max((float(x.get("percent", 0)) for x in holders), default=0) * 100
        except (TypeError, ValueError):
            pass
        dexes = item.get("dex") or []
        liquidity = None
        try:
            liquidity = max((float(x.get("liquidity", 0)) for x in dexes), default=0)
        except (TypeError, ValueError):
            pass
        return {
            "status": "RISK_FLAGS_FOUND" if risks else "DATA_RETURNED_REQUIRES_REVIEW",
            "source": "GOPLUS", "risks": risks,
            "is_honeypot": item.get("is_honeypot"),
            "is_open_source": item.get("is_open_source"),
            "is_mintable": item.get("is_mintable"),
            "cannot_sell_all": item.get("cannot_sell_all"),
            "liquidity_usd": liquidity, "top_holder_pct": top_holder_pct,
            "holder_count": item.get("holder_count"),
        }


class PublicNewsRSS:
    """Read headlines from a public RSS feed; no social account or API key."""

    def __init__(self, fetch_text=http_text, url: str | None = None, timeout: float = 8.0):
        self.fetch_text, self.timeout = fetch_text, timeout
        self.url = url or os.getenv("DOMINION_NEWS_RSS_URL", "https://cointelegraph.com/rss")

    def headlines(self, limit: int = 20) -> list[dict]:
        xml_text = self.fetch_text(self.url, self.timeout)
        root = ET.fromstring(xml_text)
        output = []
        for item in root.findall(".//item")[:limit]:
            title = (item.findtext("title") or "").strip()
            description = (item.findtext("description") or "").strip()
            pub_date = (item.findtext("pubDate") or "").strip()
            if title:
                output.append({"text": (title + " " + description)[:2000],
                               "title": title, "published_at": pub_date,
                               "source": "PUBLIC_RSS"})
        return output
