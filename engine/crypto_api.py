"""Loopback-only, read-only HTTP bridge for the crypto paper monitor.

This server never starts/stops the monitor and exposes no order or credential
endpoints. It binds only to 127.0.0.1 so it is not a remotely reachable API.
"""
from __future__ import annotations

import json
from urllib.parse import urlsplit
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable


def _read_decisions(path: Path, limit: int) -> list[dict]:
    if not path.exists():
        return []
    records: list[dict] = []
    # Read only the last bounded number of lines; tolerate a partial final line.
    with path.open("r", encoding="utf-8") as handle:
        lines = handle.readlines()[-limit:]
    for line in lines:
        try:
            item = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if isinstance(item, dict):
            records.append(item)
    return list(reversed(records))


def make_handler(
    decision_log: str | Path,
    status_provider: Callable[[], dict] | None = None,
):
    log_path = Path(decision_log)
    get_status = status_provider or (lambda: {
        "engine": "not_started",
        "mode": "PAPER_ONLY",
        "orders_enabled": False,
    })

    class ReadOnlyHandler(BaseHTTPRequestHandler):
        server_version = "DominionPaperAPI/0.1"

        _allowed_origins = {"https://localhost", "http://localhost:5173"}

        def _cors(self) -> None:
            origin = self.headers.get("Origin")
            if origin in self._allowed_origins:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
                self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")

        def _send(self, status: int, payload: dict) -> None:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self._cors()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self) -> None:  # noqa: N802
            if self.headers.get("Origin") not in self._allowed_origins:
                self._send(403, {"error": "origin_not_allowed"})
                return
            self.send_response(204)
            self._cors()
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            origin = self.headers.get("Origin")
            if origin and origin not in self._allowed_origins:
                self._send(403, {"error": "origin_not_allowed"})
                return
            route = urlsplit(self.path)
            if route.path == "/health":
                try:
                    status = get_status()
                    mode = status.get("mode") if isinstance(status, dict) else "PAPER_ONLY"
                    if mode not in {"PAPER_ONLY", "BINANCE_SPOT_TESTNET"}:
                        mode = "PAPER_ONLY"
                    enabled = mode == "BINANCE_SPOT_TESTNET" and status.get("orders_enabled") is True
                    self._send(200, {"ok": True, "mode": mode, "orders_enabled": enabled})
                except Exception:
                    self._send(503, {"ok": False, "mode": "PAPER_ONLY",
                                     "orders_enabled": False})
                return
            if route.path == "/api/crypto/status":
                try:
                    status = get_status()
                    if not isinstance(status, dict):
                        raise TypeError("Status provider must return a dictionary.")
                    safe_status = dict(status)
                    mode = safe_status.get("mode")
                    if mode not in {"PAPER_ONLY", "BINANCE_SPOT_TESTNET"}:
                        mode = "PAPER_ONLY"
                    safe_status["mode"] = mode
                    safe_status["orders_enabled"] = (
                        mode == "BINANCE_SPOT_TESTNET"
                        and safe_status.get("orders_enabled") is True
                    )
                    self._send(200, safe_status)
                except Exception:
                    self._send(503, {"ok": False, "status": "unavailable",
                                     "mode": "PAPER_ONLY", "orders_enabled": False})
                return
            if route.path == "/api/crypto/decisions":
                limit = 50
                if route.query:
                    from urllib.parse import parse_qs
                    raw = parse_qs(route.query).get("limit", ["50"])[0]
                    try:
                        limit = max(1, min(100, int(raw)))
                    except ValueError:
                        self._send(400, {"error": "limit must be an integer"})
                        return
                self._send(200, {"items": _read_decisions(log_path, limit),
                                 "mode": "PAPER_ONLY", "orders_enabled": False})
                return
            self._send(404, {"error": "not_found"})

        def do_POST(self) -> None:  # noqa: N802
            self._send(405, {"error": "method_not_allowed",
                             "read_only": True, "orders_enabled": False})

        def do_PUT(self) -> None:  # noqa: N802
            self._send(405, {"error": "method_not_allowed",
                             "read_only": True, "orders_enabled": False})

        def do_DELETE(self) -> None:  # noqa: N802
            self._send(405, {"error": "method_not_allowed",
                             "read_only": True, "orders_enabled": False})

        def log_message(self, fmt: str, *args) -> None:
            # Avoid writing request data or local paths to standard output.
            return

    return ReadOnlyHandler


def create_server(
    decision_log: str | Path,
    *,
    status_provider: Callable[[], dict] | None = None,
    host: str = "127.0.0.1",
    port: int = 8766,
) -> ThreadingHTTPServer:
    if host != "127.0.0.1":
        raise ValueError("The paper API must bind to loopback (127.0.0.1) only.")
    if not 0 <= port <= 65535:
        raise ValueError("Port must be between 0 and 65535.")
    return ThreadingHTTPServer(
        (host, port), make_handler(decision_log, status_provider)
    )
