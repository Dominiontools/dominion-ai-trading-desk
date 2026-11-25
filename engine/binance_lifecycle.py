"""Single-submit, fail-closed Binance Spot Testnet protected-order lifecycle.

The optional journal persists client order IDs and halt state before network
submission. A process restart therefore cannot silently forget an uncertain
submission and place a duplicate. The journal is local state, not a substitute
for querying Binance during recovery.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from threading import RLock
from time import sleep
from typing import Any, Callable

from engine.risk_execution import BinanceOrderPlan, BinanceTestnetRiskGate


class BinanceProtectedLifecycle:
    """Coordinate protected orders with restart-safe submission idempotency."""

    JOURNAL_VERSION = 1

    def __init__(
        self,
        gate: BinanceTestnetRiskGate,
        client: Any,
        *,
        reconcile_attempts: int = 4,
        reconcile_interval_seconds: float = 0.25,
        wait: Callable[[float], None] = sleep,
        journal_path: str | Path | None = None,
        daily_loss_ledger: Any | None = None,
    ):
        if reconcile_attempts < 1 or reconcile_attempts > 10:
            raise ValueError("Reconciliation attempts must be between 1 and 10.")
        if reconcile_interval_seconds < 0 or reconcile_interval_seconds > 5:
            raise ValueError("Reconciliation interval must be between 0 and 5 seconds.")
        self._gate = gate
        self._client = client
        self._reconcile_attempts = reconcile_attempts
        self._reconcile_interval_seconds = reconcile_interval_seconds
        self._wait = wait
        self._lock = RLock()
        self._journal_path = Path(journal_path) if journal_path is not None else None
        self._daily_loss_ledger = daily_loss_ledger
        self._submitted_ids: set[str] = set()
        self._submitted_risk_quote: dict[str, str] = {}
        self._submitted_symbols: dict[str, str] = {}
        self._journal_invalid = False
        self._halted = False
        self._last_result: dict[str, Any] | None = None
        self._restore_state()

    def _restore_state(self) -> None:
        if self._journal_path is None or not self._journal_path.exists():
            return
        try:
            payload = json.loads(self._journal_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or payload.get("version") != self.JOURNAL_VERSION:
                raise ValueError("Unsupported lifecycle journal.")
            submitted = payload.get("submitted_ids")
            halted = payload.get("halted")
            last_result = payload.get("last_result")
            submitted_symbols = payload.get("submitted_symbols", {})
            submitted_risk_quote = payload.get("submitted_risk_quote", {})
            if (not isinstance(submitted, list)
                    or any(not isinstance(item, str) or not item or len(item) > 20 for item in submitted)
                    or not isinstance(halted, bool)
                    or not isinstance(submitted_symbols, dict)
                    or any(not isinstance(k, str) or not isinstance(v, str) or not v for k, v in submitted_symbols.items())
                    or not isinstance(submitted_risk_quote, dict)
                    or any(not isinstance(k, str) or not isinstance(v, str) or not v for k, v in submitted_risk_quote.items())
                    or (last_result is not None and not isinstance(last_result, dict))):
                raise ValueError("Invalid lifecycle journal fields.")
            self._submitted_ids = set(submitted)
            self._submitted_symbols = dict(submitted_symbols)
            self._submitted_risk_quote = dict(submitted_risk_quote)
            self._halted = halted
            self._last_result = last_result
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
            # Corrupt or unreadable state must never permit a fresh order.
            self._journal_invalid = True
            self._halted = True
            self._last_result = {
                "status": "LIFECYCLE_JOURNAL_INVALID",
                "protected": False,
                "halted": True,
                "operator_action_required": True,
            }

    def _persist_state(self) -> None:
        if self._journal_path is None:
            return
        self._journal_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": self.JOURNAL_VERSION,
            "submitted_ids": sorted(self._submitted_ids),
            "submitted_symbols": self._submitted_symbols,
            "submitted_risk_quote": self._submitted_risk_quote,
            "halted": self._halted,
            "last_result": self._last_result,
        }
        fd, temporary = tempfile.mkstemp(
            prefix=self._journal_path.name + ".", suffix=".tmp",
            dir=str(self._journal_path.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, sort_keys=True, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self._journal_path)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

    @property
    def halted(self) -> bool:
        with self._lock:
            return self._halted

    @property
    def last_result(self) -> dict[str, Any] | None:
        with self._lock:
            return dict(self._last_result) if self._last_result else None

    def submit_and_verify(
        self, plan: BinanceOrderPlan, *, list_client_order_id: str
    ) -> dict[str, Any]:
        """Persist idempotency before submission; confirm exchange-held protection."""
        with self._lock:
            if self._halted:
                raise PermissionError(
                    "Binance execution is halted pending protection reconciliation."
                )
            if not list_client_order_id or len(list_client_order_id) > 20:
                raise ValueError("A unique order-list ID of at most 20 characters is required.")
            if list_client_order_id in self._submitted_ids:
                raise PermissionError("Duplicate order-list ID; refusing a second submission.")

            # Write-ahead record: if the process dies after this point, a new
            # process will reject the same ID instead of sending it twice.
            self._submitted_ids.add(list_client_order_id)
            self._submitted_symbols[list_client_order_id] = plan.symbol
            self._submitted_risk_quote[list_client_order_id] = str(plan.max_planned_loss_quote)
            try:
                self._persist_state()
            except Exception:
                self._submitted_ids.discard(list_client_order_id)
                self._submitted_symbols.pop(list_client_order_id, None)
                self._submitted_risk_quote.pop(list_client_order_id, None)
                raise

            try:
                submitted = self._gate.execute(
                    self._client, plan, list_client_order_id=list_client_order_id
                )
                reconcile = getattr(self._client, "reconcile_protected_buy_otoco", None)
                if not callable(reconcile):
                    raise RuntimeError("Client cannot reconcile protected order-list legs.")
                exchange_state = {}
                for attempt in range(self._reconcile_attempts):
                    exchange_state = reconcile(
                        symbol=plan.symbol, list_client_order_id=list_client_order_id
                    )
                    if not isinstance(exchange_state, dict):
                        raise RuntimeError("Exchange reconciliation returned an invalid response.")
                    if (
                        exchange_state.get("state") == "PROTECTED"
                        and exchange_state.get("protected") is True
                        and exchange_state.get("action_required") is False
                    ):
                        break
                    if attempt + 1 < self._reconcile_attempts:
                        self._wait(self._reconcile_interval_seconds)
                protected = (
                    exchange_state.get("state") == "PROTECTED"
                    and exchange_state.get("protected") is True
                    and exchange_state.get("action_required") is False
                )
                result = {
                    "status": "PROTECTED" if protected else "PROTECTION_UNCONFIRMED",
                    "protected": protected,
                    "halted": not protected,
                    "order_list_id": list_client_order_id,
                    "submission": submitted,
                    "exchange_state": exchange_state,
                    "operator_action_required": not protected,
                }
                self._halted = not protected
                self._last_result = result
                self._persist_state()
                return dict(result)
            except Exception:
                # The request may have reached Binance even if its response
                # was lost. Keep the ID and halt state durable; never retry.
                self._halted = True
                self._last_result = {
                    "status": "SUBMISSION_OR_RECONCILIATION_UNKNOWN",
                    "protected": False,
                    "halted": True,
                    "order_list_id": list_client_order_id,
                    "operator_action_required": True,
                }
                self._persist_state()
                raise

    def reconcile_existing(self, *, symbol: str, list_client_order_id: str) -> dict[str, Any]:
        """Refresh one order but preserve the aggregate state of every journaled order."""
        with self._lock:
            if self._journal_invalid:
                self._halted = True
                return self.reconcile_after_restart()
            normalized_symbol = symbol.strip().upper()
            if (not normalized_symbol or not list_client_order_id
                    or len(list_client_order_id) > 20):
                raise ValueError("A valid symbol and order-list ID are required.")
            existing_symbol = self._submitted_symbols.get(list_client_order_id)
            if existing_symbol and existing_symbol != normalized_symbol:
                self._halted = True
                raise PermissionError("Order-list ID is already journaled to a different symbol.")
            self._submitted_ids.add(list_client_order_id)
            self._submitted_symbols[list_client_order_id] = normalized_symbol
            self._persist_state()
            aggregate = self.reconcile_after_restart()
            matching = next(
                (item for item in aggregate.get("orders", [])
                 if item.get("order_list_id") == list_client_order_id),
                None,
            )
            result = dict(aggregate)
            result["order_list_id"] = list_client_order_id
            result["protected"] = bool(
                matching and matching.get("state") == "PROTECTED"
                and matching.get("safe") is True
            )
            return result

    def reconcile_after_restart(self) -> dict[str, Any]:
        """Reconcile every journaled order; never submit or silently clear unknown state."""
        with self._lock:
            if self._journal_invalid:
                self._halted = True
                result = {"status": "LIFECYCLE_JOURNAL_INVALID", "halted": True,
                          "reconciled": 0, "unresolved": [{"reason": "JOURNAL_CORRUPT"}],
                          "operator_action_required": True}
                self._last_result = result
                return dict(result)
            if not self._submitted_ids:
                self._halted = False
                result = {"status": "NO_JOURNALED_ORDERS", "halted": False,
                          "reconciled": 0, "unresolved": []}
                self._last_result = result
                self._persist_state()
                return dict(result)

            reconcile = getattr(self._client, "reconcile_protected_buy_otoco", None)
            if not callable(reconcile):
                self._halted = True
                raise RuntimeError("Client cannot reconcile journaled order lists.")

            results = []
            unresolved = []
            safe_states = {"PROTECTED", "NO_POSITION",
                           "EXITED_TAKE_PROFIT", "EXITED_STOP_LOSS"}
            for order_id in sorted(self._submitted_ids):
                symbol = self._submitted_symbols.get(order_id)
                if not symbol:
                    unresolved.append({"order_list_id": order_id,
                                       "reason": "SYMBOL_MISSING_FROM_LEGACY_JOURNAL"})
                    continue
                try:
                    state = reconcile(symbol=symbol, list_client_order_id=order_id)
                except Exception as exc:
                    unresolved.append({"order_list_id": order_id,
                                       "reason": "EXCHANGE_QUERY_FAILED",
                                       "error_type": type(exc).__name__})
                    continue
                if not isinstance(state, dict):
                    unresolved.append({"order_list_id": order_id,
                                       "reason": "INVALID_EXCHANGE_RECONCILIATION"})
                    continue
                state_name = state.get("state")
                safe = (state_name in safe_states and state.get("action_required") is False
                        and (state_name != "PROTECTED" or state.get("protected") is True))
                if state_name == "EXITED_STOP_LOSS":
                    planned_loss = self._submitted_risk_quote.get(order_id)
                    if not planned_loss:
                        safe = False
                        unresolved.append({"order_list_id": order_id,
                                           "reason": "STOP_LOSS_RISK_BASIS_MISSING"})
                    elif self._daily_loss_ledger is None:
                        safe = False
                        unresolved.append({"order_list_id": order_id,
                                           "reason": "DAILY_LOSS_LEDGER_UNAVAILABLE"})
                    else:
                        try:
                            self._daily_loss_ledger.record_stop_loss(
                                order_list_id=order_id, symbol=symbol,
                                planned_loss_quote=planned_loss,
                            )
                        except Exception as exc:
                            safe = False
                            unresolved.append({"order_list_id": order_id,
                                               "reason": "DAILY_LOSS_LEDGER_WRITE_FAILED",
                                               "error_type": type(exc).__name__})
                # Publish the final safety decision only after every required
                # accounting check has completed. In particular, an exchange-
                # confirmed stop-loss is not fully reconciled until its loss has
                # been durably recorded in the daily-loss ledger.
                results.append({"order_list_id": order_id, "symbol": symbol,
                                "state": state_name, "safe": safe})
                if not safe and not any(
                    item.get("order_list_id") == order_id for item in unresolved
                ):
                    unresolved.append({"order_list_id": order_id,
                                       "reason": "EXCHANGE_STATE_REQUIRES_REVIEW",
                                       "state": state_name})

            self._halted = bool(unresolved)
            result = {"status": "RECONCILED" if not unresolved else "RECONCILIATION_REQUIRED",
                      "halted": self._halted, "reconciled": len(results),
                      "orders": results, "unresolved": unresolved,
                      "operator_action_required": bool(unresolved)}
            self._last_result = result
            self._persist_state()
            return dict(result)
