from dataclasses import dataclass, replace

@dataclass(frozen=True)
class SimulatedPosition:
    position_id: str
    symbol: str
    market: str
    side: str
    entry_price: float
    stop_loss: float
    take_profit: float
    quantity: float
    trailing_distance: float | None = None
    status: str = "OPEN"

    def __post_init__(self):
        if self.side not in {"BUY", "SELL"}:
            raise ValueError("Side must be BUY or SELL.")
        if min(self.entry_price, self.stop_loss, self.take_profit, self.quantity) <= 0:
            raise ValueError("Prices and quantity must be positive.")
        if self.side == "BUY":
            valid = self.stop_loss < self.take_profit and (self.trailing_distance is not None or self.stop_loss < self.entry_price)
            if not valid or self.entry_price >= self.take_profit:
                raise ValueError("BUY requires stop < target and entry < target; trailing stops may protect profit above entry.")
        if self.side == "SELL":
            valid = self.take_profit < self.stop_loss and (self.trailing_distance is not None or self.entry_price < self.stop_loss)
            if not valid or self.take_profit >= self.entry_price:
                raise ValueError("SELL requires target < stop and target < entry; trailing stops may protect profit below entry.")

@dataclass(frozen=True)
class ExitDecision:
    should_close: bool
    reason: str
    exit_price: float | None = None

def evaluate_exit(position: SimulatedPosition, current_price: float) -> ExitDecision:
    if position.status != "OPEN":
        return ExitDecision(False, "Position is not open.")
    if current_price <= 0:
        raise ValueError("Current price must be positive.")
    if position.side == "BUY":
        if current_price <= position.stop_loss:
            return ExitDecision(True, "STOP_LOSS", position.stop_loss)
        if current_price >= position.take_profit:
            return ExitDecision(True, "TAKE_PROFIT", position.take_profit)
    else:
        if current_price >= position.stop_loss:
            return ExitDecision(True, "STOP_LOSS", position.stop_loss)
        if current_price <= position.take_profit:
            return ExitDecision(True, "TAKE_PROFIT", position.take_profit)
    return ExitDecision(False, "Position remains open.")

def update_trailing_stop(position: SimulatedPosition, current_price: float) -> SimulatedPosition:
    d = position.trailing_distance
    if d is None or d <= 0 or current_price <= 0 or position.status != "OPEN":
        return position
    if position.side == "BUY":
        return replace(position, stop_loss=max(position.stop_loss, current_price - d))
    return replace(position, stop_loss=min(position.stop_loss, current_price + d))
