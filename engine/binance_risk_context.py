"""Verified Binance Spot Testnet account and shared risk-context provider.

Equity is deliberately measured only in the configured quote asset (USDT),
excluding volatile non-quote holdings. This is conservative, not a portfolio
valuation. Unknown account permissions, journal state, or loss-ledger state
block new entries.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from .risk_execution import SpotRiskContext

MAX_TESTNET_RISK_CAPITAL_USDT = Decimal("20")


@dataclass(frozen=True)
class BinanceRiskSnapshot:
    context: SpotRiskContext
    account_snapshot_verified: bool
    daily_loss_verified: bool
    quote_asset: str
    journaled_order_lists: int
    recovery_status: str
    actual_equity_quote: Decimal
    risk_capital_cap_quote: Decimal
    exchange_open_orders: int
    captured_at: datetime


class BinanceRiskContextProvider:
    def __init__(self, client, lifecycle, daily_loss_ledger, *, quote_asset="USDT"):
        self.client = client
        self.lifecycle = lifecycle
        self.daily_loss_ledger = daily_loss_ledger
        self.quote_asset = quote_asset.strip().upper()
        if not self.quote_asset or not self.quote_asset.isalnum():
            raise ValueError("A valid quote asset is required.")

    @staticmethod
    def _amount(value, field: str) -> Decimal:
        try:
            amount = Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"Invalid Binance {field}.") from exc
        if not amount.is_finite() or amount < 0:
            raise ValueError(f"Invalid Binance {field}.")
        return amount

    def snapshot(self, *, now: datetime | None = None) -> BinanceRiskSnapshot:
        captured_at = now or datetime.now(timezone.utc)
        if captured_at.tzinfo is None or captured_at.utcoffset() is None:
            raise ValueError("Risk snapshot time must be timezone-aware.")
        account = self.client.account()
        if not isinstance(account, dict) or account.get("canTrade") is not True:
            raise PermissionError("Binance account does not confirm trading permission.")
        balances = account.get("balances")
        if not isinstance(balances, list):
            raise ValueError("Binance account balances are missing.")
        quote_rows = [
            item for item in balances
            if isinstance(item, dict) and item.get("asset") == self.quote_asset
        ]
        if len(quote_rows) != 1:
            raise ValueError("Quote-asset balance was not uniquely returned.")
        free = self._amount(quote_rows[0].get("free"), "free quote balance")
        locked = self._amount(quote_rows[0].get("locked"), "locked quote balance")
        equity = free + locked
        if equity <= 0:
            raise PermissionError("Quote-asset equity is not positive.")
        # Seeded Testnet inventory is not proof of an active position.
        # Enforce the limit from reconciled bot state and account-wide active orders.
        recovery = self.lifecycle.reconcile_after_restart()
        if (not isinstance(recovery, dict) or recovery.get("halted") is not False
                or recovery.get("operator_action_required") is True):
            raise PermissionError("Existing Binance order state is unresolved; execution remains halted.")
        orders = recovery.get("orders", [])
        if not isinstance(orders, list):
            raise ValueError("Binance recovery order summary is malformed.")
        journaled_positions = 0
        for item in orders:
            if not isinstance(item, dict) or item.get("safe") is not True:
                raise PermissionError("An existing Binance order is not safely reconciled.")
            if item.get("state") == "PROTECTED":
                journaled_positions += 1

        open_orders_reader = getattr(self.client, "account_open_orders", None)
        if not callable(open_orders_reader):
            raise PermissionError("Binance account-wide open orders cannot be verified.")
        exchange_orders = open_orders_reader()
        if not isinstance(exchange_orders, list):
            raise ValueError("Binance account-wide open-orders response is malformed.")
        for item in exchange_orders:
            if (not isinstance(item, dict)
                    or not isinstance(item.get("symbol"), str)
                    or not item["symbol"].isalnum()
                    or item.get("side") not in {"BUY", "SELL"}
                    or item.get("status") not in {"NEW", "PARTIALLY_FILLED"}):
                raise ValueError("Binance account-wide open-orders response is malformed.")

        # OTOCO protection legs and a journaled position occupy one slot.
        open_positions = 1 if journaled_positions or exchange_orders else 0
        if journaled_positions > 1:
            raise PermissionError("More than one journaled Binance position is present.")
        daily_loss = self.daily_loss_ledger.loss_for_day(now=now)
        if not isinstance(daily_loss, Decimal) or not daily_loss.is_finite() or daily_loss < 0:
            raise ValueError("Daily realized-loss ledger returned an invalid value.")
        risk_equity = min(equity, MAX_TESTNET_RISK_CAPITAL_USDT)
        risk_available = min(free, MAX_TESTNET_RISK_CAPITAL_USDT)
        context = SpotRiskContext(
            equity_quote=risk_equity,
            available_quote=risk_available,
            daily_loss_quote=daily_loss,
            open_positions=open_positions,
            emergency_stop=False,
        )
        return BinanceRiskSnapshot(
            context=context,
            account_snapshot_verified=True,
            daily_loss_verified=True,
            quote_asset=self.quote_asset,
            journaled_order_lists=len(orders),
            recovery_status=str(recovery.get("status", "UNKNOWN")),
            actual_equity_quote=equity,
            risk_capital_cap_quote=MAX_TESTNET_RISK_CAPITAL_USDT,
            exchange_open_orders=len(exchange_orders),
            captured_at=captured_at,
        )
