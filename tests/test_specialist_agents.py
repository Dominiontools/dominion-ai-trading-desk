from datetime import datetime, timezone
from engine.specialist_agents import DeskCoordinator, HypeAgent, RugAgent, SniperAgent, WhaleAgent
from engine.positions import SimulatedPosition

def test_whale_agent_flags_large_recent_trade():
    result = WhaleAgent(100_000).analyze([{"symbol":"BTCUSDT","side":"BUY","notional_usd":150_000,"timestamp":datetime.now(timezone.utc).isoformat()}])
    assert result.status == "ANALYSED" and "BTCUSDT BUY" in result.findings[0]

def test_whale_agent_ignores_malformed_trade():
    assert WhaleAgent().analyze([{"symbol":"BTC","side":"BUY"}]).status == "NO_ALERT"

def test_rug_agent_blocks_missing_evidence():
    result = RugAgent().assess({"liquidity_usd":100_000})
    assert result.status == "INSUFFICIENT_EVIDENCE" and not result.allowed_for_paper_review

def test_rug_agent_blocks_honeypot():
    evidence = {"liquidity_usd":100_000,"liquidity_locked":True,"contract_verified":True,
      "mint_authority_disabled":True,"freeze_authority_disabled":True,"top_holder_pct":5,"honeypot_check_passed":False}
    result = RugAgent().assess(evidence)
    assert result.status == "HIGH_OR_UNRESOLVED_RISK" and not result.allowed_for_paper_review

def test_rug_agent_accepts_high_checklist_score():
    evidence = {"liquidity_usd":100_000,"liquidity_locked":True,"contract_verified":True,
      "mint_authority_disabled":True,"freeze_authority_disabled":True,"top_holder_pct":5,"honeypot_check_passed":True}
    assert RugAgent().assess(evidence).score == 100

def test_hype_agent_scores_supplied_text():
    result = HypeAgent().score([{"text":"bullish adoption growth breakout"},{"text":"scam hack dump"}])
    assert result.status == "ANALYSED" and "keyword score" in result.summary

def test_sniper_paper_proposal_only_after_risk_approval():
    order, result = SniperAgent().review(symbol="BTCUSDT",market="CRYPTO",side="BUY",
      entry_price=100,stop_loss=99.6,take_profit=101,quantity=0.01,equity=100,
      daily_loss_pct=0,open_positions=0,spread_bps=1,estimated_slippage_bps=1,quote_age_seconds=0.5)
    assert order is not None and order.mode == "PAPER_ONLY" and not order.broker_order_sent
    assert result.status == "PAPER_ACCEPTED"

def test_sniper_blocks_risk_excess():
    order, result = SniperAgent().review(symbol="BTCUSDT",market="CRYPTO",side="BUY",
      entry_price=100,stop_loss=90,take_profit=120,quantity=1,equity=100,
      daily_loss_pct=0,open_positions=0,spread_bps=1,estimated_slippage_bps=1,quote_age_seconds=0.5)
    assert order is None and result.status == "BLOCKED"

def test_exit_agent_in_coordinator():
    position = SimulatedPosition("p1","BTCUSDT","CRYPTO","BUY",100,95,110,1)
    result = DeskCoordinator().analyse(positions=[position],prices={"BTCUSDT":111})
    assert result["agents"]["EXIT"]["results"][0]["status"] == "CLOSE_SIGNAL"
    assert result["orders_enabled"] is False

def test_coordinator_reports_missing_feeds_honestly():
    result = DeskCoordinator().analyse()
    assert result["agents"]["WHALE"]["status"] == "NO_ALERT"
    assert result["agents"]["RUG"]["status"] == "WAITING_FOR_EVIDENCE"
    assert result["agents"]["HYPE"]["status"] == "NO_DATA"
