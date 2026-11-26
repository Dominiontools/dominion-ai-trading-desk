import json
import time
from urllib.request import urlopen

import pytest
import engine.crypto_service as service


class FakeFeeds:
    def __init__(self, timeout=5.0):
        self.timeout = timeout


class FakeMonitor:
    def __init__(self, feeds, **kwargs):
        self.calls = 0

    def poll_once(self, symbol):
        self.calls += 1
        return {"symbol": symbol, "status": "BLOCKED", "reason": "FEE_CONFIG_MISSING"}

    def poll_many_once(self, symbols):
        self.calls += 1
        return {
            "symbol": "MULTI_MARKET", "status": "BLOCKED",
            "reason": "FEE_CONFIG_MISSING", "symbols_requested": len(symbols),
            "symbols_with_two_venues": 0, "quote_count": 0,
        }


class FakeUniverse:
    def __init__(self, timeout=8.0):
        self.timeout = timeout

    def top_usdt_symbols(self, limit=52, min_quote_volume=1_000_000.0):
        return ("BTCUSDT", "ETHUSDT")[:limit]


class FakeCandleFeed:
    def __init__(self, timeout=8.0):
        self.timeout = timeout

    def candles(self, symbol, timeframe="1m", limit=80):
        raise RuntimeError("offline test fixture")


def test_fee_config_uses_public_standard_rates_and_leaves_htx_unconfigured(monkeypatch):
    for name in (
        "DOMINION_FEE_BINANCE_PERSONAL_MAKER_BPS",
        "DOMINION_FEE_BINANCE_PERSONAL_TAKER_BPS",
        "DOMINION_FEE_BINANCE_PERSONAL_VERIFIED",
    ):
        monkeypatch.delenv(name, raising=False)
    assert service._fee_config() == {
        "Binance": (10.0, 10.0),
        "Bitget": (10.0, 10.0),
        "OKX": (8.0, 10.0),
    }


def test_binance_verified_personal_rate_overrides_public_fallback(monkeypatch):
    monkeypatch.setenv("DOMINION_FEE_BINANCE_PERSONAL_MAKER_BPS", "7.5")
    monkeypatch.setenv("DOMINION_FEE_BINANCE_PERSONAL_TAKER_BPS", "8.5")
    monkeypatch.setenv("DOMINION_FEE_BINANCE_PERSONAL_VERIFIED", "YES")
    assert service._fee_config()["Binance"] == (7.5, 8.5)


def test_binance_personal_rate_requires_explicit_verification(monkeypatch):
    monkeypatch.setenv("DOMINION_FEE_BINANCE_PERSONAL_MAKER_BPS", "7.5")
    monkeypatch.setenv("DOMINION_FEE_BINANCE_PERSONAL_TAKER_BPS", "8.5")
    monkeypatch.delenv("DOMINION_FEE_BINANCE_PERSONAL_VERIFIED", raising=False)
    with pytest.raises(RuntimeError, match="PERSONAL_VERIFIED=YES"):
        service._fee_config()


def test_binance_personal_rate_requires_both_maker_and_taker(monkeypatch):
    monkeypatch.setenv("DOMINION_FEE_BINANCE_PERSONAL_MAKER_BPS", "7.5")
    monkeypatch.delenv("DOMINION_FEE_BINANCE_PERSONAL_TAKER_BPS", raising=False)
    with pytest.raises(RuntimeError, match="both"):
        service._fee_config()


def test_binance_personal_rate_rejects_non_finite_values(monkeypatch):
    monkeypatch.setenv("DOMINION_FEE_BINANCE_PERSONAL_MAKER_BPS", "nan")
    monkeypatch.setenv("DOMINION_FEE_BINANCE_PERSONAL_TAKER_BPS", "8")
    monkeypatch.setenv("DOMINION_FEE_BINANCE_PERSONAL_VERIFIED", "YES")
    with pytest.raises(RuntimeError, match="finite"):
        service._fee_config()


def test_positive_float_rejects_zero(monkeypatch):
    monkeypatch.setenv("DOMINION_TEST_INTERVAL", "0")
    with pytest.raises(RuntimeError):
        service._positive_float("DOMINION_TEST_INTERVAL", 5.0)


def test_embedded_service_starts_read_only_api_and_stops(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "PublicCryptoFeeds", FakeFeeds)
    monkeypatch.setattr(service, "CryptoPaperMonitor", FakeMonitor)
    monkeypatch.setattr(service, "BinanceMarketUniverse", FakeUniverse)
    monkeypatch.setattr(service, "BinancePublicCandleFeed", FakeCandleFeed)
    monkeypatch.delenv("DOMINION_FEE_BINANCE_TAKER_BPS", raising=False)
    monkeypatch.delenv("DOMINION_FEE_BITGET_TAKER_BPS", raising=False)
    monkeypatch.delenv("DOMINION_FEE_HTX_TAKER_BPS", raising=False)

    started = service.start_embedded(str(tmp_path), port=0)
    assert started["started"] is True
    assert started["orders_enabled"] is False
    assert started["port"] > 0

    try:
        deadline = time.time() + 2
        status = None
        while time.time() < deadline:
            try:
                with urlopen(f"http://127.0.0.1:{started['port']}/api/crypto/status", timeout=1) as response:
                    status = json.loads(response.read())
                break
            except OSError:
                time.sleep(0.05)
        assert status is not None
        assert status["mode"] == "PAPER_ONLY"
        assert status["orders_enabled"] is False
        assert status["engine"] == "running"
        assert status["paper_trading"]["mode"] == "PAPER_ONLY"
        assert status["paper_trading"]["starting_equity"] == 20.0
        assert status["paper_trading"]["open_position"] is None
        assert status["paper_trading"]["orders_enabled"] is False
        assert status["arbitrage_universe"]["actual_count"] == 2
        assert status["arbitrage_universe"]["status"] == "DYNAMIC_UNDER_52"
        assert status["agents"]["SNIPER"]["status"] == "READY_FOR_VALIDATED_SIGNALS"
    finally:
        stopped = service.stop_embedded()

    assert stopped["stopped"] is True
    assert service.stop_embedded()["already_stopped"] is True


class EmptyDiscovery:
    def __init__(self, timeout=8.0):
        pass

    def discover(self, limit=12):
        return []


class OneSolanaTokenDiscovery:
    def __init__(self, timeout=8.0):
        pass

    def discover(self, limit=12):
        return [{
            "chain_id": "solana", "pair_address": "PoolAddress",
            "token_address": "TokenAddress", "symbol": "TEST",
        }][:limit]


class EmptyWhaleFeed:
    def __init__(self, timeout=8.0, min_notional_usd=100_000.0):
        pass

    def trades(self, network, pool_address, symbol):
        return []


class EmptySecurityFeed:
    def __init__(self, token=None, timeout=8.0):
        pass

    @staticmethod
    def supports_contract(chain, address):
        return False


class EmptyNewsFeed:
    def __init__(self, timeout=8.0):
        pass

    def headlines(self, limit=20):
        return []


def test_embedded_service_exposes_only_safe_binance_recovery_summary(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "PublicCryptoFeeds", FakeFeeds)
    monkeypatch.setattr(service, "CryptoPaperMonitor", FakeMonitor)
    monkeypatch.setattr(service, "BinanceMarketUniverse", FakeUniverse)
    monkeypatch.setattr(service, "BinancePublicCandleFeed", FakeCandleFeed)
    for name in ("DOMINION_FEE_BINANCE_TAKER_BPS", "DOMINION_FEE_BITGET_TAKER_BPS",
                 "DOMINION_FEE_HTX_TAKER_BPS", "DOMINION_FEE_OKX_TAKER_BPS"):
        monkeypatch.delenv(name, raising=False)

    recovery = json.dumps({
        "status": "RECONCILIATION_REQUIRED", "halted": True,
        "reconciled": 2, "unresolved": [{"order_list_id": "secret-order-id"}],
        "operator_action_required": True, "orders_enabled": False,
        "api_secret": "must-not-leak",
        "risk_context": {
            "verified": True, "status": "VERIFIED", "quote_asset": "USDT",
            "equity_quote": "20", "available_quote": "20",
            "actual_equity_quote": "105.00", "risk_capital_cap_quote": "20",
            "daily_loss_quote": "0.25", "open_positions": 0,
            "exchange_open_orders": 0, "journaled_order_lists": 1, "private_payload": "must-not-leak",
        },
    })
    started = service.start_embedded(str(tmp_path), port=0,
                                     binance_recovery_json=recovery)
    try:
        with urlopen(f"http://127.0.0.1:{started['port']}/api/crypto/status", timeout=2) as response:
            status = json.loads(response.read())
        recovery_status = status["binance_testnet_recovery"]
        assert recovery_status == {
            "status": "RECONCILIATION_REQUIRED", "halted": True,
            "reconciled": 2, "unresolved_count": 1,
            "operator_action_required": True, "orders_enabled": False,
            "environment": "BINANCE_SPOT_TESTNET",
        }
        assert "secret-order-id" not in json.dumps(status)
        assert "must-not-leak" not in json.dumps(status)
        assert status["orders_enabled"] is False
        risk = status["binance_testnet_risk_context"]
        assert risk == {
            "verified": True, "status": "VERIFIED", "quote_asset": "USDT",
            "equity_quote": "20", "available_quote": "20",
            "actual_equity_quote": "105.00", "risk_capital_cap_quote": "20",
            "daily_loss_quote": "0.25", "open_positions": 0,
            "exchange_open_orders": 0, "journaled_order_lists": 1, "orders_enabled": False,
            "environment": "BINANCE_SPOT_TESTNET",
        }
    finally:
        service.stop_embedded()


def test_invalid_binance_recovery_payload_is_reported_as_halted(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "PublicCryptoFeeds", FakeFeeds)
    monkeypatch.setattr(service, "CryptoPaperMonitor", FakeMonitor)
    monkeypatch.setattr(service, "BinanceMarketUniverse", FakeUniverse)
    monkeypatch.setattr(service, "BinancePublicCandleFeed", FakeCandleFeed)
    started = service.start_embedded(str(tmp_path), port=0,
                                     binance_recovery_json="{not-json")
    try:
        with urlopen(f"http://127.0.0.1:{started['port']}/api/crypto/status", timeout=2) as response:
            status = json.loads(response.read())
        assert status["binance_testnet_recovery"]["status"] == "RECOVERY_STATUS_INVALID"
        assert status["binance_testnet_recovery"]["halted"] is True
        assert status["binance_testnet_recovery"]["operator_action_required"] is True
    finally:
        service.stop_embedded()



def test_runtime_keeps_testnet_execution_off_without_explicit_enablement(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "PublicCryptoFeeds", FakeFeeds)
    monkeypatch.setattr(service, "CryptoPaperMonitor", FakeMonitor)
    monkeypatch.setattr(service, "BinanceMarketUniverse", FakeUniverse)
    monkeypatch.setattr(service, "BinancePublicCandleFeed", FakeCandleFeed)
    result = service._runtime_config(str(tmp_path), port=0)
    stop_event, server, _monitor, _agents, _strategy, state, *_ = result
    try:
        assert state["mode"] == "PAPER_ONLY"
        assert state["orders_enabled"] is False
        assert state["binance_testnet_execution"]["enabled"] is False
        assert service.os.environ["DOMINION_ENABLE_BINANCE_TESTNET_ORDERS"] == "NO"
    finally:
        stop_event.set()
        server.server_close()


def test_runtime_enables_only_the_explicit_binance_testnet_route(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "PublicCryptoFeeds", FakeFeeds)
    monkeypatch.setattr(service, "CryptoPaperMonitor", FakeMonitor)
    monkeypatch.setattr(service, "BinanceMarketUniverse", FakeUniverse)
    monkeypatch.setattr(service, "BinancePublicCandleFeed", FakeCandleFeed)
    monkeypatch.setattr(service, "DexScreenerDiscovery", EmptyDiscovery)
    monkeypatch.setattr(service, "GeckoTerminalWhaleFeed", EmptyWhaleFeed)
    monkeypatch.setattr(service, "GoPlusSecurityFeed", EmptySecurityFeed)
    monkeypatch.setattr(service, "PublicNewsRSS", EmptyNewsFeed)

    class FakeTestnetClient:
        def __init__(self, api_key, api_secret, *, allow_orders):
            assert api_key == "demo-key"
            assert api_secret == "demo-secret"
            assert allow_orders is True

    class FakeLedger:
        def __init__(self, path):
            self.path = path

    class FakeLifecycle:
        def __init__(self, gate, client, **kwargs):
            assert isinstance(client, FakeTestnetClient)

    class FakeRiskProvider:
        def __init__(self, client, lifecycle, ledger, *, quote_asset):
            assert quote_asset == "USDT"

    class FakeRouter:
        def __init__(self, client, lifecycle, gate):
            assert isinstance(client, FakeTestnetClient)

    monkeypatch.setattr(service, "BinanceSpotTestnetClient", FakeTestnetClient)
    monkeypatch.setattr(service, "BinanceDailyLossLedger", FakeLedger)
    monkeypatch.setattr(service, "BinanceProtectedLifecycle", FakeLifecycle)
    monkeypatch.setattr(service, "BinanceRiskContextProvider", FakeRiskProvider)
    monkeypatch.setattr(service, "BinanceTestnetSignalRouter", FakeRouter)

    result = service._runtime_config(
        str(tmp_path), port=0, binance_api_key="demo-key",
        binance_api_secret="demo-secret", binance_testnet_orders_enabled=True,
    )
    stop_event, server, _monitor, _agents, _strategy, state, *_ = result
    try:
        assert state["mode"] == "BINANCE_SPOT_TESTNET"
        assert state["orders_enabled"] is True
        assert state["binance_testnet_execution"]["enabled"] is True
        assert state["binance_testnet_execution"]["status"] == "ENABLED_TESTNET"
        assert service.os.environ["DOMINION_ENABLE_BINANCE_TESTNET_ORDERS"] == "YES"
    finally:
        stop_event.set()
        server.server_close()
        service.os.environ["DOMINION_ENABLE_BINANCE_TESTNET_ORDERS"] = "NO"


def test_runtime_refuses_testnet_mode_when_credentials_are_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "PublicCryptoFeeds", FakeFeeds)
    monkeypatch.setattr(service, "CryptoPaperMonitor", FakeMonitor)
    monkeypatch.setattr(service, "BinanceMarketUniverse", FakeUniverse)
    monkeypatch.setattr(service, "BinancePublicCandleFeed", FakeCandleFeed)
    result = service._runtime_config(
        str(tmp_path), port=0, binance_testnet_orders_enabled=True,
    )
    stop_event, server, _monitor, _agents, _strategy, state, *_ = result
    try:
        assert state["mode"] == "PAPER_ONLY"
        assert state["orders_enabled"] is False
        assert state["binance_testnet_execution"]["enabled"] is False
        assert service.os.environ["DOMINION_ENABLE_BINANCE_TESTNET_ORDERS"] == "NO"
    finally:
        stop_event.set()
        server.server_close()


@pytest.mark.parametrize("value", ["nan", "NaN", "inf", "-inf"])
def test_fee_config_rejects_non_finite_values(monkeypatch, value):
    monkeypatch.setenv("DOMINION_FEE_BINANCE_PERSONAL_MAKER_BPS", value)
    monkeypatch.setenv("DOMINION_FEE_BINANCE_PERSONAL_TAKER_BPS", "8")
    monkeypatch.setenv("DOMINION_FEE_BINANCE_PERSONAL_VERIFIED", "YES")
    with pytest.raises(RuntimeError, match="finite"):
        service._fee_config()

def test_scanner_readiness_requires_all_four_fresh_exchange_feeds():
    scanner = {
        "status": "NO_QUALIFYING_OPPORTUNITY",
        "symbols_scanned": 52,
        "fresh_quote_count": 104,
        "symbols_with_two_venues": 52,
        "available_exchanges": ["Binance", "Bitget", "HTX", "OKX"],
        "fresh_exchanges": ["Binance", "Bitget", "HTX", "OKX"],
        "venue_errors": {},
        "reason": "No fresh, depth-backed price gap cleared verified fees.",
    }
    assert service._cross_exchange_scan_verified(scanner) is True

    # All four may have returned something, but a stale-only venue must not
    # make the full scanner look verified.
    scanner["fresh_exchanges"] = ["Binance", "Bitget", "OKX"]
    assert service._cross_exchange_scan_verified(scanner) is False


def test_scanner_readiness_rejects_missing_fee_qualification():
    scanner = {
        "status": "NO_QUALIFYING_OPPORTUNITY",
        "symbols_scanned": 52,
        "fresh_quote_count": 104,
        "symbols_with_two_venues": 52,
        "fresh_exchanges": ["Binance", "Bitget", "HTX", "OKX"],
        "venue_errors": {},
        "reason": "FEE_CONFIG_MISSING",
    }
    assert service._cross_exchange_scan_verified(scanner) is False



def _testnet_monitor_state():
    return {
        "orders_enabled": True,
        "binance_testnet_execution": {
            "enabled": True, "status": "ENABLED_TESTNET",
            "halted": False, "orders_enabled": True,
        },
        "agents": {
            "RISK": {}, "SNIPER": {}, "EXIT": {},
        },
    }


def test_testnet_position_monitor_keeps_confirmed_protection_and_does_not_submit():
    state = _testnet_monitor_state()
    result = service._apply_testnet_reconciliation(state, {
        "status": "RECONCILED", "halted": False, "reconciled": 1,
        "orders": [{
            "order_list_id": "private-id", "symbol": "BTCUSDT",
            "state": "PROTECTED", "safe": True,
        }],
        "unresolved": [],
    })
    assert result["status"] == "RECONCILED"
    assert result["halted"] is False
    assert state["orders_enabled"] is True
    assert state["binance_testnet_execution"]["orders_enabled"] is True
    assert state["agents"]["EXIT"]["status"] == "EXCHANGE_PROTECTED_TESTNET_POSITION"


def test_testnet_position_monitor_halts_new_entries_on_uncertain_reconciliation():
    state = _testnet_monitor_state()
    result = service._apply_testnet_reconciliation(state, {
        "status": "RECONCILIATION_REQUIRED", "halted": True,
        "reconciled": 0,
        "orders": [],
        "unresolved": [{"reason": "EXCHANGE_QUERY_FAILED"}],
    })
    assert result["halted"] is True
    assert result["unresolved_count"] == 1
    assert state["orders_enabled"] is False
    assert state["binance_testnet_execution"]["orders_enabled"] is False
    assert state["binance_testnet_execution"]["halted"] is True
    assert state["agents"]["RISK"]["status"] == "BLOCKED"
    assert state["agents"]["SNIPER"]["status"] == "PAUSED_REQUIRES_REVIEW"
    assert state["agents"]["EXIT"]["status"] == "RECONCILIATION_REQUIRED"


def test_testnet_position_monitor_reports_exchange_confirmed_exit_without_closing_again():
    state = _testnet_monitor_state()
    service._apply_testnet_reconciliation(state, {
        "status": "RECONCILED", "halted": False, "reconciled": 1,
        "orders": [{
            "order_list_id": "private-id", "symbol": "BTCUSDT",
            "state": "EXITED_TAKE_PROFIT", "safe": True,
        }],
        "unresolved": [],
    })
    assert state["agents"]["EXIT"]["status"] == "TESTNET_POSITION_EXIT_RECONCILED"
    assert state["orders_enabled"] is True
