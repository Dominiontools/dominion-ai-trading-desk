"""Truthful checklist of integration gates for the trading desk.

External approvals, credentials, and on-device validation are never inferred.
All execution remains disabled until the required gates are explicitly verified.
"""
from __future__ import annotations


def build_readiness(
    *,
    phone_engine_running: bool = False,
    phone_device_validated: bool = False,
    spotware_approved: bool = False,
    ctrader_demo_authorized: bool = False,
    ctrader_demo_orders_verified: bool = False,
    crypto_testnet_authorized: bool = False,
    crypto_testnet_orders_verified: bool = False,
    verified_fee_exchanges: tuple[str, ...] = (),
    agent_workflow_verified: bool = False,
) -> dict:
    """Return the next actionable integration tasks without claiming completion."""
    tasks = [
        {
            "id": "phone_install",
            "title": "Install and validate the Android app on the phone",
            "status": "ENGINE_RUNNING_AWAITING_DEVICE_CHECK" if phone_engine_running and not phone_device_validated
                      else "VERIFIED" if phone_device_validated else "AWAITING_USER_TEST",
            "detail": "Confirm the foreground service stays active, public feeds update, and paper entries/exits persist after an app restart.",
            "owner": "USER_DEVICE_TEST",
        },
        {
            "id": "spotware_approval",
            "title": "Spotware approval for the cTrader application",
            "status": "APPROVED" if spotware_approved else "BLOCKED_EXTERNAL_APPROVAL",
            "detail": "The existing cTrader application must be approved before account authorization and trading scope can be used.",
            "owner": "SPOTWARE",
        },
        {
            "id": "pepperstone_demo",
            "title": "Authorize the Pepperstone cTrader demo account",
            "status": "AUTHORIZED" if ctrader_demo_authorized else "BLOCKED_APPROVAL_AND_USER_AUTH",
            "detail": "Requires Spotware approval, the correct account/trading scopes, and your explicit demo-account authorization.",
            "owner": "USER_AND_CTRADER",
        },
        {
            "id": "ctrader_demo_orders",
            "title": "Verify demo orders, stop-loss, take-profit and position closing",
            "status": "VERIFIED" if ctrader_demo_orders_verified else "NOT_TESTED",
            "detail": "Must be tested against the authorized Pepperstone demo account; no live account or live orders are permitted in this stage.",
            "owner": "DEVELOPMENT_AND_DEMO_TEST",
        },
        {
            "id": "crypto_testnet",
            "title": "Connect exchange testnet accounts and verify test orders",
            "status": "ORDERS_VERIFIED" if crypto_testnet_orders_verified
                      else "AUTHORIZED_NOT_TESTED" if crypto_testnet_authorized
                      else "NOT_CONNECTED",
            "detail": "Separate exchange testnet credentials and exchange-specific order adapters are required. Public market feeds do not authorize trading.",
            "owner": "USER_CREDENTIALS_AND_DEVELOPMENT",
        },
        {
            "id": "fees",
            "title": "Configure verified exchange fees and execution costs",
            "status": "VERIFIED" if {"Binance", "Bitget", "HTX"}.issubset(set(verified_fee_exchanges))
                      else "INCOMPLETE",
            "detail": "Use the actual account tier, maker/taker fees and withdrawal/network costs where relevant. Unknown fees block profitability claims.",
            "owner": "USER_CONFIGURATION",
        },
        {
            "id": "agent_execution",
            "title": "Connect all specialist agents to validated execution and exit workflows",
            "status": "VERIFIED" if agent_workflow_verified else "BLOCKED_UNTIL_DEMO_EXECUTION",
            "detail": "Scanner, risk, sniper, whale, rug, exit, hype and desk manager are not all autonomous execution agents yet.",
            "owner": "DEVELOPMENT",
        },
        {
            "id": "live_safety",
            "title": "Live-money trading authorization",
            "status": "LOCKED",
            "detail": "Live mode remains disabled. It requires separate explicit approval after successful demo testing and a fresh safety review.",
            "owner": "USER_APPROVAL_REQUIRED",
        },
    ]
    verified = sum(task["status"] in {"VERIFIED", "APPROVED", "AUTHORIZED", "ORDERS_VERIFIED"}
                   for task in tasks)
    return {
        "schema_version": 1,
        "overall_status": "NOT_COMPLETE" if any(
            task["status"] not in {"VERIFIED", "APPROVED", "AUTHORIZED", "ORDERS_VERIFIED", "LOCKED"}
            for task in tasks
        ) else "READY_FOR_FINAL_REVIEW",
        "verified_tasks": verified,
        "total_tasks": len(tasks),
        "execution_mode": "PAPER_ONLY",
        "live_trading_enabled": False,
        "tasks": tasks,
    }
