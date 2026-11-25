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


def test_fee_config_is_empty_without_user_verified_values(monkeypatch):
    for name in ("DOMINION_FEE_BINANCE_TAKER_BPS", "DOMINION_FEE_BITGET_TAKER_BPS",
                 "DOMINION_FEE_HTX_TAKER_BPS"):
        monkeypatch.delenv(name, raising=False)
    assert service._fee_config() == {}


def test_fee_config_reads_all_three_explicit_values(monkeypatch):
    monkeypatch.setenv("DOMINION_FEE_BINANCE_TAKER_BPS", "10")
    monkeypatch.setenv("DOMINION_FEE_BITGET_TAKER_BPS", "12")
    monkeypatch.setenv("DOMINION_FEE_HTX_TAKER_BPS", "8")
    assert service._fee_config() == {"Binance": (10.0, 10.0),
                                     "Bitget": (12.0, 12.0), "HTX": (8.0, 8.0)}


def test_fee_config_rejects_negative_fee(monkeypatch):
    monkeypatch.setenv("DOMINION_FEE_BINANCE_TAKER_BPS", "-1")
    with pytest.raises(RuntimeError):
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


class FakeGMGN:
    def __init__(self, api_key, timeout=8.0):
        assert api_key == "gmgn-test-key"
        self.timeout = timeout

    def trenches(self, chain, limit=50):
        return {"code": 0, "data": {"chain": chain, "tokens": []}}

    def trending(self, chain, interval, limit=30):
        return {"code": 0, "data": {"chain": chain, "interval": interval, "tokens": []}}

    def token_security(self, chain, address):
        return {"code": 0, "data": {
            "chain": chain, "address": address, "open_source": "yes",
            "owner_renounced": "yes", "rug_ratio": 0.1,
            "is_wash_trading": False, "renounced_mint": True,
            "renounced_freeze_account": True,
        }}


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


def test_embedded_service_connects_official_gmgn_read_only_feed(tmp_path, monkeypatch):
    monkeypatch.setattr(service.time, "monotonic", lambda: 400.0)
    monkeypatch.setattr(service, "PublicCryptoFeeds", FakeFeeds)
    monkeypatch.setattr(service, "CryptoPaperMonitor", FakeMonitor)
    monkeypatch.setattr(service, "BinanceMarketUniverse", FakeUniverse)
    monkeypatch.setattr(service, "BinancePublicCandleFeed", FakeCandleFeed)
    monkeypatch.setattr(service, "GMGNReadOnlyClient", FakeGMGN)
    monkeypatch.setattr(service, "DexScreenerDiscovery", EmptyDiscovery)
    monkeypatch.setattr(service, "GeckoTerminalWhaleFeed", EmptyWhaleFeed)
    monkeypatch.setattr(service, "GoPlusSecurityFeed", EmptySecurityFeed)
    monkeypatch.setattr(service, "PublicNewsRSS", EmptyNewsFeed)
    for name in ("DOMINION_FEE_BINANCE_TAKER_BPS", "DOMINION_FEE_BITGET_TAKER_BPS",
                 "DOMINION_FEE_HTX_TAKER_BPS"):
        monkeypatch.delenv(name, raising=False)

    started = service.start_embedded(str(tmp_path), port=0, gmgn_api_key="gmgn-test-key")
    try:
        deadline = time.time() + 3
        status = None
        while time.time() < deadline:
            try:
                with urlopen(f"http://127.0.0.1:{started['port']}/api/crypto/status", timeout=1) as response:
                    status = json.loads(response.read())
                if status.get("gmgn_feed", {}).get("status") == "CONNECTED":
                    break
            except OSError:
                time.sleep(0.05)
            time.sleep(0.05)
        assert status is not None
        assert status["gmgn_feed"]["status"] == "CONNECTED", status
        assert status.get("agent_feed_error") is None, status
        assert "gmgn-test-key" not in json.dumps(status)
        assert status["orders_enabled"] is False
    finally:
        service.stop_embedded()


def test_gmgn_security_evidence_is_used_by_rug_agent_for_solana_tokens(tmp_path, monkeypatch):
    monkeypatch.setattr(service.time, "monotonic", lambda: 100.0)
    monkeypatch.setattr(service, "PublicCryptoFeeds", FakeFeeds)
    monkeypatch.setattr(service, "CryptoPaperMonitor", FakeMonitor)
    monkeypatch.setattr(service, "BinanceMarketUniverse", FakeUniverse)
    monkeypatch.setattr(service, "BinancePublicCandleFeed", FakeCandleFeed)
    monkeypatch.setattr(service, "GMGNReadOnlyClient", FakeGMGN)
    monkeypatch.setattr(service, "DexScreenerDiscovery", OneSolanaTokenDiscovery)
    monkeypatch.setattr(service, "GeckoTerminalWhaleFeed", EmptyWhaleFeed)
    monkeypatch.setattr(service, "GoPlusSecurityFeed", EmptySecurityFeed)
    monkeypatch.setattr(service, "PublicNewsRSS", EmptyNewsFeed)
    for name in ("DOMINION_FEE_BINANCE_TAKER_BPS", "DOMINION_FEE_BITGET_TAKER_BPS",
                 "DOMINION_FEE_HTX_TAKER_BPS"):
        monkeypatch.delenv(name, raising=False)

    started = service.start_embedded(str(tmp_path), port=0, gmgn_api_key="gmgn-test-key")
    try:
        deadline = time.time() + 3
        status = None
        while time.time() < deadline:
            try:
                with urlopen(f"http://127.0.0.1:{started['port']}/api/crypto/status", timeout=1) as response:
                    status = json.loads(response.read())
                rug = status.get("agents", {}).get("RUG", {})
                if rug.get("gmgn_security_checks"):
                    break
            except OSError:
                time.sleep(0.05)
            time.sleep(0.05)
        assert status is not None
        assert status["agents"]["RUG"]["status"] == "CONNECTED"
        assert status["agents"]["RUG"]["gmgn_security_checks"][0]["chain"] == "sol"
        assert status["gmgn_feed"]["status"] == "CONNECTED"
        assert status["orders_enabled"] is False
    finally:
        service.stop_embedded()



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
