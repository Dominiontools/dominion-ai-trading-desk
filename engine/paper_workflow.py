"""End-to-end, fail-closed paper trading lifecycle.

Signals must be supplied by a strategy/scanner. This module validates risk,
opens a simulated position, updates trailing stops, and records exits. It never
connects to a broker or exchange and cannot place real orders.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable
from uuid import uuid4

from .positions import SimulatedPosition, evaluate_exit, update_trailing_stop
from .risk import RiskLimits


@dataclass(frozen=True)
class PaperSignal:
    symbol: str
    market: str
    side: str
    entry_price: float
    stop_loss: float
    take_profit: float
    quantity: float
    spread_bps: float
    estimated_slippage_bps: float
    quote_age_seconds: float
    trailing_distance: float | None = None


class PaperTradingDesk:
    """A single-position paper desk with the project's $20 / 0.5% / 2% policy."""

    def __init__(
        self,
        *,
        starting_equity: float = 20.0,
        limits: RiskLimits | None = None,
        journal: str | Path | None = None,
        clock: Callable[[], datetime] | None = None,
    ):
        if starting_equity <= 0:
            raise ValueError("Starting equity must be positive.")
        self.starting_equity = float(starting_equity)
        self.limits = limits or RiskLimits(max_risk_per_trade_pct=0.005,
                                           max_daily_loss_pct=0.02,
                                           max_open_positions=1)
        self.journal = Path(journal) if journal else None
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.position: SimulatedPosition | None = None
        self.trades: list[dict] = []
        self.realized_pnl = 0.0
        self._day = self.clock().astimezone(timezone.utc).date()
        self._daily_realized_pnl = 0.0

    @property
    def equity(self) -> float:
        return self.starting_equity + self.realized_pnl

    @property
    def daily_loss_pct(self) -> float:
        return max(0.0, -self._daily_realized_pnl / self.starting_equity)

    def _roll_day(self) -> None:
        today = self.clock().astimezone(timezone.utc).date()
        if today != self._day:
            self._day = today
            self._daily_realized_pnl = 0.0

    def _record(self, event: str, **fields) -> dict:
        record = {
            "timestamp": self.clock().astimezone(timezone.utc).isoformat(),
            "event": event,
            "mode": "PAPER_ONLY",
            "orders_enabled": False,
            **fields,
        }
        self.trades.append(record)
        if self.journal:
            self.journal.parent.mkdir(parents=True, exist_ok=True)
            with self.journal.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, sort_keys=True) + "\\n")
                stream.flush()
        return record

    def open_from_signal(self, signal: PaperSignal) -> dict:
        self._roll_day()
        if self.position is not None:
            return self._record("ENTRY_BLOCKED", symbol=signal.symbol,
                                reason="MAX_OPEN_POSITIONS")
        values = (signal.entry_price, signal.stop_loss, signal.take_profit,
                  signal.quantity, signal.spread_bps,
                  signal.estimated_slippage_bps, signal.quote_age_seconds)
        if any(value < 0 for value in values) or min(values[:4]) <= 0:
            return self._record("ENTRY_BLOCKED", symbol=signal.symbol,
                                reason="INVALID_SIGNAL")
        if signal.side not in {"BUY", "SELL"}:
            return self._record("ENTRY_BLOCKED", symbol=signal.symbol,
                                reason="INVALID_SIDE")
        if signal.side == "BUY" and not signal.stop_loss < signal.entry_price < signal.take_profit:
            return self._record("ENTRY_BLOCKED", symbol=signal.symbol,
                                reason="INVALID_BUY_LEVELS")
        if signal.side == "SELL" and not signal.take_profit < signal.entry_price < signal.stop_loss:
            return self._record("ENTRY_BLOCKED", symbol=signal.symbol,
                                reason="INVALID_SELL_LEVELS")
        risk_amount = abs(signal.entry_price - signal.stop_loss) * signal.quantity
        risk_pct = risk_amount / self.equity
        reasons = []
        if signal.market not in self.limits.allowed_markets:
            reasons.append("MARKET_NOT_ALLOWED")
        if risk_pct > self.limits.max_risk_per_trade_pct:
            reasons.append("PER_TRADE_RISK_EXCEEDED")
        if self.daily_loss_pct >= self.limits.max_daily_loss_pct:
            reasons.append("DAILY_LOSS_LIMIT_REACHED")
        if signal.spread_bps > self.limits.max_spread_bps:
            reasons.append("SPREAD_TOO_WIDE")
        if signal.estimated_slippage_bps > self.limits.max_slippage_bps:
            reasons.append("SLIPPAGE_TOO_HIGH")
        if signal.quote_age_seconds > self.limits.max_quote_age_seconds:
            reasons.append("STALE_QUOTE")
        if reasons:
            return self._record("ENTRY_BLOCKED", symbol=signal.symbol,
                                reasons=reasons, risk_amount=round(risk_amount, 8))
        position = SimulatedPosition(
            position_id=str(uuid4()), symbol=signal.symbol.upper(),
            market=signal.market, side=signal.side, entry_price=signal.entry_price,
            stop_loss=signal.stop_loss, take_profit=signal.take_profit,
            quantity=signal.quantity, trailing_distance=signal.trailing_distance,
        )
        self.position = position
        return self._record("PAPER_ENTRY", position=asdict(position),
                            risk_amount=round(risk_amount, 8),
                            risk_pct=round(risk_pct, 8))

    def update_price(self, symbol: str, price: float) -> dict:
        self._roll_day()
        if price <= 0:
            raise ValueError("Market price must be positive.")
        position = self.position
        if position is None or position.symbol != symbol.upper():
            return self._record("EXIT_WAITING", symbol=symbol.upper(),
                                reason="NO_MATCHING_OPEN_POSITION")
        updated = update_trailing_stop(position, price)
        decision = evaluate_exit(updated, price)
        if not decision.should_close:
            self.position = updated
            return self._record("POSITION_HOLD", position_id=position.position_id,
                                symbol=position.symbol, mark_price=price,
                                stop_loss=updated.stop_loss,
                                take_profit=updated.take_profit)
        exit_price = float(decision.exit_price or price)
        pnl = ((exit_price - position.entry_price) if position.side == "BUY"
               else (position.entry_price - exit_price)) * position.quantity
        self.realized_pnl += pnl
        self._daily_realized_pnl += pnl
        self.position = None
        return self._record("PAPER_EXIT", position_id=position.position_id,
                            symbol=position.symbol, side=position.side,
                            exit_reason=decision.reason, entry_price=position.entry_price,
                            exit_price=exit_price, quantity=position.quantity,
                            realized_pnl=round(pnl, 8),
                            equity=round(self.equity, 8),
                            daily_loss_pct=round(self.daily_loss_pct, 8))

    def close_position(self, price: float, reason: str = "MANUAL_PAPER_CLOSE") -> dict:
        if self.position is None:
            return self._record("EXIT_WAITING", reason="NO_OPEN_POSITION")
        position = self.position
        pnl = ((price - position.entry_price) if position.side == "BUY"
               else (position.entry_price - price)) * position.quantity
        self.realized_pnl += pnl
        self._roll_day()
        self._daily_realized_pnl += pnl
        self.position = None
        return self._record("PAPER_EXIT", position_id=position.position_id,
                            symbol=position.symbol, exit_reason=reason,
                            entry_price=position.entry_price, exit_price=price,
                            quantity=position.quantity, realized_pnl=round(pnl, 8),
                            equity=round(self.equity, 8),
                            daily_loss_pct=round(self.daily_loss_pct, 8))

    def snapshot(self) -> dict:
        self._roll_day()
        return {
            "mode": "PAPER_ONLY",
            "orders_enabled": False,
            "starting_equity": self.starting_equity,
            "equity": round(self.equity, 8),
            "realized_pnl": round(self.realized_pnl, 8),
            "daily_loss_pct": round(self.daily_loss_pct, 8),
            "open_position": asdict(self.position) if self.position else None,
            "recent_trades": self.trades[-20:],
        }
