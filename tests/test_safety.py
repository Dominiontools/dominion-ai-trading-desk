import pytest
from engine.safety import RiskConfig, assert_demo_only, validate_risk

def test_default_config_is_demo_only_and_uses_project_limits():
    config = RiskConfig()
    assert_demo_only(config)
    assert config.max_risk_per_trade_pct == 0.5
    assert config.max_daily_loss_pct == 2.0
    assert config.max_open_positions == 1
    assert config.max_slippage_pct == 0.15

def test_live_mode_is_rejected():
    with pytest.raises(RuntimeError):
        assert_demo_only(RiskConfig(demo_only=False, live_trading_enabled=True))

def test_risk_accepts_safe_simulated_candidate():
    ok, _ = validate_risk(RiskConfig(), 0.25, 0, 0.2, 0.05)
    assert ok

def test_risk_rejects_excessive_risk():
    ok, reason = validate_risk(RiskConfig(), 1.0, 0, 0.2, 0.05)
    assert not ok and "risk" in reason.lower()

def test_risk_rejects_daily_loss_limit():
    ok, reason = validate_risk(RiskConfig(), 0.25, 0, 2.0, 0.05)
    assert not ok and "daily loss" in reason.lower()

def test_risk_rejects_second_concurrent_position():
    ok, reason = validate_risk(RiskConfig(), 0.25, 1, 0.0, 0.05)
    assert not ok and "maximum open positions" in reason.lower()

def test_risk_rejects_slippage_above_fifteen_basis_points():
    ok, reason = validate_risk(RiskConfig(), 0.25, 0, 0.0, 0.16)
    assert not ok and "slippage" in reason.lower()
