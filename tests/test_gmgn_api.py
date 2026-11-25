import json
from urllib.parse import parse_qs, urlparse

import pytest

from engine.gmgn_api import GMGNReadOnlyClient, GMGN_BASE_URL


def test_gmgn_trenches_uses_official_exist_auth_and_read_only_payload():
    captured = {}

    def fake_fetch(method, url, headers, body, timeout):
        captured.update(method=method, url=url, headers=headers, body=body, timeout=timeout)
        return {"code": 0, "data": {"tokens": []}}

    client = GMGNReadOnlyClient(
        "test-api-key", fetch_json=fake_fetch, clock=lambda: 1_800_000_000,
        client_id=lambda: "client-uuid",
    )
    result = client.trenches("sol", limit=40)
    parsed = urlparse(captured["url"])
    query = parse_qs(parsed.query)
    body = json.loads(captured["body"])
    assert result["code"] == 0
    assert captured["method"] == "POST"
    assert parsed.scheme + "://" + parsed.netloc == GMGN_BASE_URL
    assert parsed.path == "/v1/trenches"
    assert query == {"chain": ["sol"], "timestamp": ["1800000000"], "client_id": ["client-uuid"]}
    assert captured["headers"]["X-APIKEY"] == "test-api-key"
    assert body["version"] == "v2"
    assert body["new_creation"]["limit"] == 40
    assert body["near_completion"]["limit"] == 40
    assert body["completed"]["limit"] == 40


def test_gmgn_token_security_uses_read_only_endpoint():
    captured = {}

    def fake_fetch(method, url, headers, body, timeout):
        captured.update(method=method, url=url, headers=headers, body=body)
        return {"code": 0, "data": {"is_honeypot": False}}

    client = GMGNReadOnlyClient("key", fetch_json=fake_fetch, client_id=lambda: "id")
    result = client.token_security("sol", "TokenAddress")
    assert result["data"]["is_honeypot"] is False
    assert captured["method"] == "GET"
    assert urlparse(captured["url"]).path == "/v1/token/security"
    assert parse_qs(urlparse(captured["url"]).query)["address"] == ["TokenAddress"]
    assert captured["body"] is None


def test_gmgn_rejects_invalid_chain_limit_and_empty_credentials():
    with pytest.raises(ValueError, match="API key"):
        GMGNReadOnlyClient("")
    client = GMGNReadOnlyClient("key", fetch_json=lambda *args: {"code": 0})
    with pytest.raises(ValueError, match="Unsupported GMGN chain"):
        client.trenches("unknown")
    with pytest.raises(ValueError, match="limit"):
        client.trenches("sol", limit=81)


def test_gmgn_errors_do_not_echo_api_key_or_request_url():
    def fail(*args):
        raise RuntimeError("request failed with X-APIKEY secret-value")

    client = GMGNReadOnlyClient("secret-value", fetch_json=fail)
    with pytest.raises(RuntimeError) as exc:
        client.trending()
    assert "secret-value" not in str(exc.value)
    assert "https://" not in str(exc.value)
