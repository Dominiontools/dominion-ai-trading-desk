import pytest
from engine.safety import RiskConfig, assert_demo_only, validate_risk

def test_default_config_is_demo_only():
    assert_demo_only(RiskConfig())

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
