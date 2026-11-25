"""Single-submit, fail-closed Binance Spot Testnet protected-order lifecycle.

This coordinator is deliberately not wired to the phone strategy loop yet.
It prevents duplicate submissions within its lifetime and never reports an
entry as protected until the exchange confirms both OCO exit legs are active.
An unconfirmed bracket halts further submissions and requires operator review.
"""
from __future__ import annotations

from threading import RLock
from time import sleep
from typing import Any, Callable

from engine.risk_execution import BinanceOrderPlan, BinanceTestnetRiskGate


class BinanceProtectedLifecycle:
    """Coordinate one protected order-list submission and its verification."""

    def __init__(
        self,
        gate: BinanceTestnetRiskGate,
        client: Any,
        *,
        reconcile_attempts: int = 4,
        reconcile_interval_seconds: float = 0.25,
        wait: Callable[[float], None] = sleep,
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
        self._submitted_ids: set[str] = set()
        self._halted = False
        self._last_result: dict[str, Any] | None = None

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
        """Submit once, then reconcile exchange state before reporting protection."""
        with self._lock:
            if self._halted:
                raise PermissionError(
                    "Binance execution is halted pending protection reconciliation."
                )
            if not list_client_order_id or len(list_client_order_id) > 20:
                raise ValueError("A unique order-list ID of at most 20 characters is required.")
            if list_client_order_id in self._submitted_ids:
                raise PermissionError("Duplicate order-list ID; refusing a second submission.")
            self._submitted_ids.add(list_client_order_id)

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
                    # Binance may initially report child OCO legs as
                    # PENDING_NEW immediately after the working order fills.
                    # Re-query briefly; never treat pending as protected.
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
                if not protected:
                    self._halted = True
                self._last_result = result
                return dict(result)
            except Exception:
                # The submission may have reached the exchange even if the
                # response was lost. Never retry automatically with a new ID.
                self._halted = True
                self._last_result = {
                    "status": "SUBMISSION_OR_RECONCILIATION_UNKNOWN",
                    "protected": False,
                    "halted": True,
                    "order_list_id": list_client_order_id,
                    "operator_action_required": True,
                }
                raise

    def reconcile_existing(self, *, symbol: str, list_client_order_id: str) -> dict[str, Any]:
        """Refresh an existing order-list state without submitting another order."""
        with self._lock:
            reconcile = getattr(self._client, "reconcile_protected_buy_otoco", None)
            if not callable(reconcile):
                self._halted = True
                raise RuntimeError("Client cannot reconcile protected order-list legs.")
            state = reconcile(symbol=symbol, list_client_order_id=list_client_order_id)
            if not isinstance(state, dict):
                self._halted = True
                raise RuntimeError("Exchange reconciliation returned an invalid response.")
            protected = (
                state.get("state") == "PROTECTED"
                and state.get("protected") is True
                and state.get("action_required") is False
            )
            result = {
                "status": "PROTECTED" if protected else "PROTECTION_UNCONFIRMED",
                "protected": protected,
                "halted": not protected,
                "order_list_id": list_client_order_id,
                "exchange_state": state,
                "operator_action_required": not protected,
            }
            self._halted = not protected
            self._last_result = result
            return dict(result)
