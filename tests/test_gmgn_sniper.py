from engine.gmgn_sniper import GMGNSniperAgent


def test_gmgn_sniper_only_surfaces_tokens_with_complete_security_and_liquidity():
    agent = GMGNSniperAgent()
    tokens = [
        {"symbol": "READY", "chain": "sol", "token_address": "A" * 32,
         "liquidity": 25000, "rug_ratio": 0.12},
        {"symbol": "LOWLIQ", "chain": "sol", "token_address": "B" * 32,
         "liquidity": 5000, "rug_ratio": 0.1},
        {"symbol": "HIGH RUG", "chain": "sol", "token_address": "C" * 32,
         "liquidity": 50000, "rug_ratio": 0.5},
        {"symbol": "UNKNOWN", "chain": "sol", "token_address": "D" * 32,
         "liquidity": 50000},
    ]
    checks = [{
        "token_address": "A" * 32,
        "assessment": {
            "status": "NO_EXPLICIT_FLAGS",
            "risk_flags": [],
            "unknown_fields": [],
        },
    }]
    result = agent.rank(tokens, checks)
    assert result["candidate_count"] == 1
    assert result["candidates"][0]["symbol"] == "READY"
    assert result["candidates"][0]["execution_enabled"] is False
    assert result["blocked_count"] == 3
    assert "LIQUIDITY_BELOW_10000_USD" in result["blocked"][0]["reasons"]


def test_gmgn_sniper_blocks_missing_security_or_any_explicit_risk_flag():
    agent = GMGNSniperAgent()
    tokens = [
        {"symbol": "PENDING", "token_address": "A" * 32, "liquidity": 50000, "rug_ratio": 0.1},
        {"symbol": "FLAGGED", "token_address": "B" * 32, "liquidity": 50000, "rug_ratio": 0.1},
    ]
    checks = [{
        "token_address": "B" * 32,
        "assessment": {
            "status": "RISK_FLAGS_FOUND",
            "risk_flags": ["GMGN_WASH_TRADING_DETECTED"],
            "unknown_fields": [],
        },
    }]
    result = agent.rank(tokens, checks)
    assert result["candidate_count"] == 0
    assert result["execution_enabled"] is False
    assert all(item["status"] == "BLOCKED" for item in result["blocked"])
