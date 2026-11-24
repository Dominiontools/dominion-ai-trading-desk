from urllib.parse import parse_qs, urlsplit

import pytest

from engine.ctrader_oauth import build_authorization_url, authorize_interactively


def test_c_trader_oauth_defaults_to_view_only_scope():
    url = build_authorization_url("client-id", "http://127.0.0.1:8765/callback", "state")
    query = parse_qs(urlsplit(url).query)
    assert query["scope"] == ["accounts"]
    assert query["state"] == ["state"]


def test_c_trader_oauth_can_request_trading_scope_explicitly():
    url = build_authorization_url("client-id", "http://127.0.0.1:8765/callback",
                                 "state", scope="trading")
    assert parse_qs(urlsplit(url).query)["scope"] == ["trading"]


def test_c_trader_oauth_rejects_unknown_scope_before_starting_server():
    with pytest.raises(ValueError):
        build_authorization_url("client-id", "http://127.0.0.1:8765/callback",
                                "state", scope="admin")
    with pytest.raises(ValueError):
        authorize_interactively("id", "secret", "http://127.0.0.1:8765/callback",
                                ".tokens", scope="admin")
