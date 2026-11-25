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
            # Do not surface transport exceptions which may contain request headers or URLs.
            raise RuntimeError(f"GMGN_READ_REQUEST_FAILED:{type(exc).__name__}") from None
        if isinstance(payload, dict):
            code = payload.get("code")
            if code not in (None, 0, "0", 200, "200", "success", "SUCCESS"):
                raise RuntimeError(f"GMGN_API_REJECTED:{str(code)[:32]}")
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
