"""Risk-gated Binance Spot Testnet order planning.

This module validates a complete entry plan before any exchange call. It does
not submit orders: the current adapter cannot attach and verify protective
stop-loss/take-profit orders after a fill, so sending an entry alone is blocked.
"""
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_DOWN

D = Decimal

def _dec(value, field: str) -> Decimal:
    try:
        result = D(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} must be a valid decimal.") from exc
    if not result.is_finite():
        raise ValueError(f"{field} must be finite.")
    return result

def _floor_step(value: Decimal, step: Decimal) -> Decimal:
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step

def _aligned(value: Decimal, step: Decimal) -> bool:
    return step > 0 and value == _floor_step(value, step)

@dataclass(frozen=True)
class BinanceSymbolRules:
    tick_size: Decimal
    step_size: Decimal
    min_quantity: Decimal
    max_quantity: Decimal
    min_notional: Decimal
    verified: bool = False

@dataclass(frozen=True)
class VerifiedFees:
    taker_fee_bps: Decimal
    verified: bool = False

@dataclass(frozen=True)
class SpotRiskContext:
    equity_quote: Decimal
    available_quote: Decimal
    daily_loss_quote: Decimal
    open_positions: int
    emergency_stop: bool = False

@dataclass(frozen=True)
class BinanceOrderPlan:
    symbol: str
    side: str
    quantity: str
    limit_price: str
    stop_loss: str
    take_profit: str
    max_planned_loss_quote: str
    estimated_round_trip_fee_quote: str
    notional_quote: str

class BinanceTestnetRiskGate:
    """Default-deny risk router for BUY-only Spot Testnet entry planning."""
    def __init__(self, *, max_risk_fraction=D("0.005"),
                 max_daily_loss_fraction=D("0.02"), max_open_positions=1,
                 max_quote_age_seconds=D("10"), max_spread_bps=D("20"),
                 max_slippage_bps=D("15")):
        if not D("0") < max_risk_fraction <= D("0.01"):
            raise ValueError("Per-trade risk must be positive and no more than 1%.")
        if not D("0") < max_daily_loss_fraction <= D("0.05"):
            raise ValueError("Daily loss must be positive and no more than 5%.")
        if max_open_positions != 1:
            raise ValueError("This project policy permits exactly one open position.")
        self.max_risk_fraction = D(str(max_risk_fraction))
        self.max_daily_loss_fraction = D(str(max_daily_loss_fraction))
        self.max_open_positions = max_open_positions
        self.max_quote_age_seconds = D(str(max_quote_age_seconds))
        self.max_spread_bps = D(str(max_spread_bps))
        self.max_slippage_bps = D(str(max_slippage_bps))

    def prepare_buy(self, *, symbol, entry_price, stop_loss, take_profit,
                    context, rules, fees, quote_age_seconds, spread_bps,
                    estimated_slippage_bps) -> BinanceOrderPlan:
        pair = symbol.strip().upper()
        if not pair.isalnum() or not 5 <= len(pair) <= 20:
            raise ValueError("Invalid Binance symbol.")
        entry, stop, target = (_dec(entry_price, "entry price"),
                               _dec(stop_loss, "stop loss"),
                               _dec(take_profit, "take profit"))
        equity = _dec(context.equity_quote, "equity")
        available_quote = _dec(context.available_quote, "available quote balance")
        daily_loss = _dec(context.daily_loss_quote, "daily loss")
        age, spread, slippage = (_dec(quote_age_seconds, "quote age"),
                                 _dec(spread_bps, "spread"),
                                 _dec(estimated_slippage_bps, "estimated slippage"))
        if context.emergency_stop:
            raise PermissionError("Emergency stop is active.")
        if equity <= 0 or available_quote < 0 or daily_loss < 0:
            raise ValueError("Equity must be positive; available balance and daily loss must be non-negative.")
        if context.open_positions < 0:
            raise ValueError("Open position count cannot be negative.")
        if context.open_positions >= self.max_open_positions:
            raise PermissionError("Maximum open-position limit has been reached.")
        if daily_loss >= equity * self.max_daily_loss_fraction:
            raise PermissionError("Daily loss limit has been reached.")
        if min(entry, stop, target) <= 0 or not stop < entry < target:
            raise ValueError("BUY plan requires positive prices and stop-loss < entry < take-profit.")
        if age < 0 or age > self.max_quote_age_seconds:
            raise PermissionError("Quote is stale or has an invalid timestamp.")
        if spread < 0 or spread > self.max_spread_bps:
            raise PermissionError("Spread exceeds the project risk limit.")
        if slippage < 0 or slippage > self.max_slippage_bps:
            raise PermissionError("Estimated slippage exceeds the project risk limit.")
        if not rules.verified:
            raise PermissionError("Fresh Binance symbol filters have not been verified.")
        tick, step, min_qty, max_qty, min_notional = (
            _dec(rules.tick_size, "tick size"), _dec(rules.step_size, "quantity step"),
            _dec(rules.min_quantity, "minimum quantity"), _dec(rules.max_quantity, "maximum quantity"),
            _dec(rules.min_notional, "minimum notional"))
        if min(tick, step, min_qty, max_qty, min_notional) <= 0 or max_qty < min_qty:
            raise ValueError("Binance symbol filters are invalid.")
        if not all(_aligned(p, tick) for p in (entry, stop, target)):
            raise ValueError("Entry, stop-loss and take-profit must align to tick size.")
        if not fees.verified:
            raise PermissionError("Verified account-tier taker fees are required.")
        taker_bps = _dec(fees.taker_fee_bps, "taker fee")
        if taker_bps < 0 or taker_bps > D("100"):
            raise ValueError("Taker fee is outside the accepted range.")
        risk_budget = equity * self.max_risk_fraction
        round_trip_fee_rate = (taker_bps * D("2")) / D("10000")
        risk_per_unit = (entry - stop) + (entry * round_trip_fee_rate)
        quantity = _floor_step(risk_budget / risk_per_unit, step)
        if quantity < min_qty or quantity > max_qty:
            raise PermissionError("Risk-sized quantity violates Binance quantity filters.")
        notional = quantity * entry
        if notional < min_notional:
            raise PermissionError("Risk-sized order is below Binance minimum notional.")
        planned_loss = quantity * (entry - stop)
        estimated_fees = notional * round_trip_fee_rate
        total_risk = planned_loss + estimated_fees
        if total_risk > risk_budget:
            raise PermissionError("Rounded order exceeds the per-trade risk budget.")
        if notional + (notional * taker_bps / D("10000")) > available_quote:
            raise PermissionError("Available quote balance cannot fund the order and estimated entry fee.")
        return BinanceOrderPlan(
            symbol=pair, side="BUY", quantity=format(quantity, "f"),
            limit_price=format(entry, "f"), stop_loss=format(stop, "f"),
            take_profit=format(target, "f"),
            max_planned_loss_quote=format(total_risk, "f"),
            estimated_round_trip_fee_quote=format(estimated_fees, "f"),
            notional_quote=format(notional, "f"))

    def execute(self, client, plan: BinanceOrderPlan, *, list_client_order_id: str) -> dict:
        """Submit a FOK entry with exchange-hosted OTOCO exits, behind explicit gates."""
        if not getattr(client, "allow_orders", False):
            raise PermissionError("Binance Testnet order gate is disabled; no order was sent.")
        submit = getattr(client, "place_protected_buy_otoco", None)
        if not callable(submit):
            raise PermissionError("Client lacks protected OTOCO support; no order was sent.")
        if plan.side != "BUY":
            raise PermissionError("Only BUY plans are supported by this protected workflow.")
        if not list_client_order_id or len(list_client_order_id) > 20:
            raise ValueError("A unique order-list ID of at most 20 characters is required.")
        return submit(
            symbol=plan.symbol, quantity=plan.quantity,
            entry_price=plan.limit_price, stop_loss=plan.stop_loss,
            take_profit=plan.take_profit,
            list_client_order_id=list_client_order_id,
        )
