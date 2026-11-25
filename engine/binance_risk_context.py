"""Verified Binance Spot Testnet account and shared risk-context provider.

Equity is deliberately measured only in the configured quote asset (USDT),
excluding volatile non-quote holdings. This is conservative, not a portfolio
valuation. Unknown account permissions, journal state, or loss-ledger state
block new entries.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation

from .risk_execution import SpotRiskContext


@dataclass(frozen=True)
class BinanceRiskSnapshot:
    context: SpotRiskContext
    account_snapshot_verified: bool
    daily_loss_verified: bool
    quote_asset: str
    journaled_order_lists: int
    recovery_status: str


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
        unmanaged_assets = []
        for item in balances:
            if not isinstance(item, dict) or item.get("asset") == self.quote_asset:
                continue
            asset = str(item.get("asset", "")).strip().upper()
            if not asset:
                raise ValueError("A Binance balance has no asset symbol.")
            asset_total = (
                self._amount(item.get("free"), f"{asset} free balance")
                + self._amount(item.get("locked"), f"{asset} locked balance")
            )
            if asset_total > 0:
                unmanaged_assets.append(asset)

        recovery = self.lifecycle.reconcile_after_restart()
        if (not isinstance(recovery, dict) or recovery.get("halted") is not False
                or recovery.get("operator_action_required") is True):
            raise PermissionError("Existing Binance order state is unresolved; execution remains halted.")
        orders = recovery.get("orders", [])
        if not isinstance(orders, list):
            raise ValueError("Binance recovery order summary is malformed.")
        open_positions = 0
        for item in orders:
            if not isinstance(item, dict) or item.get("safe") is not True:
                raise PermissionError("An existing Binance order is not safely reconciled.")
            if item.get("state") == "PROTECTED":
                open_positions += 1
        # Any non-quote holding is treated as an unmanaged open position.
        # This prevents the bot from ignoring manual or externally opened Spot
        # holdings when enforcing its one-position policy.
        open_positions += 1 if unmanaged_assets else 0
        if open_positions > 1:
            raise PermissionError("More than one managed or unmanaged Spot holding is present.")

        daily_loss = self.daily_loss_ledger.loss_for_day(now=now)
        if not isinstance(daily_loss, Decimal) or not daily_loss.is_finite() or daily_loss < 0:
            raise ValueError("Daily realized-loss ledger returned an invalid value.")
        context = SpotRiskContext(
            equity_quote=equity,
            available_quote=free,
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
        )
