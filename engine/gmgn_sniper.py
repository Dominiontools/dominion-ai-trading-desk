"""Paper-only GMGN sniper candidate screening.

This component ranks evidence for human review. It never places orders and
never labels a token safe.
"""
from __future__ import annotations


class GMGNSniperAgent:
    def __init__(self, *, min_liquidity_usd: float = 10_000.0, max_rug_ratio: float = 0.3):
        if min_liquidity_usd <= 0 or not 0 <= max_rug_ratio <= 1:
            raise ValueError("Invalid GMGN sniper screening thresholds.")
        self.min_liquidity_usd = float(min_liquidity_usd)
        self.max_rug_ratio = float(max_rug_ratio)

    def rank(self, tokens: list[dict], security_checks: list[dict]) -> dict:
        checks = {
            str(item.get("token_address", "")).lower(): item.get("assessment", {})
            for item in security_checks
            if item.get("token_address")
        }
        candidates = []
        for token in tokens[:80]:
            address = str(token.get("token_address", "")).strip()
            symbol = str(token.get("symbol", "UNKNOWN"))[:32]
            try:
                liquidity = float(token.get("liquidity"))
            except (TypeError, ValueError):
                liquidity = None
            try:
                rug_ratio = float(token.get("rug_ratio"))
            except (TypeError, ValueError):
                rug_ratio = None

            reasons = []
            if liquidity is None:
                reasons.append("LIQUIDITY_UNKNOWN")
            elif liquidity < self.min_liquidity_usd:
                reasons.append("LIQUIDITY_BELOW_10000_USD")
            if rug_ratio is None:
                reasons.append("RUG_RATIO_UNKNOWN")
            elif rug_ratio > self.max_rug_ratio:
                reasons.append("GMGN_RUG_RATIO_ABOVE_0_3")

            assessment = checks.get(address.lower(), {})
            if not assessment:
                reasons.append("SECURITY_CHECK_PENDING")
            else:
                if assessment.get("risk_flags"):
                    reasons.extend(str(flag) for flag in assessment["risk_flags"][:10])
                if assessment.get("status") != "NO_EXPLICIT_FLAGS":
                    reasons.append("SECURITY_EVIDENCE_NOT_COMPLETE")
                if assessment.get("unknown_fields"):
                    reasons.append("SECURITY_FIELDS_UNKNOWN")

            ready = not reasons
            candidates.append({
                "symbol": symbol,
                "chain": str(token.get("chain", "sol")),
                "token_address": address,
                "liquidity_usd": liquidity,
                "rug_ratio": rug_ratio,
                "status": "PAPER_REVIEW_CANDIDATE" if ready else "BLOCKED",
                "reasons": sorted(set(reasons)),
                "execution_enabled": False,
            })

        ready = [item for item in candidates if item["status"] == "PAPER_REVIEW_CANDIDATE"]
        return {
            "status": "PAPER_REVIEW_CANDIDATES" if ready else "NO_QUALIFIED_CANDIDATES",
            "candidate_count": len(ready),
            "blocked_count": len(candidates) - len(ready),
            "candidates": ready[:10],
            "blocked": [item for item in candidates if item["status"] == "BLOCKED"][:10],
            "execution_enabled": False,
            "detail": "Candidates require complete GMGN security evidence, at least $10,000 reported liquidity and rug_ratio no higher than 0.3. This is a paper-review filter, not a safety guarantee or trade signal.",
        }
