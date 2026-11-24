from engine.readiness import build_readiness


def test_readiness_never_enables_live_trading_by_default():
    result = build_readiness()
    assert result["overall_status"] == "NOT_COMPLETE"
    assert result["execution_mode"] == "PAPER_ONLY"
    assert result["live_trading_enabled"] is False
    assert next(x for x in result["tasks"] if x["id"] == "live_safety")["status"] == "LOCKED"


def test_external_approval_and_demo_authorization_are_separate_gates():
    result = build_readiness(spotware_approved=True)
    tasks = {x["id"]: x for x in result["tasks"]}
    assert tasks["spotware_approval"]["status"] == "APPROVED"
    assert tasks["pepperstone_demo"]["status"] == "BLOCKED_APPROVAL_AND_USER_AUTH"


def test_demo_order_verification_does_not_unlock_live_mode():
    result = build_readiness(
        phone_device_validated=True,
        spotware_approved=True,
        ctrader_demo_authorized=True,
        ctrader_demo_orders_verified=True,
        crypto_testnet_authorized=True,
        crypto_testnet_orders_verified=True,
        verified_fee_exchanges=("Binance", "Bitget", "HTX"),
    )
    assert result["overall_status"] == "READY_FOR_FINAL_REVIEW"
    assert result["live_trading_enabled"] is False
