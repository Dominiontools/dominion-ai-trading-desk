"""Durable, idempotent UTC-day loss ledger for Binance Spot Testnet.

The ledger records conservative planned-risk amounts only after Binance
confirms that the corresponding protective stop-loss order filled. Corruption
or inconsistent duplicate records fail closed.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path


class BinanceDailyLossLedger:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _records(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        records: dict[str, dict] = {}
        try:
            with self.path.open("r", encoding="utf-8") as stream:
                for line_number, line in enumerate(stream, 1):
                    if not line.strip():
                        continue
                    item = json.loads(line)
                    if not isinstance(item, dict):
                        raise ValueError("Ledger record must be an object.")
                    order_id = item.get("order_list_id")
                    symbol = item.get("symbol")
                    amount = Decimal(str(item.get("loss_quote")))
                    stamp = datetime.fromisoformat(
                        str(item.get("recorded_at", "")).replace("Z", "+00:00")
                    )
                    if (not isinstance(order_id, str) or not order_id
                            or not isinstance(symbol, str) or not symbol
                            or not amount.is_finite() or amount <= 0
                            or stamp.tzinfo is None or stamp.utcoffset() is None):
                        raise ValueError("Invalid daily loss ledger fields.")
                    normalized = {
                        "order_list_id": order_id,
                        "symbol": symbol.upper(),
                        "loss_quote": format(amount, "f"),
                        "recorded_at": stamp.astimezone(timezone.utc).isoformat(),
                    }
                    previous = records.get(order_id)
                    if previous and previous != normalized:
                        raise ValueError("Conflicting duplicate daily loss record.")
                    records[order_id] = normalized
        except (OSError, UnicodeDecodeError, json.JSONDecodeError,
                InvalidOperation, TypeError, ValueError) as exc:
            raise RuntimeError("Binance daily loss ledger is invalid; execution is blocked.") from exc
        return records

    def record_stop_loss(
        self, *, order_list_id: str, symbol: str, planned_loss_quote: str | Decimal,
        recorded_at: datetime | None = None,
    ) -> dict:
        if not order_list_id or len(order_list_id) > 20:
            raise ValueError("A valid order-list ID is required.")
        pair = symbol.strip().upper()
        if not pair:
            raise ValueError("A trading symbol is required.")
        try:
            amount = Decimal(str(planned_loss_quote))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("Planned loss must be a valid decimal.") from exc
        if not amount.is_finite() or amount <= 0:
            raise ValueError("Planned loss must be greater than zero.")
        stamp = recorded_at or datetime.now(timezone.utc)
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError("Loss timestamp must be timezone-aware.")
        record = {
            "order_list_id": order_list_id,
            "symbol": pair,
            "loss_quote": format(amount, "f"),
            "recorded_at": stamp.astimezone(timezone.utc).isoformat(),
        }
        records = self._records()
        previous = records.get(order_list_id)
        if previous:
            if previous != record:
                # Same ID may be reprocessed on a later restart. Preserve the
                # first timestamp and amount, but reject any changed basis.
                if (previous["symbol"] != pair
                        or Decimal(previous["loss_quote"]) != amount):
                    raise RuntimeError("Conflicting duplicate stop-loss ledger entry.")
                return dict(previous)
            return dict(previous)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        return dict(record)

    def loss_for_day(self, *, now: datetime | None = None) -> Decimal:
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError("Current time must be timezone-aware.")
        day = current.astimezone(timezone.utc).date()
        total = Decimal("0")
        for item in self._records().values():
            stamp = datetime.fromisoformat(item["recorded_at"])
            if stamp.astimezone(timezone.utc).date() == day:
                total += Decimal(item["loss_quote"])
        return total
