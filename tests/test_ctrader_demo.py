from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import pytest

from engine.ctrader_demo import CTraderDemoConfig, historical_window, is_confirmed_demo_account, market_for_symbol, spot_event_to_quote, trendbar_to_candle


def test_market_mapping_identifies_gold_and_forex():
    assert market_for_symbol("XAUUSD") == "GOLD"
    assert market_for_symbol("EUR/USD") == "FOREX"


def test_trendbar_prices_are_scaled_and_reconstructed():
    bar = SimpleNamespace(low=200000000, deltaOpen=100000, deltaClose=250000, deltaHigh=300000,
                          utcTimestampInMinutes=30000000, volume=123)
    candle = trendbar_to_candle(bar, "XAUUSD", "M5")
    assert candle.low == 2000.0
    assert candle.open == 2001.0
    assert candle.close == 2002.5
    assert candle.high == 2003.0
    assert candle.volume == 123.0
    assert candle.timestamp.tzinfo == timezone.utc


def test_connector_config_requires_client_credentials_and_account(monkeypatch, tmp_path):
    for name in ("CTRADER_CLIENT_ID", "CTRADER_CLIENT_SECRET", "CTRADER_ACCESS_TOKEN", "CTRADER_ACCOUNT_ID"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CTRADER_TOKEN_FILE", str(tmp_path / "missing.json"))
    with pytest.raises(RuntimeError, match="Missing required"):
        CTraderDemoConfig.from_env()


def test_connector_config_rejects_non_numeric_account(monkeypatch):
    monkeypatch.setenv("CTRADER_CLIENT_ID", "demo-client")
    monkeypatch.setenv("CTRADER_CLIENT_SECRET", "secret")
    monkeypatch.setenv("CTRADER_ACCESS_TOKEN", "token")
    monkeypatch.setenv("CTRADER_ACCOUNT_ID", "not-a-number")
    with pytest.raises(RuntimeError, match="must be an integer"):
        CTraderDemoConfig.from_env()


def test_account_must_explicitly_be_marked_demo():
    demo = SimpleNamespace(isLive=False, HasField=lambda name: name == "isLive")
    live = SimpleNamespace(isLive=True, HasField=lambda name: name == "isLive")
    unknown = SimpleNamespace(isLive=False, HasField=lambda name: False)
    assert is_confirmed_demo_account(demo)
    assert not is_confirmed_demo_account(live)
    assert not is_confirmed_demo_account(unknown)



def test_historical_window_is_bounded_to_requested_bar_count():
    end = 1_800_000_000_000
    start, returned_end = historical_window("M5", 200, end)
    assert returned_end == end
    assert end - start == 201 * 300_000


def test_historical_window_rejects_invalid_timeframe_and_limit():
    with pytest.raises(ValueError, match="Unsupported timeframe"):
        historical_window("Q1", 100, 1_800_000_000_000)
    with pytest.raises(ValueError, match="between 1 and 5000"):
        historical_window("M1", 0, 1_800_000_000_000)



def test_spot_event_converts_timestamped_bid_and_ask():
    event = SimpleNamespace(
        bid=115482,
        ask=115490,
        timestamp=1_800_000_000_000,
        HasField=lambda name: name in {"bid", "ask", "timestamp"},
    )
    quote = spot_event_to_quote(event, "EURUSD")
    assert quote is not None
    assert quote.symbol == "EURUSD"
    assert quote.bid == 1.15482
    assert quote.ask == 1.1549
    assert quote.timestamp.tzinfo == timezone.utc


def test_spot_event_rejects_missing_timestamp_or_crossed_market():
    missing_time = SimpleNamespace(
        bid=100000, ask=100001, timestamp=0,
        HasField=lambda name: name in {"bid", "ask"},
    )
    partial = SimpleNamespace(
        bid=100000, ask=0, timestamp=1_800_000_000_000,
        HasField=lambda name: name in {"bid", "timestamp"},
    )
    crossed = SimpleNamespace(
        bid=100002, ask=100001, timestamp=1_800_000_000_000,
        HasField=lambda name: name in {"bid", "ask", "timestamp"},
    )
    assert spot_event_to_quote(missing_time, "EURUSD") is None
    partial_quote = spot_event_to_quote(partial, "EURUSD")
    assert partial_quote is not None
    assert partial_quote.bid == 1.0
    assert partial_quote.ask is None
    assert spot_event_to_quote(crossed, "EURUSD") is None



def test_incremental_spot_updates_preserve_each_side_timestamp():
    first_time = 1_800_000_000_000
    first_event = SimpleNamespace(
        bid=115482, ask=115490, timestamp=first_time,
        HasField=lambda name: name in {"bid", "ask", "timestamp"},
    )
    initial = spot_event_to_quote(first_event, "EURUSD")
    assert initial is not None

    bid_update = SimpleNamespace(
        bid=115483, ask=0, timestamp=first_time + 1000,
        HasField=lambda name: name in {"bid", "timestamp"},
    )
    updated = spot_event_to_quote(
        bid_update,
        "EURUSD",
        previous_bid=initial.bid,
        previous_ask=initial.ask,
        previous_bid_timestamp=initial.bid_timestamp,
        previous_ask_timestamp=initial.ask_timestamp,
    )
    assert updated is not None
    assert updated.bid == 1.15483
    assert updated.ask == 1.1549
    assert updated.bid_timestamp > updated.ask_timestamp


class _FakeRequest:
    def __init__(self):
        self.symbolId = []

class _FakeDeferred:
    def addErrback(self, callback):
        self.errback = callback

class _FakeClient:
    def __init__(self):
        self.sent = []
    def send(self, request, clientMsgId=None):
        self.sent.append((request, clientMsgId))
        return _FakeDeferred()


def test_subscribe_spots_sends_timestamped_request_and_tracks_ack():
    from engine.ctrader_demo import CTraderDemoConnector

    connector = CTraderDemoConnector(CTraderDemoConfig("id", "secret", "token", 123))
    connector.state = "READY_DEMO_READ_ONLY"
    connector.account_id = 123
    connector.symbol_ids = {"EURUSD": 10, "XAUUSD": 20}
    connector._messages = {"spots_req": _FakeRequest}
    connector.client = _FakeClient()

    request_id = connector.subscribe_spots(["EURUSD", "XAUUSD", "EURUSD"])

    request, sent_id = connector.client.sent[0]
    assert sent_id == request_id
    assert request.ctidTraderAccountId == 123
    assert request.symbolId == [10, 20]
    assert request.subscribeToSpotTimestamp is True
    assert connector.pending_subscriptions[request_id] == {"EURUSD", "XAUUSD"}


def test_subscribe_spots_rejects_unknown_symbol_and_empty_list():
    from engine.ctrader_demo import CTraderDemoConnector

    connector = CTraderDemoConnector(CTraderDemoConfig("id", "secret", "token", 123))
    connector.state = "READY_DEMO_READ_ONLY"
    connector.account_id = 123
    connector.symbol_ids = {"EURUSD": 10}
    with pytest.raises(ValueError, match="At least one symbol"):
        connector.subscribe_spots([])
    with pytest.raises(KeyError, match="not enabled"):
        connector.subscribe_spots(["UNKNOWN"])



def test_spot_subscription_acknowledgement_updates_subscribed_symbols():
    from types import SimpleNamespace
    from engine.ctrader_demo import CTraderDemoConnector

    connector = CTraderDemoConnector(CTraderDemoConfig("id", "secret", "token", 123))
    connector.symbol_ids = {"EURUSD": 10, "XAUUSD": 20}
    connector.pending_subscriptions["request-1"] = {"EURUSD", "XAUUSD"}
    connector._protobuf = SimpleNamespace(
        extract=lambda message: SimpleNamespace(subscribedSymbolId=[10, 20])
    )
    connector._messages = {
        "error_res": lambda: SimpleNamespace(payloadType=900),
        "app_auth_res": lambda: SimpleNamespace(payloadType=910),
        "accounts_res": lambda: SimpleNamespace(payloadType=911),
        "account_auth_res": lambda: SimpleNamespace(payloadType=912),
        "symbols_res": lambda: SimpleNamespace(payloadType=913),
        "spots_res": lambda: SimpleNamespace(payloadType=901),
        "spot_event": lambda: SimpleNamespace(payloadType=902),
        "bars_res": lambda: SimpleNamespace(payloadType=903),
    }
    message = SimpleNamespace(payloadType=901, clientMsgId="request-1")

    connector._received(None, message)

    assert connector.subscribed_symbols == {"EURUSD", "XAUUSD"}
    assert "request-1" not in connector.pending_subscriptions


def test_spot_subscription_acknowledgement_rejects_partial_acceptance():
    from types import SimpleNamespace
    from engine.ctrader_demo import CTraderDemoConnector

    connector = CTraderDemoConnector(CTraderDemoConfig("id", "secret", "token", 123))
    connector.symbol_ids = {"EURUSD": 10, "XAUUSD": 20}
    connector.pending_subscriptions["request-2"] = {"EURUSD", "XAUUSD"}
    connector._protobuf = SimpleNamespace(
        extract=lambda message: SimpleNamespace(subscribedSymbolId=[10])
    )
    connector._messages = {
        "error_res": lambda: SimpleNamespace(payloadType=900),
        "app_auth_res": lambda: SimpleNamespace(payloadType=910),
        "accounts_res": lambda: SimpleNamespace(payloadType=911),
        "account_auth_res": lambda: SimpleNamespace(payloadType=912),
        "symbols_res": lambda: SimpleNamespace(payloadType=913),
        "spots_res": lambda: SimpleNamespace(payloadType=901),
        "spot_event": lambda: SimpleNamespace(payloadType=902),
        "bars_res": lambda: SimpleNamespace(payloadType=903),
    }
    message = SimpleNamespace(payloadType=901, clientMsgId="request-2")

    connector._received(None, message)

    assert connector.state == "ERROR"
    assert connector.subscribed_symbols == set()


def test_oauth_authorization_url_uses_view_only_scope():
    from urllib.parse import parse_qs, urlsplit
    from engine.ctrader_oauth import build_authorization_url

    url = build_authorization_url("client-1", "http://127.0.0.1:8765/callback", "state-1")
    query = parse_qs(urlsplit(url).query)
    assert query["scope"] == ["accounts"]
    assert query["client_id"] == ["client-1"]
    assert query["state"] == ["state-1"]


def test_token_file_is_private_and_access_token_is_loaded(tmp_path):
    import json
    import stat
    from engine.ctrader_oauth import load_access_token, save_token_response

    token_file = tmp_path / "tokens.json"
    save_token_response({
        "accessToken": "access-old", "refreshToken": "refresh-old",
        "tokenType": "bearer", "expiresIn": 3600,
    }, token_file, now=1000)
    assert load_access_token("id", "secret", None, token_file, now=1100) == "access-old"
    assert stat.S_IMODE(token_file.stat().st_mode) == 0o600
    assert json.loads(token_file.read_text())["refresh_token"] == "refresh-old"


def test_expired_token_is_refreshed_and_rotated(tmp_path):
    import json
    from engine.ctrader_oauth import load_access_token, save_token_response

    token_file = tmp_path / "tokens.json"
    save_token_response({
        "accessToken": "access-old", "refreshToken": "refresh-old",
        "tokenType": "bearer", "expiresIn": 1,
    }, token_file, now=1000)

    class FakeResponse:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self):
            return json.dumps({
                "accessToken": "access-new", "refreshToken": "refresh-new",
                "tokenType": "bearer", "expiresIn": 3600, "errorCode": None,
            }).encode()

    def fake_opener(request, timeout):
        assert request.get_method() == "POST"
        assert "refresh_token=refresh-old" in request.data.decode()
        return FakeResponse()

    token = load_access_token("id", "secret", None, token_file, now=1002, opener=fake_opener)
    assert token == "access-new"
    saved = json.loads(token_file.read_text())
    assert saved["refresh_token"] == "refresh-new"
    assert saved["expires_at"] == 4602


def test_config_loads_access_token_from_private_store_when_env_token_absent(monkeypatch, tmp_path):
    from engine.ctrader_oauth import save_token_response

    token_file = tmp_path / "tokens.json"
    save_token_response({
        "accessToken": "stored-access", "refreshToken": "stored-refresh",
        "tokenType": "bearer", "expiresIn": 3600,
    }, token_file)
    monkeypatch.setenv("CTRADER_CLIENT_ID", "demo-client")
    monkeypatch.setenv("CTRADER_CLIENT_SECRET", "secret")
    monkeypatch.setenv("CTRADER_ACCOUNT_ID", "123")
    monkeypatch.delenv("CTRADER_ACCESS_TOKEN", raising=False)
    monkeypatch.setenv("CTRADER_TOKEN_FILE", str(token_file))
    config = CTraderDemoConfig.from_env()
    assert config.access_token == "stored-access"
