from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from engine.binance_signal_router import BinanceTestnetSignalRouter
from engine.risk_execution import SpotRiskContext, VerifiedFees


class FakeRulesClient:
    allow_orders = True

    def __init__(self):
        self.exchange_info_calls = 0

    def exchange_info(self, symbol):
        self.exchange_info_calls += 1
        return {"symbols": [{
            "symbol": symbol, "status": "TRADING",
            "filters": [
                {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
                {"filterType": "LOT_SIZE", "stepSize": "0.001",
                 "minQty": "0.001", "maxQty": "1000"},
                {"filterType": "MIN_NOTIONAL", "minNotional": "5"},
            ],
        }]}


class FakeLifecycle:
    def __init__(self, protected=True):
        self.calls = []
        self.protected = protected

    def submit_and_verify(self, plan, *, list_client_order_id):
        self.calls.append((plan, list_client_order_id))
        return {
            "status": "PROTECTED" if self.protected else "PROTECTION_UNCONFIRMED",
            "protected": self.protected, "halted": not self.protected,
            "operator_action_required": not self.protected,
        }


def fixtures(now=None):
    now = now or datetime.now(timezone.utc)
    client = FakeRulesClient()
    lifecycle = FakeLifecycle()
    router = BinanceTestnetSignalRouter(client, lifecycle)
    setup = SimpleNamespace(
        market="CRYPTO", side="BUY", symbol="BTCUSDT",
        stop_loss=99.0, target_2r=102.0,
    )
    from engine.crypto_arbitrage import ExchangeQuote
    quote = ExchangeQuote(
        exchange="Binance", symbol="BTCUSDT", bid=99.99, ask=100.01,
        timestamp=now,
    )
    context = SpotRiskContext(
        equity_quote=1000, available_quote=1000,
        daily_loss_quote=0, open_positions=0,
    )
    fees = VerifiedFees(taker_fee_bps=10, verified=True)
    return router, client, lifecycle, setup, quote, context, fees, now


def test_validated_buy_setup_becomes_risk_sized_protected_testnet_plan():
    router, client, lifecycle, setup, quote, context, fees, now = fixtures()
    result = router.submit_setup(
        setup, quote, context=context, fees=fees,
        account_snapshot_verified=True, daily_loss_verified=True,
        list_client_order_id="dominion123", now=now,
    )
    assert result["environment"] == "BINANCE_SPOT_TESTNET"
    assert result["status"] == "PROTECTED"
    assert result["protected"] is True
    assert result["plan"]["quantity"]
    assert result["plan"]["stop_loss"] == "99.0"
    assert result["plan"]["take_profit"] == "102.0"
    assert client.exchange_info_calls == 1
    assert len(lifecycle.calls) == 1
    assert lifecycle.calls[0][1] == "dominion123"


@pytest.mark.parametrize("verified", [False, True])
def test_router_requires_both_account_and_daily_loss_verification(verified):
    router, client, lifecycle, setup, quote, context, fees, now = fixtures()
    with pytest.raises(PermissionError, match="Verified account balance"):
        router.submit_setup(
            setup, quote, context=context, fees=fees,
            account_snapshot_verified=verified,
            daily_loss_verified=False, now=now,
        )
    assert client.exchange_info_calls == 0
    assert lifecycle.calls == []


def test_router_rejects_stale_binance_quote():
    now = datetime.now(timezone.utc)
    router, client, lifecycle, setup, quote, context, fees, _ = fixtures(now)
    from dataclasses import replace
    stale = replace(quote, timestamp=now - timedelta(seconds=10))
    with pytest.raises(PermissionError, match="stale"):
        router.submit_setup(
            setup, stale, context=context, fees=fees,
            account_snapshot_verified=True, daily_loss_verified=True,
            now=now,
        )
    assert lifecycle.calls == []


def test_router_rejects_sell_and_non_crypto_setups():
    router, client, lifecycle, setup, quote, context, fees, now = fixtures()
    setup.side = "SELL"
    with pytest.raises(PermissionError, match="BUY"):
        router.submit_setup(
            setup, quote, context=context, fees=fees,
            account_snapshot_verified=True, daily_loss_verified=True, now=now,
        )
    setup.side = "BUY"
    setup.market = "FOREX"
    with pytest.raises(PermissionError, match="crypto Spot"):
        router.submit_setup(
            setup, quote, context=context, fees=fees,
            account_snapshot_verified=True, daily_loss_verified=True, now=now,
        )
    assert client.exchange_info_calls == 0
    assert lifecycle.calls == []


def test_router_rejects_open_position_through_shared_risk_gate():
    router, client, lifecycle, setup, quote, context, fees, now = fixtures()
    from dataclasses import replace
    context = replace(context, open_positions=1)
    with pytest.raises(PermissionError, match="open-position"):
        router.submit_setup(
            setup, quote, context=context, fees=fees,
            account_snapshot_verified=True, daily_loss_verified=True, now=now,
        )
    assert lifecycle.calls == []


def test_router_never_reports_protected_when_lifecycle_cannot_confirm_it():
    router, client, lifecycle, setup, quote, context, fees, now = fixtures()
    lifecycle.protected = False
    result = router.submit_setup(
        setup, quote, context=context, fees=fees,
        account_snapshot_verified=True, daily_loss_verified=True, now=now,
    )
    assert result["protected"] is False
    assert result["halted"] is True
    assert result["operator_action_required"] is True



def test_router_refuses_to_route_when_testnet_order_gate_is_disabled():
    router, client, lifecycle, setup, quote, context, fees, now = fixtures()
    client.allow_orders = False
    with pytest.raises(PermissionError, match="order gate is disabled"):
        router.submit_setup(
            setup, quote, context=context, fees=fees,
            account_snapshot_verified=True, daily_loss_verified=True, now=now,
        )
    assert client.exchange_info_calls == 0
    assert lifecycle.calls == []


def test_router_accepts_only_verified_snapshot_object():
    from types import SimpleNamespace
    router, client, lifecycle, setup, quote, context, fees, now = fixtures()
    snapshot = SimpleNamespace(
        context=context,
        account_snapshot_verified=True,
        daily_loss_verified=True,
    )
    result = router.submit_verified_setup(
        setup, quote, snapshot=snapshot, fees=fees,
        list_client_order_id="dominion321", now=now,
    )
    assert result["protected"] is True
    assert lifecycle.calls[0][1] == "dominion321"
