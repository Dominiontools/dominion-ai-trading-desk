"""Official GMGN OpenAPI read-only client.

Only exist-auth endpoints are implemented here. No wallet signing, swaps,
orders, private keys, or withdrawals are supported by this module.
"""
from __future__ import annotations

import json
import time
import uuid
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from typing import Callable

GMGN_BASE_URL = "https://openapi.gmgn.ai"


def _http_json(method: str, url: str, headers: dict[str, str], body: bytes | None, timeout: float) -> object:
    request = Request(url, data=body, headers=headers, method=method)
    with urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"GMGN HTTP status {response.status}")
        return json.loads(response.read().decode("utf-8"))


class GMGNReadOnlyClient:
    """GMGN official OpenAPI client for read-only token and market data."""

    def __init__(
        self,
        api_key: str,
        *,
        fetch_json: Callable = _http_json,
        timeout: float = 8.0,
        clock: Callable[[], float] = time.time,
        client_id: Callable[[], str] = lambda: str(uuid.uuid4()),
    ):
        key = str(api_key or "").strip()
        if not key or len(key) > 512:
            raise ValueError("A valid GMGN API key is required.")
        if timeout <= 0:
            raise ValueError("Timeout must be positive.")
        self._api_key = key
        self.fetch_json = fetch_json
        self.timeout = timeout
        self.clock = clock
        self.client_id = client_id

    def _request(self, method: str, path: str, query: dict | None = None, body: dict | None = None) -> object:
        params = dict(query or {})
        params["timestamp"] = str(int(self.clock()))
        params["client_id"] = self.client_id()
        url = f"{GMGN_BASE_URL}{path}?{urlencode(params, doseq=True)}"
        body_bytes = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8") if body is not None else None
        headers = {
            "X-APIKEY": self._api_key,
            "Content-Type": "application/json",
            "User-Agent": "Dominion-AI-Trading-Desk/0.1",
        }
        try:
            payload = self.fetch_json(method, url, headers, body_bytes, self.timeout)
        except Exception as exc:
            # Surface only a numeric HTTP status, never headers, URL, or credential values.
            status_code = getattr(exc, "code", None)
            if isinstance(status_code, int):
                raise RuntimeError(f"GMGN_HTTP_ERROR:{status_code}") from None
            raise RuntimeError(f"GMGN_READ_REQUEST_FAILED:{type(exc).__name__}") from None
        if isinstance(payload, dict):
            code = payload.get("code")
            if code not in (None, 0, "0", 200, "200", "success", "SUCCESS"):
                reason = str(payload.get("error") or payload.get("message") or "")[:80]
                raise RuntimeError(f"GMGN_API_REJECTED:{str(code)[:32]}:{reason}")
            if payload.get("success") is False:
                raise RuntimeError("GMGN_API_REJECTED")
        return payload

    def trenches(self, chain: str = "sol", *, limit: int = 50) -> object:
        chain = str(chain).strip().lower()
        if chain not in {"sol", "bsc", "base", "eth", "arbitrum", "hyperevm", "robinhood", "arc", "stable", "avalanche", "elysium"}:
            raise ValueError("Unsupported GMGN chain.")
        if not 1 <= limit <= 80:
            raise ValueError("GMGN trenches limit must be between 1 and 80.")
        section = {"filters": ["offchain", "onchain"], "launchpad_platform_v2": True, "limit": limit}
        body = {
            "version": "v2",
            "new_creation": dict(section),
            "near_completion": dict(section),
            "completed": dict(section),
        }
        return self._request("POST", "/v1/trenches", {"chain": chain}, body)

    def trending(self, chain: str = "sol", interval: str = "1h", *, limit: int = 30) -> object:
        if interval not in {"1m", "5m", "1h", "6h", "24h"}:
            raise ValueError("Unsupported GMGN trending interval.")
        if not 1 <= limit <= 100:
            raise ValueError("GMGN trending limit must be between 1 and 100.")
        return self._request("GET", "/v1/market/rank", {"chain": chain, "interval": interval, "limit": limit})

    def token_info(self, chain: str, address: str) -> object:
        return self._token_request("/v1/token/info", chain, address)

    def token_security(self, chain: str, address: str) -> object:
        return self._token_request("/v1/token/security", chain, address)

    def token_pool_info(self, chain: str, address: str) -> object:
        return self._token_request("/v1/token/pool_info", chain, address)

    def token_top_holders(self, chain: str, address: str) -> object:
        return self._token_request("/v1/market/token_top_holders", chain, address)

    def token_top_traders(self, chain: str, address: str) -> object:
        return self._token_request("/v1/market/token_top_traders", chain, address)

    def _token_request(self, path: str, chain: str, address: str) -> object:
        chain = str(chain).strip().lower()
        address = str(address).strip()
        if not chain or len(chain) > 32 or not address or len(address) > 128:
            raise ValueError("A valid chain and token address are required.")
        return self._request("GET", path, {"chain": chain, "address": address})


def _find_field(value: object, field: str):
    if isinstance(value, dict):
        if field in value:
            return value[field]
        for nested in value.values():
            found = _find_field(nested, field)
            if found is not None:
                return found
    elif isinstance(value, list):
        for nested in value:
            found = _find_field(nested, field)
            if found is not None:
                return found
    return None


def summarize_security_evidence(payload: object, chain: str) -> dict:
    """Extract documented GMGN security signals without declaring a token safe."""
    chain = str(chain).strip().lower()
    flags: list[str] = []
    unknown: list[str] = []
    observed: dict[str, object] = {}

    def text_value(field: str):
        value = _find_field(payload, field)
        if value is None or value == "":
            unknown.append(field)
            return None
        return str(value).strip().lower()

    def bool_value(field: str):
        value = _find_field(payload, field)
        if value is None or value == "":
            unknown.append(field)
            return None
        if isinstance(value, bool):
            return value
        normalized = str(value).strip().lower()
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no"}:
            return False
        unknown.append(field)
        return None

    open_source = text_value("open_source")
    owner_renounced = text_value("owner_renounced")
    wash_trading = bool_value("is_wash_trading")
    rug_ratio = _find_field(payload, "rug_ratio")
    try:
        rug_score = float(rug_ratio)
        if not 0 <= rug_score <= 1:
            raise ValueError
        observed["rug_ratio"] = rug_score
        if rug_score > 0.3:
            flags.append("GMGN_HIGH_RUG_RATIO")
    except (TypeError, ValueError):
        unknown.append("rug_ratio")

    if open_source == "no":
        flags.append("GMGN_SOURCE_NOT_VERIFIED")
    elif open_source != "yes":
        unknown.append("open_source")

    if owner_renounced == "no":
        flags.append("GMGN_OWNER_NOT_RENOUNCED")
    elif owner_renounced != "yes":
        unknown.append("owner_renounced")

    if wash_trading is True:
        flags.append("GMGN_WASH_TRADING_DETECTED")

    if chain in {"bsc", "base"}:
        honeypot = text_value("is_honeypot")
        if honeypot == "yes":
            flags.append("GMGN_HONEYPOT_DETECTED")
        elif honeypot not in {"no"}:
            unknown.append("is_honeypot")

    if chain == "sol":
        mint_renounced = bool_value("renounced_mint")
        freeze_renounced = bool_value("renounced_freeze_account")
        if mint_renounced is False:
            flags.append("GMGN_MINT_AUTHORITY_NOT_RENOUNCED")
        if freeze_renounced is False:
            flags.append("GMGN_FREEZE_AUTHORITY_NOT_RENOUNCED")

    for field in ("buy_tax", "sell_tax", "top_10_holder_rate",
                  "dev_team_hold_rate", "creator_balance_rate",
                  "suspected_insider_hold_rate", "rat_trader_amount_rate",
                  "bundler_trader_amount_rate", "sniper_count", "burn_status"):
        value = _find_field(payload, field)
        if value is not None:
            observed[field] = value

    critical_unknown = bool(unknown)
    if flags:
        status = "RISK_FLAGS_FOUND"
    elif critical_unknown:
        status = "INSUFFICIENT_EVIDENCE"
    else:
        status = "NO_EXPLICIT_FLAGS"

    return {
        "status": status,
        "risk_flags": sorted(set(flags)),
        "unknown_fields": sorted(set(unknown)),
        "observed": observed,
        "disclaimer": "No explicit GMGN flag is not a safety guarantee.",
    }


def extract_trenches_tokens(payload: object, chain: str = "sol", *, limit: int = 50) -> list[dict]:
    """Extract only token-shaped records from the documented Trenches categories."""
    chain = str(chain).strip().lower()
    if not 1 <= limit <= 80:
        raise ValueError("Token extraction limit must be between 1 and 80.")
    found: list[dict] = []
    seen: set[str] = set()

    def visit(value: object) -> None:
        if len(found) >= limit:
            return
        if isinstance(value, dict):
            address = next((value.get(key) for key in
                            ("token_address", "address", "contract_address")
                            if isinstance(value.get(key), str) and value.get(key).strip()), None)
            symbol = value.get("symbol") or value.get("ticker")
            if isinstance(address, str) and isinstance(symbol, str):
                normalized_address = address.strip()
                if 20 <= len(normalized_address) <= 128 and normalized_address not in seen:
                    seen.add(normalized_address)
                    found.append({
                        "chain": chain,
                        "token_address": normalized_address,
                        "symbol": symbol.strip()[:32],
                        "name": str(value.get("name") or symbol).strip()[:80],
                        "price": value.get("price"),
                        "liquidity": value.get("liquidity"),
                        "rug_ratio": value.get("rug_ratio"),
                        "launchpad": value.get("launchpad") or value.get("launchpad_platform"),
                        "created_timestamp": value.get("created_timestamp") or value.get("creation_timestamp"),
                    })
            for key in ("new_creation", "near_completion", "completed", "list", "tokens", "items", "data"):
                if key in value:
                    visit(value[key])
        elif isinstance(value, list):
            for item in value:
                visit(item)
                if len(found) >= limit:
                    break

    visit(payload)
    return found
