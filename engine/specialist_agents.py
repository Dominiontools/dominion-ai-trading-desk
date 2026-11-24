"""Executable specialist agents for Dominion AI Trading Desk.
All decisions are PAPER_ONLY. No network feeds, broker connections or real orders.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Mapping
from uuid import uuid4
from .positions import SimulatedPosition, evaluate_exit, update_trailing_stop
from .risk import RiskLimits, TradeProposal, evaluate_trade

@dataclass(frozen=True)
class AgentResult:
    agent: str
    status: str
    summary: str
    findings: tuple[str, ...] = ()
    mode: str = "PAPER_ONLY"

class WhaleAgent:
    """Flags large trades in a supplied timestamped trade sample."""
    def __init__(self, min_notional_usd: float = 100_000.0):
        if min_notional_usd <= 0: raise ValueError("Whale threshold must be positive.")
        self.min_notional_usd = min_notional_usd
    def analyze(self, trades: Iterable[Mapping]) -> AgentResult:
        alerts = []
        for trade in trades:
            try:
                symbol, side = str(trade["symbol"]).strip().upper(), str(trade["side"]).upper()
                notional = float(trade["notional_usd"])
                stamp = datetime.fromisoformat(str(trade["timestamp"]).replace("Z", "+00:00"))
                if not symbol or side not in {"BUY", "SELL"} or notional <= 0 or stamp.tzinfo is None: continue
                if (datetime.now(timezone.utc) - stamp.astimezone(timezone.utc)).total_seconds() < -5: continue
                if notional >= self.min_notional_usd:
                    alerts.append(f"{symbol} {side} USD {notional:,.0f} at {stamp.isoformat()}")
            except (KeyError, TypeError, ValueError, OverflowError): continue
        return AgentResult("WHALE", "ANALYSED" if alerts else "NO_ALERT",
                           f"{len(alerts)} large-trade alert(s) in supplied sample.", tuple(alerts))

@dataclass(frozen=True)
class RugAssessment:
    status: str
    score: int | None
    allowed_for_paper_review: bool
    findings: tuple[str, ...]
    mode: str = "PAPER_ONLY"

class RugAgent:
    """Conservative checklist scorer; missing evidence blocks clearance."""
    REQUIRED = ("liquidity_usd", "liquidity_locked", "contract_verified",
                "mint_authority_disabled", "freeze_authority_disabled",
                "top_holder_pct", "honeypot_check_passed")
    def assess(self, evidence: Mapping) -> RugAssessment:
        missing = [k for k in self.REQUIRED if k not in evidence or evidence[k] is None]
        if missing:
            return RugAssessment("INSUFFICIENT_EVIDENCE", None, False,
                                 tuple(f"Missing: {k}" for k in missing))
        try:
            liquidity, top_holder = float(evidence["liquidity_usd"]), float(evidence["top_holder_pct"])
        except (TypeError, ValueError):
            return RugAssessment("INSUFFICIENT_EVIDENCE", None, False, ("Invalid liquidity or holder data.",))
        if liquidity < 0 or not 0 <= top_holder <= 100:
            return RugAssessment("INSUFFICIENT_EVIDENCE", None, False, ("Out-of-range evidence.",))
        checks = (
            (liquidity >= 25_000, 20, "Liquidity is at least USD 25,000."),
            (bool(evidence["liquidity_locked"]), 20, "Liquidity is reported locked."),
            (bool(evidence["contract_verified"]), 15, "Contract is verified."),
            (bool(evidence["mint_authority_disabled"]), 15, "Mint authority is disabled."),
            (bool(evidence["freeze_authority_disabled"]), 10, "Freeze authority is disabled."),
            (top_holder <= 20, 10, "Largest holder is at most 20%."),
            (bool(evidence["honeypot_check_passed"]), 10, "Honeypot check passed."),
        )
        score, findings = 0, []
        for passed, points, message in checks:
            if passed: score += points; findings.append(message)
            else: findings.append("FAILED: " + message)
        severe = liquidity < 5_000 or not evidence["honeypot_check_passed"] or not evidence["liquidity_locked"] or top_holder > 50
        allowed = score >= 80 and not severe
        return RugAssessment("LOWER_CHECKLIST_RISK" if allowed else "HIGH_OR_UNRESOLVED_RISK",
                             score, allowed, tuple(findings))

class HypeAgent:
    """Keyword sentiment baseline over supplied text, not an internet feed."""
    POSITIVE = {"bullish", "breakout", "adoption", "partnership", "growth", "launch", "strong"}
    NEGATIVE = {"bearish", "scam", "hack", "exploit", "dump", "rug", "lawsuit", "delist"}
    def score(self, posts: Iterable[Mapping]) -> AgentResult:
        positive = negative = 0.0
        count = 0
        for post in posts:
            text = str(post.get("text", "")).lower()
            if not text.strip(): continue
            try: weight = min(5.0, max(0.25, float(post.get("weight", 1.0))))
            except (TypeError, ValueError): continue
            words = {w.strip(".,!?#$") for w in text.split()}
            positive += len(words & self.POSITIVE) * weight
            negative += len(words & self.NEGATIVE) * weight
            count += 1
        if not count: return AgentResult("HYPE", "NO_DATA", "No usable posts were supplied.")
        score = (positive - negative) / max(1.0, positive + negative) * 100
        label = "POSITIVE" if score >= 20 else "NEGATIVE" if score <= -20 else "MIXED_OR_NEUTRAL"
        return AgentResult("HYPE", "ANALYSED", f"{label}: keyword score {score:.1f}/100 from {count} supplied posts.",
                           (f"positive_weight={positive:.2f}", f"negative_weight={negative:.2f}",
                            "Keyword baseline only; not a prediction or verified social trend."))

class ExitAgent:
    """Evaluates simulated positions and tightens trailing stops only."""
    def evaluate(self, positions: Iterable[SimulatedPosition], prices: Mapping[str, float]) -> tuple[dict, ...]:
        results = []
        for position in positions:
            if position.status != "OPEN": continue
            if position.symbol not in prices:
                results.append({"position_id": position.position_id, "status": "BLOCKED",
                                "reason": "CURRENT_PRICE_MISSING", "mode": "PAPER_ONLY"})
                continue
            price = float(prices[position.symbol])
            updated = update_trailing_stop(position, price)
            decision = evaluate_exit(updated, price)
            results.append({"position_id": position.position_id,
                            "status": "CLOSE_SIGNAL" if decision.should_close else "HOLD",
                            "reason": decision.reason, "updated_stop_loss": updated.stop_loss,
                            "exit_price": decision.exit_price, "mode": "PAPER_ONLY"})
        return tuple(results)

@dataclass(frozen=True)
class PaperOrder:
    order_id: str
    symbol: str
    side: str
    entry_price: float
    stop_loss: float
    take_profit: float
    risk_amount: float
    status: str = "PAPER_ACCEPTED"
    mode: str = "PAPER_ONLY"
    broker_order_sent: bool = False

class SniperAgent:
    """Creates paper order proposals only after the shared risk gate approves."""
    def __init__(self, limits: RiskLimits | None = None):
        self.limits = limits or RiskLimits()
    def review(self, *, symbol: str, market: str, side: str, entry_price: float,
               stop_loss: float, take_profit: float, quantity: float, equity: float,
               daily_loss_pct: float, open_positions: int, spread_bps: float,
               estimated_slippage_bps: float, quote_age_seconds: float,
               emergency_stop: bool = False) -> tuple[PaperOrder | None, AgentResult]:
        if side not in {"BUY", "SELL"} or min(entry_price, stop_loss, take_profit, quantity) <= 0:
            return None, AgentResult("SNIPER", "BLOCKED", "Invalid order parameters.")
        if side == "BUY" and not stop_loss < entry_price < take_profit:
            return None, AgentResult("SNIPER", "BLOCKED", "BUY requires stop < entry < target.")
        if side == "SELL" and not take_profit < entry_price < stop_loss:
            return None, AgentResult("SNIPER", "BLOCKED", "SELL requires target < entry < stop.")
        risk_amount = abs(entry_price - stop_loss) * quantity
        proposal = TradeProposal(market, risk_amount, equity, daily_loss_pct, open_positions,
                                 spread_bps, estimated_slippage_bps, quote_age_seconds, emergency_stop)
        decision = evaluate_trade(proposal, self.limits)
        if not decision.approved:
            return None, AgentResult("SNIPER", "BLOCKED", "Risk gate rejected paper order.", decision.reasons)
        order = PaperOrder(str(uuid4()), symbol.upper(), side, entry_price, stop_loss, take_profit, risk_amount)
        return order, AgentResult("SNIPER", "PAPER_ACCEPTED",
                                  "Risk-approved paper proposal created; no broker order sent.")

class DeskCoordinator:
    """Coordinates specialist checks using caller-supplied evidence."""
    def __init__(self):
        self.whale, self.rug, self.hype, self.exit = WhaleAgent(), RugAgent(), HypeAgent(), ExitAgent()
        self.sniper = SniperAgent()
    def analyse(self, *, trades=(), rug_evidence: Mapping | None = None,
                posts=(), positions=(), prices: Mapping | None = None) -> dict:
        whale, hype = self.whale.analyze(trades), self.hype.score(posts)
        rug = self.rug.assess(rug_evidence) if rug_evidence is not None else RugAssessment(
            "WAITING_FOR_EVIDENCE", None, False, ("No token safety evidence supplied.",))
        exits = self.exit.evaluate(positions, prices or {})
        return {"mode": "PAPER_ONLY", "orders_enabled": False, "agents": {
            "WHALE": {"status": whale.status, "summary": whale.summary, "findings": list(whale.findings)},
            "RUG": {"status": rug.status, "score": rug.score,
                    "allowed_for_paper_review": rug.allowed_for_paper_review, "findings": list(rug.findings)},
            "HYPE": {"status": hype.status, "summary": hype.summary, "findings": list(hype.findings)},
            "EXIT": {"status": "ANALYSED" if exits else "NO_OPEN_POSITIONS", "results": list(exits)}}}
