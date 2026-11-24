"""Paper-only cross-exchange crypto arbitrage calculations.

This module detects price differences; it does not connect to exchanges or place orders.
Real execution requires pre-funded exchange balances, depth-aware fills, fee schedules,
withdrawal/network risk controls, and separate exchange adapters.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import permutations


@dataclass(frozen=True)
class ExchangeQuote:
    exchange: str
    symbol: str
    bid: float
    ask: float
    timestamp: datetime
    bid_size: float = 0.0
    ask_size: float = 0.0

    def __post_init__(self):
        if not self.exchange.strip() or not self.symbol.strip():
            raise ValueError("Exchange and symbol are required.")
        if self.bid <= 0 or self.ask <= 0 or self.ask < self.bid:
            raise ValueError("Quote prices must be positive and ask must be >= bid.")
        if self.bid_size < 0 or self.ask_size < 0:
            raise ValueError("Quote sizes cannot be negative.")
        if self.timestamp.tzinfo is None:
            raise ValueError("Quote timestamp must be timezone-aware.")


@dataclass(frozen=True)
class ArbitrageCosts:
    buy_fee_bps: float
    sell_fee_bps: float
    buy_slippage_bps: float = 0.0
    sell_slippage_bps: float = 0.0
    transfer_cost_bps: float = 0.0

    def __post_init__(self):
        values = (self.buy_fee_bps, self.sell_fee_bps, self.buy_slippage_bps,
                  self.sell_slippage_bps, self.transfer_cost_bps)
        if any(value < 0 for value in values):
            raise ValueError("Costs cannot be negative.")


@dataclass(frozen=True)
class ArbitrageOpportunity:
    symbol: str
    buy_exchange: str
    sell_exchange: str
    buy_price: float
    sell_price: float
    gross_edge_bps: float
    estimated_cost_bps: float
    net_edge_bps: float
    max_notional_at_top_of_book: float
    mode: str = "PAPER_ONLY"


def quote_age_seconds(quote: ExchangeQuote, *, now: datetime | None = None) -> float:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("Current time must be timezone-aware.")
    return max(0.0, (current - quote.timestamp).total_seconds())


def scan_arbitrage(
    quotes: list[ExchangeQuote],
    costs_by_exchange: dict[str, tuple[float, float]],
    *,
    now: datetime | None = None,
    max_quote_age_seconds: float = 2.0,
    min_net_edge_bps: float = 10.0,
    max_notional: float = 20.0,
) -> list[ArbitrageOpportunity]:
    """Return paper opportunities sorted by net edge; never creates orders.

    costs_by_exchange maps exchange -> (maker/taker fee bps); the taker fee is
    used conservatively for both sides. A caller must supply current fee estimates.
    """
    if max_quote_age_seconds <= 0 or min_net_edge_bps < 0 or max_notional <= 0:
        raise ValueError("Scanner limits are invalid.")
    current = now or datetime.now(timezone.utc)
    fresh = [q for q in quotes if quote_age_seconds(q, now=current) <= max_quote_age_seconds]
    opportunities: list[ArbitrageOpportunity] = []
    for buy, sell in permutations(fresh, 2):
        if buy.symbol != sell.symbol or buy.exchange == sell.exchange:
            continue
        if buy.ask_size <= 0 or sell.bid_size <= 0:
            continue
        if buy.ask >= sell.bid:
            continue
        if buy.exchange not in costs_by_exchange or sell.exchange not in costs_by_exchange:
            continue
        buy_fee = costs_by_exchange[buy.exchange][1]
        sell_fee = costs_by_exchange[sell.exchange][1]
        gross = (sell.bid - buy.ask) / buy.ask * 10_000
        # Conservative placeholder until order-book depth/slippage models are connected.
        estimated_slippage = 5.0
        total_costs = buy_fee + sell_fee + estimated_slippage
        net = gross - total_costs
        notional = min(max_notional, buy.ask * buy.ask_size, sell.bid * sell.bid_size)
        if net < min_net_edge_bps or notional <= 0:
            continue
        opportunities.append(ArbitrageOpportunity(
            symbol=buy.symbol,
            buy_exchange=buy.exchange,
            sell_exchange=sell.exchange,
            buy_price=buy.ask,
            sell_price=sell.bid,
            gross_edge_bps=round(gross, 4),
            estimated_cost_bps=round(total_costs, 4),
            net_edge_bps=round(net, 4),
            max_notional_at_top_of_book=round(notional, 8),
        ))
    return sorted(opportunities, key=lambda item: item.net_edge_bps, reverse=True)
