"""Local cTrader OAuth helper with private token-file storage.

Use the accounts scope only. This module never prints or logs token values.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import tempfile
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen

TOKEN_ENDPOINT = "https://openapi.ctrader.com/apps/token"
AUTHORIZE_ENDPOINT = "https://id.ctrader.com/my/settings/openapi/grantingaccess/"


def build_authorization_url(client_id: str, redirect_uri: str, state: str) -> str:
    query = urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": "accounts",
        "product": "web",
        "state": state,
    })
    return AUTHORIZE_ENDPOINT + "?" + query


def _request_token(params: dict[str, str], method: str, opener=None) -> dict:
    request_opener = opener or urlopen
    if method == "GET":
        request = Request(TOKEN_ENDPOINT + "?" + urlencode(params), headers={"Accept": "application/json"})
    elif method == "POST":
        request = Request(
            TOKEN_ENDPOINT,
            data=urlencode(params).encode("utf-8"),
            headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
    else:
        raise ValueError("Unsupported OAuth request method.")
    try:
        with request_opener(request, timeout=20) as response:
            result = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise RuntimeError("cTrader OAuth request failed; check connectivity and application settings.") from exc
    if result.get("errorCode"):
        raise RuntimeError("cTrader OAuth rejected the request: " + str(result.get("errorCode")))
    if not all(result.get(key) for key in ("accessToken", "refreshToken", "tokenType", "expiresIn")):
        raise RuntimeError("cTrader OAuth returned an incomplete token response.")
    try:
        if int(result["expiresIn"]) <= 0:
            raise ValueError
    except (TypeError, ValueError) as exc:
        raise RuntimeError("cTrader OAuth returned an invalid token lifetime.") from exc
    return result


def save_token_response(token_response: dict, token_file: str | Path, *, now: float | None = None) -> None:
    expires_in = int(token_response["expiresIn"])
    payload = {
        "access_token": token_response["accessToken"],
        "refresh_token": token_response["refreshToken"],
        "token_type": token_response["tokenType"],
        "expires_at": int((time.time() if now is None else now) + expires_in),
    }
    path = Path(token_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_token_file(token_file: str | Path) -> dict:
    path = Path(token_file)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError("No cTrader token file was found. Run python -m engine.ctrader_oauth authorize first.") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("The local cTrader token file could not be read.") from exc
    if not payload.get("access_token") or not payload.get("refresh_token") or not payload.get("expires_at"):
        raise RuntimeError("The local cTrader token file is incomplete; authorize again.")
    return payload


def refresh_token_file(client_id: str, client_secret: str, token_file: str | Path, *, now: float | None = None, opener=None) -> dict:
    current = read_token_file(token_file)
    response = _request_token({
        "grant_type": "refresh_token",
        "refresh_token": current["refresh_token"],
        "client_id": client_id,
        "client_secret": client_secret,
    }, "POST", opener=opener)
    save_token_response(response, token_file, now=now)
    return read_token_file(token_file)


def load_access_token(client_id: str, client_secret: str, explicit_access_token: str | None, token_file: str | Path, *, now: float | None = None, opener=None) -> str:
    if explicit_access_token:
        return explicit_access_token
    current = read_token_file(token_file)
    current_time = time.time() if now is None else now
    if int(current["expires_at"]) <= current_time + 300:
        current = refresh_token_file(client_id, client_secret, token_file, now=current_time, opener=opener)
    return current["access_token"]


def authorize_interactively(client_id: str, client_secret: str, redirect_uri: str, token_file: str) -> None:
    parsed_redirect = urlsplit(redirect_uri)
    if parsed_redirect.scheme != "http" or parsed_redirect.hostname not in {"127.0.0.1", "localhost"}:
        raise RuntimeError("For this local helper, redirect URI must use http://127.0.0.1 or http://localhost.")
    expected_path = parsed_redirect.path or "/"
    expected_port = parsed_redirect.port or 80
    state = secrets.token_urlsafe(24)
    received: dict[str, str] = {}

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlsplit(self.path)
            query = parse_qs(parsed.query)
            if parsed.path != expected_path:
                self.send_error(404)
                return
            if query.get("state", [""])[0] != state:
                self.send_error(400, "OAuth state mismatch")
                return
            code = query.get("code", [""])[0]
            if not code:
                self.send_error(400, "Missing authorization code")
                return
            received["code"] = code
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"cTrader authorization received. You can close this tab.")

        def log_message(self, format, *args):
            return

    server = HTTPServer((parsed_redirect.hostname, expected_port), CallbackHandler)
    server.timeout = 1
    authorization_url = build_authorization_url(client_id, redirect_uri, state)
    print("Opening cTrader authorization in your browser. Approve ACCOUNTS / VIEW-ONLY access.")
    print("If the browser does not open, visit this URL:", authorization_url)
    webbrowser.open(authorization_url)
    deadline = time.monotonic() + 180
    try:
        while not received and time.monotonic() < deadline:
            server.handle_request()
    finally:
        server.server_close()
    if not received:
        raise RuntimeError("Timed out waiting for the local cTrader authorization callback.")
    token_response = _request_token({
        "grant_type": "authorization_code",
        "code": received["code"],
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "client_secret": client_secret,
    }, "GET")
    save_token_response(token_response, token_file)
    print("cTrader view-only authorization completed. Tokens were saved to a private local file.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Set up or refresh cTrader view-only OAuth tokens.")
    parser.add_argument("command", choices=("authorize", "refresh"))
    args = parser.parse_args()
    client_id = os.getenv("CTRADER_CLIENT_ID", "").strip()
    client_secret = os.getenv("CTRADER_CLIENT_SECRET", "").strip()
    redirect_uri = os.getenv("CTRADER_REDIRECT_URI", "http://127.0.0.1:8765/callback").strip()
    token_file = os.getenv("CTRADER_TOKEN_FILE", ".ctrader_tokens.json")
    if not client_id or not client_secret:
        raise SystemExit("Set CTRADER_CLIENT_ID and CTRADER_CLIENT_SECRET in your local environment first.")
    if args.command == "authorize":
        authorize_interactively(client_id, client_secret, redirect_uri, token_file)
    else:
        refresh_token_file(client_id, client_secret, token_file)
        print("cTrader tokens refreshed and saved. Token values were not displayed.")


if __name__ == "__main__":
    main()
