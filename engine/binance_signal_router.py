"""Strategy-to-Binance Spot Testnet router with explicit verified-context gates.

This adapter converts a validated directional setup into a risk-sized,
exchange-protected OTOCO order. The Android strategy service can call it only
when its explicit Testnet switch is enabled; callers must supply verified
account/daily-risk context and the client must independently pass the Testnet
order-enable gates.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from .binance_lifecycle import BinanceProtectedLifecycle
from .binance_market_rules import fetch_symbol_rules, fetch_verified_taker_fees
from .crypto_arbitrage import ExchangeQuote, quote_age_seconds
from .risk_execution import (
    BinanceTestnetRiskGate, SpotRiskContext, VerifiedFees,
)


class BinanceTestnetSignalRouter:
    """Default-deny BUY-only strategy router for Binance Spot Testnet."""

    def __init__(
        self,
        client,
        lifecycle: BinanceProtectedLifecycle,
        risk_gate: BinanceTestnetRiskGate | None = None,
        *,
        max_quote_age_seconds: float = 2.0,
        estimated_slippage_bps: float = 5.0,
    ):
        if max_quote_age_seconds <= 0 or estimated_slippage_bps < 0:
            raise ValueError("Invalid quote-age or slippage policy.")
        self.client = client
        self.lifecycle = lifecycle
        self.risk_gate = risk_gate or BinanceTestnetRiskGate(
            max_quote_age_seconds=max_quote_age_seconds
        )
        self.max_quote_age_seconds = max_quote_age_seconds
        self.estimated_slippage_bps = estimated_slippage_bps

    def submit_verified_setup(
        self, setup, quote: ExchangeQuote, *, snapshot, fees: VerifiedFees | None = None,
        list_client_order_id: str | None = None,
        now: datetime | None = None,
    ) -> dict:
        """Route using a fresh BinanceRiskSnapshot rather than caller-made flags."""
        return self.submit_setup(
            setup, quote,
            context=snapshot.context,
            fees=fees,
            account_snapshot_verified=snapshot.account_snapshot_verified,
            daily_loss_verified=snapshot.daily_loss_verified,
            list_client_order_id=list_client_order_id,
            now=now,
        )

    def submit_setup(
        self,
        setup,
        quote: ExchangeQuote,
        *,
        context: SpotRiskContext,
        fees: VerifiedFees | None = None,
        account_snapshot_verified: bool,
        daily_loss_verified: bool,
        list_client_order_id: str | None = None,
        now: datetime | None = None,
    ) -> dict:
        """Validate context, size the order and submit one protected Testnet bracket."""
        if not getattr(self.client, "allow_orders", False):
            raise PermissionError("Binance Spot Testnet order gate is disabled.")
        if not account_snapshot_verified or not daily_loss_verified:
            raise PermissionError(
                "Verified account balance and daily realized-loss context are required."
            )
        if getattr(setup, "market", None) != "CRYPTO":
            raise PermissionError("Only crypto Spot setups can use this router.")
        if getattr(setup, "side", None) != "BUY":
            raise PermissionError("Binance Spot router currently supports BUY setups only.")
        symbol = str(getattr(setup, "symbol", "")).strip().upper()
        quote_symbol = quote.symbol.replace("/", "").replace("-", "").upper()
        if not symbol or quote_symbol != symbol or quote.exchange.lower() != "binance":
            raise ValueError("A matching fresh Binance quote is required.")
        current = now or datetime.now(timezone.utc)
        age = quote_age_seconds(quote, now=current)
        if age > self.max_quote_age_seconds:
            raise PermissionError("Binance quote is stale.")
        mid = (quote.bid + quote.ask) / 2
        spread_bps = (quote.ask - quote.bid) / mid * 10_000
        entry = quote.ask
        stop = float(setup.stop_loss)
        target = float(setup.target_2r)
        if not stop < entry < target:
            raise PermissionError(
                "The setup's protective levels no longer bracket the current ask price."
            )
        rules = fetch_symbol_rules(self.client, symbol)
        verified_fees = fees if fees is not None else fetch_verified_taker_fees(self.client, symbol)
        plan = self.risk_gate.prepare_buy(
            symbol=symbol,
            entry_price=entry,
            stop_loss=stop,
            take_profit=target,
            context=context,
            rules=rules,
            fees=verified_fees,
            quote_age_seconds=age,
            spread_bps=spread_bps,
            estimated_slippage_bps=self.estimated_slippage_bps,
        )
        order_id = list_client_order_id or ("dom" + uuid4().hex[:17])
        result = self.lifecycle.submit_and_verify(
            plan, list_client_order_id=order_id
        )
        emergency_result = None
        if result.get("protected") is not True and result.get("operator_action_required") is True:
            try:
                # Fetch a fresh exchange price after the protection check; never
                # use the earlier strategy quote for emergency min-notional checks.
                emergency_quote = self.client.ticker_price(symbol=symbol)
                emergency_price = emergency_quote.get("price")
                emergency_result = self.lifecycle.emergency_flatten(
                    symbol=symbol,
                    list_client_order_id=order_id,
                    reference_price=str(emergency_price),
                )
            except Exception as exc:
                emergency_result = {
                    "status": "EMERGENCY_CLOSE_UNCONFIRMED",
                    "halted": True,
                    "operator_action_required": True,
                    "error_type": type(exc).__name__,
                }
        return {
            "environment": "BINANCE_SPOT_TESTNET",
            "symbol": symbol,
            "side": "BUY",
            "status": (
                emergency_result.get("status")
                if emergency_result is not None
                else result.get("status")
            ),
            "protected": result.get("protected") is True,
            "halted": result.get("halted") is True,
            "operator_action_required": (
                emergency_result.get("operator_action_required") is True
                if emergency_result is not None
                else result.get("operator_action_required") is True
            ),
            "emergency_close": emergency_result,
            "plan": {
                "quantity": plan.quantity,
                "entry": plan.limit_price,
                "stop_loss": plan.stop_loss,
                "take_profit": plan.take_profit,
                "max_planned_loss_quote": plan.max_planned_loss_quote,
                "notional_quote": plan.notional_quote,
            },
            "orders_enabled": bool(getattr(self.client, "allow_orders", False)),
        }
