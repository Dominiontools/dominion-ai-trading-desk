import { submitCTraderDemoOrderOnce } from "./ctrader-order-submission.js";
import { confirmCTraderDemoOrderFromBroker } from "./ctrader-order-reconciliation.js";

/**
 * Submit one reserved demo order and persist a fill only when the execution
 * event carries the exact clientOrderId and a linked protected broker position.
 * Missing evidence leaves the durable intent unresolved and blocks new entries.
 */
export async function submitAndConfirmCTraderDemoOrder({
  db,
  session,
  accountId,
  clientOrderId,
  intent,
  order,
  management = {},
  nowMs = Date.now(),
  submitOnce = submitCTraderDemoOrderOnce,
  confirmFromBroker = confirmCTraderDemoOrderFromBroker
}) {
  const submission = await submitOnce({
    db, session, accountId, clientOrderId, intent, order, nowMs
  });
  if (!submission.submitted) {
    return { safe: false, status: submission.status, submission };
  }

  const execution = submission.brokerResponse;
  const brokerOrder = execution?.order;
  if (!brokerOrder || String(brokerOrder.clientOrderId ?? "") !== clientOrderId) {
    return {
      safe: false,
      status: "SUBMITTED_BROKER_ORDER_IDENTITY_UNCONFIRMED",
      clientOrderId,
      submission
    };
  }

  let brokerPosition = execution?.position ?? null;
  const linkedPositionId = String(brokerOrder.positionId ?? brokerPosition?.positionId ?? "");
  if (brokerPosition && linkedPositionId &&
      String(brokerPosition.positionId ?? "") !== linkedPositionId) {
    return {
      safe: false,
      status: "SUBMITTED_BROKER_POSITION_LINK_MISMATCH",
      clientOrderId,
      submission
    };
  }

  if (!brokerPosition && /^\d{1,30}$/.test(linkedPositionId)) {
    try {
      const snapshot = await session.reconcile();
      if (Array.isArray(snapshot?.positions)) {
        brokerPosition = snapshot.positions.find(
          (position) => String(position?.positionId ?? "") === linkedPositionId
        ) ?? null;
      }
    } catch {
      // Keep the intent SUBMITTED. A later reconciliation must resolve it.
    }
  }

  if (!brokerPosition) {
    return {
      safe: false,
      status: "SUBMITTED_BROKER_POSITION_NOT_CONFIRMED",
      clientOrderId,
      submission
    };
  }

  const confirmation = await confirmFromBroker({
    db,
    accountId,
    clientOrderId,
    fromState: "SUBMITTED",
    brokerOrder,
    brokerPosition,
    management,
    nowMs
  });
  return {
    safe: confirmation.confirmed === true && confirmation.safe === true,
    status: confirmation.status,
    clientOrderId,
    positionId: confirmation.positionId ?? null,
    submission,
    confirmation
  };
}
