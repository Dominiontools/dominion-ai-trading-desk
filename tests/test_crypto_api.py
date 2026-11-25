import json
import threading
import urllib.error
import urllib.request

import pytest

from engine.crypto_api import create_server


@pytest.fixture
def api_server(tmp_path):
    log = tmp_path / "decisions.jsonl"
    log.write_text(
        json.dumps({"status": "NO_QUALIFYING_OPPORTUNITY", "symbol": "BTCUSDT"}) + "\n"
        + "{partial",
        encoding="utf-8",
    )
    server = create_server(
        log,
        status_provider=lambda: {"engine": "running", "exchange_count": 3},
        port=0,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    yield f"http://{host}:{port}"
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def get_json(base, path):
    with urllib.request.urlopen(base + path, timeout=2) as response:
        return response.status, json.loads(response.read())


def test_health_is_paper_only(api_server):
    status, body = get_json(api_server, "/health")
    assert status == 200
    assert body == {"ok": True, "mode": "PAPER_ONLY", "orders_enabled": False}


def test_status_is_read_only_even_if_provider_omits_guardrails(api_server):
    status, body = get_json(api_server, "/api/crypto/status")
    assert status == 200
    assert body["engine"] == "running"
    assert body["mode"] == "PAPER_ONLY"
    assert body["orders_enabled"] is False


def test_decisions_returns_recent_valid_records(api_server):
    status, body = get_json(api_server, "/api/crypto/decisions?limit=10")
    assert status == 200
    assert len(body["items"]) == 1
    assert body["items"][0]["symbol"] == "BTCUSDT"
    assert body["orders_enabled"] is False


def test_unknown_route_is_404(api_server):
    with pytest.raises(urllib.error.HTTPError) as exc:
        get_json(api_server, "/api/orders")
    assert exc.value.code == 404


def test_post_is_rejected(api_server):
    request = urllib.request.Request(api_server + "/api/crypto/status", data=b"{}",
                                     method="POST")
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(request, timeout=2)
    assert exc.value.code == 405


def test_remote_bind_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="loopback"):
        create_server(tmp_path / "log.jsonl", host="0.0.0.0")


def test_allowed_app_origin_receives_cors_header(api_server):
    request = urllib.request.Request(
        api_server + "/api/crypto/status",
        headers={"Origin": "https://localhost"},
    )
    with urllib.request.urlopen(request, timeout=2) as response:
        assert response.headers.get("Access-Control-Allow-Origin") == "https://localhost"
        assert response.headers.get("Access-Control-Allow-Methods") == "GET, OPTIONS"


def test_unapproved_origin_is_rejected(api_server):
    request = urllib.request.Request(
        api_server + "/api/crypto/status",
        headers={"Origin": "https://example.com"},
    )
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(request, timeout=2)
    assert exc.value.code == 403


def test_decisions_route_does_not_accept_similar_prefix(api_server):
    with pytest.raises(urllib.error.HTTPError) as exc:
        get_json(api_server, "/api/crypto/decisions-extra")
    assert exc.value.code == 404


def test_options_preflight_for_capacitor_origin(api_server):
    request = urllib.request.Request(
        api_server + "/api/crypto/status",
        headers={"Origin": "https://localhost", "Access-Control-Request-Method": "GET"},
        method="OPTIONS",
    )
    with urllib.request.urlopen(request, timeout=2) as response:
        assert response.status == 204
        assert response.headers.get("Access-Control-Allow-Origin") == "https://localhost"



def test_read_only_api_reports_explicit_testnet_mode_without_adding_order_routes(tmp_path):
    log = tmp_path / "decisions.jsonl"
    server = create_server(
        log,
        status_provider=lambda: {
            "engine": "running", "mode": "BINANCE_SPOT_TESTNET",
            "orders_enabled": True,
        },
        port=0,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://{server.server_address[0]}:{server.server_address[1]}"
    try:
        status, body = get_json(base, "/api/crypto/status")
        assert status == 200
        assert body["mode"] == "BINANCE_SPOT_TESTNET"
        assert body["orders_enabled"] is True
        health, health_body = get_json(base, "/health")
        assert health == 200
        assert health_body["mode"] == "BINANCE_SPOT_TESTNET"
        assert health_body["orders_enabled"] is True
        with pytest.raises(urllib.error.HTTPError) as exc:
            get_json(base, "/api/orders")
        assert exc.value.code == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
