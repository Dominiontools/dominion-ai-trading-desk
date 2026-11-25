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


def test_gmgn_security_summary_flags_documented_sol_risks_and_keeps_unknowns():
    from engine.gmgn_api import summarize_security_evidence

    result = summarize_security_evidence({
        "data": {
            "open_source": "no",
            "owner_renounced": "unknown",
            "rug_ratio": 0.45,
            "is_wash_trading": True,
            "renounced_mint": False,
            "renounced_freeze_account": None,
        }
    }, "sol")
    assert result["status"] == "RISK_FLAGS_FOUND"
    assert "GMGN_HIGH_RUG_RATIO" in result["risk_flags"]
    assert "GMGN_WASH_TRADING_DETECTED" in result["risk_flags"]
    assert "GMGN_MINT_AUTHORITY_NOT_RENOUNCED" in result["risk_flags"]
    assert "owner_renounced" in result["unknown_fields"]
    assert "renounced_freeze_account" in result["unknown_fields"]
    assert "is_honeypot" not in result["unknown_fields"]


def test_gmgn_security_summary_flags_bsc_honeypot_and_never_claims_safe():
    from engine.gmgn_api import summarize_security_evidence

    honeypot = summarize_security_evidence({
        "data": {
            "open_source": "yes", "owner_renounced": "yes",
            "rug_ratio": 0.1, "is_wash_trading": False,
            "is_honeypot": "yes",
        }
    }, "bsc")
    assert honeypot["status"] == "RISK_FLAGS_FOUND"
    assert "GMGN_HONEYPOT_DETECTED" in honeypot["risk_flags"]

    incomplete = summarize_security_evidence({"data": {}}, "sol")
    assert incomplete["status"] == "INSUFFICIENT_EVIDENCE"
    assert incomplete["risk_flags"] == []
    assert "safety" not in incomplete["status"].lower()


def test_gmgn_trenches_parser_extracts_and_deduplicates_token_records():
    from engine.gmgn_api import extract_trenches_tokens

    payload = {
        "data": {
            "new_creation": {"list": [
                {"address": "A" * 32, "symbol": "AAA", "name": "Alpha", "rug_ratio": 0.2},
                {"token_address": "B" * 32, "symbol": "BBB"},
            ]},
            "near_completion": {"list": [
                {"address": "A" * 32, "symbol": "AAA", "name": "Alpha"},
                {"address": "short", "symbol": "BAD"},
                {"address": "C" * 32, "symbol": "CCC"},
            ]},
        }
    }
    tokens = extract_trenches_tokens(payload, "sol", limit=10)
    assert [item["symbol"] for item in tokens] == ["AAA", "BBB", "CCC"]
    assert tokens[0]["chain"] == "sol"
    assert tokens[0]["rug_ratio"] == 0.2
    assert len(tokens) == 3
