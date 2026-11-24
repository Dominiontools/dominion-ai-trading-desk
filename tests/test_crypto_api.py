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
