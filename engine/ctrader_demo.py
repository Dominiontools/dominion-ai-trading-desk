"""Read-only cTrader demo connector primitives.

This module intentionally has no order, amend, cancel, or close-position methods.
The OAuth token must be granted with the cTrader 'accounts' (view-only) scope.
"""
from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from engine.market_data import Candle

TIMEFRAME_ENUMS = {
    "M1": 1, "M2": 2, "M3": 3, "M4": 4, "M5": 5,
    "M10": 6, "M15": 7, "M30": 8, "H1": 9,
    "H4": 10, "H12": 11, "D1": 12, "W1": 13, "MN1": 14,
}

@dataclass(frozen=True)
class CTraderDemoConfig:
    client_id: str
    client_secret: str
    access_token: str
    account_id: int

    @classmethod
    def from_env(cls) -> "CTraderDemoConfig":
        names = ("CTRADER_CLIENT_ID", "CTRADER_CLIENT_SECRET", "CTRADER_ACCESS_TOKEN", "CTRADER_ACCOUNT_ID")
        values = {name: os.getenv(name, "").strip() for name in names}
        missing = [name for name, value in values.items() if not value]
        if missing:
            raise RuntimeError("Missing required environment settings: " + ", ".join(missing))
        try:
            account_id = int(values["CTRADER_ACCOUNT_ID"])
        except ValueError as exc:
            raise RuntimeError("CTRADER_ACCOUNT_ID must be an integer.") from exc
        if account_id <= 0:
            raise RuntimeError("CTRADER_ACCOUNT_ID must be positive.")
        return cls(values["CTRADER_CLIENT_ID"], values["CTRADER_CLIENT_SECRET"], values["CTRADER_ACCESS_TOKEN"], account_id)


def market_for_symbol(symbol: str) -> str:
    normalized = symbol.upper().replace("/", "").replace("_", "")
    return "GOLD" if normalized.startswith(("XAU", "GOLD")) else "FOREX"


def trendbar_to_candle(bar, symbol: str, timeframe: str) -> Candle:
    """Convert a cTrader ProtoOATrendbar using its documented 1e-5 price unit."""
    low_raw = int(bar.low)
    low = low_raw / 100_000
    open_price = (low_raw + int(bar.deltaOpen)) / 100_000
    close_price = (low_raw + int(bar.deltaClose)) / 100_000
    high_price = (low_raw + int(bar.deltaHigh)) / 100_000
    timestamp = datetime.fromtimestamp(int(bar.utcTimestampInMinutes) * 60, tz=timezone.utc)
    return Candle(
        symbol=symbol,
        market=market_for_symbol(symbol),
        timeframe=timeframe,
        timestamp=timestamp,
        open=open_price,
        high=high_price,
        low=low,
        close=close_price,
        volume=float(bar.volume),
    )


class CTraderDemoConnector:
    """Twisted callback-based, demo-only, view-scope market-data connector."""
    def __init__(self, config: CTraderDemoConfig, on_candles: Callable[[list[Candle]], None] | None = None):
        self.config = config
        self.on_candles = on_candles or (lambda candles: None)
        self.client = None
        self.account_id: int | None = None
        self.symbol_ids: dict[str, int] = {}
        self.pending: dict[str, tuple[str, str]] = {}
        self.state = "DISCONNECTED"

    def start(self) -> None:
        try:
            from ctrader_open_api import Client, Protobuf, TcpProtocol, EndPoints
            from ctrader_open_api.messages.OpenApiMessages_pb2 import (
                ProtoOAApplicationAuthReq, ProtoOAApplicationAuthRes,
                ProtoOAGetAccountListByAccessTokenReq, ProtoOAGetAccountListByAccessTokenRes,
                ProtoOAAccountAuthReq, ProtoOAAccountAuthRes,
                ProtoOASymbolsListReq, ProtoOASymbolsListRes,
                ProtoOAGetTrendbarsReq, ProtoOAGetTrendbarsRes, ProtoOAErrorRes,
            )
            from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOATrendbarPeriod
        except ImportError as exc:
            raise RuntimeError("Install the official Spotware SDK: pip install ctrader-open-api") from exc

        self._protobuf = Protobuf
        self._messages = {
            "app_auth_req": ProtoOAApplicationAuthReq, "app_auth_res": ProtoOAApplicationAuthRes,
            "accounts_req": ProtoOAGetAccountListByAccessTokenReq, "accounts_res": ProtoOAGetAccountListByAccessTokenRes,
            "account_auth_req": ProtoOAAccountAuthReq, "account_auth_res": ProtoOAAccountAuthRes,
            "symbols_req": ProtoOASymbolsListReq, "symbols_res": ProtoOASymbolsListRes,
            "bars_req": ProtoOAGetTrendbarsReq, "bars_res": ProtoOAGetTrendbarsRes,
            "error_res": ProtoOAErrorRes,
        }
        self._periods = ProtoOATrendbarPeriod
        # Demo endpoint is hard-coded: this connector cannot select a live host.
        self.client = Client(EndPoints.PROTOBUF_DEMO_HOST, EndPoints.PROTOBUF_PORT, TcpProtocol)
        self.client.setConnectedCallback(self._connected)
        self.client.setDisconnectedCallback(self._disconnected)
        self.client.setMessageReceivedCallback(self._received)
        self.state = "CONNECTING_DEMO"
        self.client.startService()

    def _send(self, request, request_id: str | None = None) -> None:
        deferred = self.client.send(request, clientMsgId=request_id) if request_id else self.client.send(request)
        deferred.addErrback(self._failed)

    def _connected(self, client) -> None:
        request = self._messages["app_auth_req"]()
        request.clientId = self.config.client_id
        request.clientSecret = self.config.client_secret
        self._send(request)

    def _disconnected(self, client, reason) -> None:
        self.state = "DISCONNECTED"

    def _failed(self, failure):
        self.state = "ERROR"
        return failure

    def _received(self, client, message) -> None:
        payload = self._protobuf.extract(message)
        kind = message.payloadType
        if kind == self._messages["error_res"]().payloadType:
            self.state = "ERROR"
            return
        if kind == self._messages["app_auth_res"]().payloadType:
            request = self._messages["accounts_req"]()
            request.accessToken = self.config.access_token
            self._send(request)
            return
        if kind == self._messages["accounts_res"]().payloadType:
            account = next((item for item in payload.ctidTraderAccount if int(item.ctidTraderAccountId) == self.config.account_id), None)
            if account is None:
                self.state = "ACCOUNT_NOT_GRANTED"
                return
            if bool(account.isLive):
                self.state = "REFUSED_LIVE_ACCOUNT"
                return
            self.account_id = self.config.account_id
            request = self._messages["account_auth_req"]()
            request.ctidTraderAccountId = self.account_id
            request.accessToken = self.config.access_token
            self._send(request)
            return
        if kind == self._messages["account_auth_res"]().payloadType:
            self.state = "AUTHENTICATED_DEMO_READ_ONLY"
            request = self._messages["symbols_req"]()
            request.ctidTraderAccountId = self.account_id
            request.includeArchivedSymbols = False
            self._send(request)
            return
        if kind == self._messages["symbols_res"]().payloadType:
            self.symbol_ids = {item.symbolName: int(item.symbolId) for item in payload.symbol if item.enabled}
            self.state = "READY_DEMO_READ_ONLY"
            return
        if kind == self._messages["bars_res"]().payloadType:
            request_id = getattr(message, "clientMsgId", "")
            details = self.pending.pop(request_id, None)
            if details:
                symbol, timeframe = details
                candles = [trendbar_to_candle(bar, symbol, timeframe) for bar in payload.trendbar]
                candles.sort(key=lambda item: item.timestamp)
                self.on_candles(candles)

    def request_candles(self, symbol: str, timeframe: str, limit: int = 200) -> str:
        if self.state != "READY_DEMO_READ_ONLY" or self.account_id is None:
            raise RuntimeError("cTrader demo session is not ready; no market data request was sent.")
        if timeframe not in TIMEFRAME_ENUMS:
            raise ValueError("Unsupported timeframe. Choose one of: " + ", ".join(TIMEFRAME_ENUMS))
        if not 1 <= limit <= 5000:
            raise ValueError("Candle limit must be between 1 and 5000.")
        symbol_id = self.symbol_ids.get(symbol)
        if symbol_id is None:
            raise KeyError(f"Symbol {symbol!r} was not found in this demo account's enabled symbol list.")
        request_id = str(uuid.uuid4())
        now_ms = int(time.time() * 1000)
        request = self._messages["bars_req"]()
        request.ctidTraderAccountId = self.account_id
        request.symbolId = symbol_id
        request.period = TIMEFRAME_ENUMS[timeframe]
        request.toTimestamp = now_ms
        request.fromTimestamp = 0
        request.count = limit
        self.pending[request_id] = (symbol, timeframe)
        self._send(request, request_id)
        return request_id

    def stop(self) -> None:
        if self.client is not None:
            self.client.stopService()
        self.state = "DISCONNECTED"
