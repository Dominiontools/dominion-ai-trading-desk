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
        verified_fee_exchanges=("Binance", "Bitget", "HTX", "OKX"),
        agent_workflow_verified=True,
        gmgn_read_only_status="CONNECTED",
    )
    assert result["overall_status"] == "READY_FOR_FINAL_REVIEW"
    assert result["live_trading_enabled"] is False


def test_gmgn_readiness_requires_a_successful_official_read_only_connection():
    missing = build_readiness()
    failed = build_readiness(gmgn_read_only_status="API_ERROR")
    connected = build_readiness(gmgn_read_only_status="CONNECTED")
    verifying = build_readiness(gmgn_read_only_status="READY_TO_CONNECT")
    limited = build_readiness(gmgn_read_only_status="RATE_LIMITED")
    plan_blocked = build_readiness(gmgn_read_only_status="PLAN_UPGRADE_REQUIRED")
    assert next(x for x in missing["tasks"] if x["id"] == "gmgn_read_only")["status"] == "NEEDS_API_KEY"
    assert next(x for x in limited["tasks"] if x["id"] == "gmgn_read_only")["status"] == "RATE_LIMITED"
    assert next(x for x in plan_blocked["tasks"] if x["id"] == "gmgn_read_only")["status"] == "PLAN_UPGRADE_REQUIRED"
    assert next(x for x in verifying["tasks"] if x["id"] == "gmgn_read_only")["status"] == "VERIFYING"
    assert next(x for x in failed["tasks"] if x["id"] == "gmgn_read_only")["status"] == "API_ERROR"
    assert next(x for x in connected["tasks"] if x["id"] == "gmgn_read_only")["status"] == "VERIFIED"



def test_fee_readiness_requires_every_enabled_public_exchange():
    partial = build_readiness(
        verified_fee_exchanges=("Binance", "Bitget", "HTX")
    )
    complete = build_readiness(
        verified_fee_exchanges=("Binance", "Bitget", "HTX", "OKX")
    )
    assert next(x for x in partial["tasks"] if x["id"] == "fees")["status"] == "INCOMPLETE"
    assert next(x for x in complete["tasks"] if x["id"] == "fees")["status"] == "VERIFIED"
