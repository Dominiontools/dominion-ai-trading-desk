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
        ctrader_partial_close_verified=True,
        crypto_testnet_authorized=True,
        crypto_testnet_orders_verified=True,
        binance_emergency_handling_verified=True,
        verified_fee_exchanges=("Binance", "Bitget", "HTX", "OKX"),
        agent_workflow_verified=True,
    )
    assert result["overall_status"] == "READY_FOR_FINAL_REVIEW"
    assert result["live_trading_enabled"] is False


def test_fee_readiness_requires_every_enabled_public_exchange():
    partial = build_readiness(
        verified_fee_exchanges=("Binance", "Bitget", "HTX")
    )
    complete = build_readiness(
        verified_fee_exchanges=("Binance", "Bitget", "HTX", "OKX")
    )
    assert next(x for x in partial["tasks"] if x["id"] == "fees")["status"] == "INCOMPLETE"
    assert next(x for x in complete["tasks"] if x["id"] == "fees")["status"] == "VERIFIED"



def test_crypto_readiness_describes_verified_context_but_not_enabled_execution():
    result = build_readiness()
    crypto = next(task for task in result["tasks"] if task["id"] == "crypto_testnet")
    assert crypto["status"] == "BINANCE_ROUTER_AND_RISK_CONTEXT_READY_TESTNET_EXECUTION_PENDING"
    assert "daily-loss ledger" in crypto["detail"]
    assert "wired into the Android strategy loop" in crypto["detail"]
    assert "off-by-default Testnet automation setting" in crypto["detail"]
    assert result["live_trading_enabled"] is False



def test_binance_emergency_handling_is_a_required_final_acceptance_gate():
    result = build_readiness()
    task = next(x for x in result["tasks"] if x["id"] == "binance_emergency_handling")
    assert task["status"] == "IMPLEMENTED_TESTS_PASSED_TESTNET_VERIFICATION_PENDING"
    assert "emergency market-close path is implemented" in task["detail"]
    assert result["overall_status"] == "NOT_COMPLETE"

    verified = build_readiness(binance_emergency_handling_verified=True)
    task = next(x for x in verified["tasks"] if x["id"] == "binance_emergency_handling")
    assert task["status"] == "VERIFIED"

def test_ctrader_partial_close_requires_broker_demo_verification():
    result = build_readiness()
    task = next(x for x in result["tasks"] if x["id"] == "ctrader_partial_close")
    assert task["status"] == "NOT_TESTED"
    assert result["overall_status"] == "NOT_COMPLETE"
    verified = build_readiness(ctrader_partial_close_verified=True)
    task = next(x for x in verified["tasks"] if x["id"] == "ctrader_partial_close")
    assert task["status"] == "VERIFIED"




def test_cross_exchange_scanner_is_a_separate_readiness_gate():
    pending = build_readiness()
    scanner = next(task for task in pending["tasks"] if task["id"] == "cross_exchange_scan")
    assert scanner["status"] == "PARTIAL_FEEDS_OR_FEES_PENDING"
    assert pending["total_tasks"] == 11

    verified = build_readiness(cross_exchange_scan_verified=True)
    scanner = next(task for task in verified["tasks"] if task["id"] == "cross_exchange_scan")
    assert scanner["status"] == "VERIFIED"
    assert verified["live_trading_enabled"] is False
