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


def reconcile_saved_orders(api_key: str, api_secret: str, journal_path: str) -> str:
    """Read-only restart recovery for previously journaled Testnet brackets."""
    if not api_key or not api_secret:
        return json.dumps({"status": "SKIPPED", "reason": "CREDENTIALS_MISSING",
                           "halted": True, "orders_enabled": False})
    try:
        from pathlib import Path
        from .binance_lifecycle import BinanceProtectedLifecycle
        from .risk_execution import BinanceTestnetRiskGate

        # allow_orders=False is deliberate: startup recovery can query state,
        # but cannot submit, cancel, or amend any exchange order.
        client = BinanceSpotTestnetClient(api_key, api_secret, allow_orders=False)
        lifecycle = BinanceProtectedLifecycle(
            BinanceTestnetRiskGate(), client, journal_path=Path(journal_path)
        )
        result = lifecycle.reconcile_after_restart()
        result["orders_enabled"] = False
        result["environment"] = "BINANCE_SPOT_TESTNET"
        return json.dumps(result, separators=(",", ":"))
    except Exception:
        # Keep the recovery state blocked; never expose signed request details.
        return json.dumps({"status": "RECOVERY_FAILED", "halted": True,
                           "operator_action_required": True,
                           "orders_enabled": False,
                           "environment": "BINANCE_SPOT_TESTNET"},
                          separators=(",", ":"))



def account_risk_snapshot(
    api_key: str, api_secret: str, journal_path: str, daily_loss_path: str,
) -> str:
    """Read-only account, open-position and daily-loss snapshot for Android."""
    if not api_key or not api_secret:
        return json.dumps({
            "status": "SKIPPED", "halted": True, "reconciled": 0,
            "unresolved": [{"reason": "CREDENTIALS_MISSING"}],
            "operator_action_required": True, "orders_enabled": False,
            "environment": "BINANCE_SPOT_TESTNET",
        }, separators=(",", ":"))
    try:
        from pathlib import Path
        from .binance_daily_loss import BinanceDailyLossLedger
        from .binance_lifecycle import BinanceProtectedLifecycle
        from .binance_risk_context import BinanceRiskContextProvider
        from .risk_execution import BinanceTestnetRiskGate

        client = BinanceSpotTestnetClient(api_key, api_secret, allow_orders=False)
        ledger = BinanceDailyLossLedger(Path(daily_loss_path))
        lifecycle = BinanceProtectedLifecycle(
            BinanceTestnetRiskGate(), client,
            journal_path=Path(journal_path), daily_loss_ledger=ledger,
        )
        snapshot = BinanceRiskContextProvider(
            client, lifecycle, ledger, quote_asset="USDT",
        ).snapshot()
        recovery = lifecycle.last_result or {}
        return json.dumps({
            "status": snapshot.recovery_status,
            "halted": False,
            "reconciled": int(recovery.get("reconciled", 0) or 0),
            "unresolved": [],
            "operator_action_required": False,
            "orders_enabled": False,
            "environment": "BINANCE_SPOT_TESTNET",
            "risk_context": {
                "verified": True,
                "quote_asset": snapshot.quote_asset,
                "equity_quote": format(snapshot.context.equity_quote, "f"),
                "available_quote": format(snapshot.context.available_quote, "f"),
                "actual_equity_quote": format(snapshot.actual_equity_quote, "f"),
                "risk_capital_cap_quote": format(snapshot.risk_capital_cap_quote, "f"),
                "daily_loss_quote": format(snapshot.context.daily_loss_quote, "f"),
                "open_positions": snapshot.context.open_positions,
                "exchange_open_orders": snapshot.exchange_open_orders,
                "journaled_order_lists": snapshot.journaled_order_lists,
                "status": "VERIFIED",
            },
        }, separators=(",", ":"))
    except Exception:
        return json.dumps({
            "status": "RISK_CONTEXT_BLOCKED", "halted": True,
            "reconciled": 0,
            "unresolved": [{"reason": "ACCOUNT_OR_RISK_CONTEXT_UNVERIFIED"}],
            "operator_action_required": True, "orders_enabled": False,
            "environment": "BINANCE_SPOT_TESTNET",
            "risk_context": {
                "verified": False, "status": "BLOCKED",
                "quote_asset": "USDT",
            },
        }, separators=(",", ":"))

def emergency_close_after_native_approval(
    api_key: str, api_secret: str, journal_path: str, daily_loss_path: str,
    symbol: str, list_client_order_id: str, native_confirmation: bool,
) -> str:
    """Run one Testnet emergency close after the Android native dialog approves it.

    The WebView cannot pass an approval flag. TradingEnginePlugin calls this
    only from the positive action of its native, symbol-and-order-specific
    confirmation dialog. Exchange state is queried again after that approval.
    """
    if native_confirmation is not True:
        return json.dumps({"status": "APPROVAL_REQUIRED", "halted": True,
                           "orders_enabled": False})
    pair = str(symbol or "").strip().upper()
    order_id = str(list_client_order_id or "").strip()
    if (not api_key or not api_secret or not pair.isalnum()
            or not 5 <= len(pair) <= 20 or not order_id
            or len(order_id) > 20 or not order_id.isascii()):
        return json.dumps({"status": "INVALID_EMERGENCY_REQUEST", "halted": True,
                           "orders_enabled": False})
    try:
        from pathlib import Path
        from .binance_daily_loss import BinanceDailyLossLedger
        from .binance_lifecycle import BinanceProtectedLifecycle
        from .risk_execution import BinanceTestnetRiskGate

        client = BinanceSpotTestnetClient(api_key, api_secret, allow_orders=True)
        if not client.allow_orders:
            raise PermissionError("Testnet order actions are disabled.")
        account = client.account()
        if account.get("canTrade") is not True:
            raise PermissionError("The Testnet account has no trading permission.")

        ledger = BinanceDailyLossLedger(Path(daily_loss_path))
        lifecycle = BinanceProtectedLifecycle(
            BinanceTestnetRiskGate(), client,
            journal_path=Path(journal_path), daily_loss_ledger=ledger,
        )
        if lifecycle._journal_invalid or order_id not in lifecycle._submitted_ids:
            raise PermissionError("The order is not present in the valid local lifecycle journal.")
        if lifecycle._submitted_symbols.get(order_id) != pair:
            raise PermissionError("The symbol does not match the journaled order.")
        previous = lifecycle.last_result or {}
        if previous.get("order_list_id") == order_id and previous.get("status") in {
            "EMERGENCY_CLOSE_PENDING", "EMERGENCY_CLOSE_UNCONFIRMED"
        }:
            raise PermissionError("An emergency close was already attempted; manual reconciliation is required.")

        # Confirm that the exact bot entry still needs operator intervention.
        exchange_state = client.reconcile_protected_buy_otoco(
            symbol=pair, list_client_order_id=order_id,
        )
        if not isinstance(exchange_state, dict) or exchange_state.get("action_required") is not True:
            raise PermissionError("Fresh exchange state does not show an emergency-close requirement.")
        ticker = client.ticker_price(symbol=pair)
        reference_price = str(ticker.get("price", ""))
        price = Decimal(reference_price)
        if not price.is_finite() or price <= 0:
            raise ValueError("The latest Testnet reference price is invalid.")

        result = lifecycle.emergency_flatten(
            symbol=pair, list_client_order_id=order_id,
            reference_price=reference_price, operator_approved=True,
        )
        result["environment"] = "BINANCE_SPOT_TESTNET"
        result["orders_enabled"] = True
        return json.dumps(result, separators=(",", ":"))
    except Exception as error:
        return json.dumps({
            "status": "EMERGENCY_CLOSE_BLOCKED",
            "halted": True,
            "operator_action_required": True,
            "orders_enabled": False,
            "reason": type(error).__name__,
            "environment": "BINANCE_SPOT_TESTNET",
        }, separators=(",", ":"))

