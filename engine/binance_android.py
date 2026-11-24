"""Read-only Binance Spot Testnet account summary for the Android native bridge.

Credentials are supplied by the Android Keystore vault at call time. This
module never persists them and never enables order routing.
"""
from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation

from .binance_testnet import BinanceSpotTestnetClient


def account_summary(api_key: str, api_secret: str) -> str:
    if not api_key or not api_secret:
        return json.dumps({"connected": False, "error": "CREDENTIALS_MISSING"})
    try:
        client = BinanceSpotTestnetClient(api_key, api_secret, allow_orders=False)
        response = client.account()
        balances = []
        for item in response.get("balances", []):
            if not isinstance(item, dict):
                continue
            asset = str(item.get("asset", ""))[:20]
            try:
                free = Decimal(str(item.get("free", "0")))
                locked = Decimal(str(item.get("locked", "0")))
            except (InvalidOperation, ValueError):
                continue
            if not free.is_finite() or not locked.is_finite() or free < 0 or locked < 0:
                continue
            if free > 0 or locked > 0:
                balances.append({
                    "asset": asset,
                    "free": format(free, "f"),
                    "locked": format(locked, "f"),
                })
        permissions = response.get("permissions", [])
        return json.dumps({
            "connected": True,
            "environment": "BINANCE_SPOT_TESTNET",
            "can_trade": bool(response.get("canTrade", False)),
            "can_withdraw": bool(response.get("canWithdraw", False)),
            "can_deposit": bool(response.get("canDeposit", False)),
            "account_type": str(response.get("accountType", "UNKNOWN"))[:40],
            "balances": balances[:100],
            "permissions": [str(x)[:40] for x in permissions[:20]] if isinstance(permissions, list) else [],
        }, separators=(",", ":"))
    except Exception as error:
        # Do not return request URLs, headers, signatures, or credential values.
        code = getattr(error, "code", None)
        return json.dumps({
            "connected": False,
            "environment": "BINANCE_SPOT_TESTNET",
            "error": "BINANCE_REQUEST_FAILED",
            "exchange_code": int(code) if isinstance(code, int) else None,
        }, separators=(",", ":"))
