import {
  acquireExecutionLock,
  releaseExecutionLock
} from "./ctrader-d1-store.js";
import { readCTraderEngineConfig } from "./ctrader-engine-config-store.js";
import { readCTraderEngineStatus } from "./ctrader-engine-status-store.js";
import { loadUsableCTraderToken } from "./ctrader-token-service.js";
import { CTraderDemoSession } from "./ctrader-demo-session.js";
import {
  appendCTraderEngineEvent,
  readCTraderActivePosition,
  readUnresolvedCTraderOrderIntents
} from "./ctrader-execution-recovery-store.js";
import {
  assertNoUnresolvedCTraderOrderIntents,
  reconcileCTraderPositionState
} from "./ctrader-execution-reconciliation.js";
import { evaluateCTraderDemoSession } from "./ctrader-session-guard.js";

const DEFAULT_SERVICES = {
  readConfig: readCTraderEngineConfig,
  readStatus: readCTraderEngineStatus,
  loadToken: loadUsableCTraderToken,
  acquireLock: acquireExecutionLock,
  releaseLock: releaseExecutionLock,
  readPosition: readCTraderActivePosition,
  readIntents: readUnresolvedCTraderOrderIntents,
  appendEvent: appendCTraderEngineEvent,
  reconcilePosition: reconcileCTraderPositionState,
  assertNoUnresolved: assertNoUnresolvedCTraderOrderIntents,
  evaluateSession: evaluateCTraderDemoSession
};

/**
 * Establish a short-lived, authenticated demo session and reconcile all durable
 * recovery state before a future strategy cycle is allowed to evaluate an entry.
 * This function intentionally DOES NOT place, amend, or close broker orders.
 */
export async function reconcileCTraderDemoCycle({
  db,
  env,
  nowMs = Date.now(),
  sessionFactory = () => new CTraderDemoSession(),
  services = {}
}) {
  const api = { ...DEFAULT_SERVICES, ...services };
  if (!db || typeof db.prepare !== "function" ||
      !env || typeof env.CTRADER_TOKEN_ENCRYPTION_KEY !== "string" ||
      typeof env.CTRADER_CLIENT_ID !== "string" ||
      typeof env.CTRADER_CLIENT_SECRET !== "string" ||
      !Number.isSafeInteger(nowMs) || nowMs <= 0) {
    return { safe: false, status: "BLOCKED", reason: "CYCLE_CONFIGURATION_INCOMPLETE" };
  }

  let lock = null;
  let session = null;
  try {
    const [savedConfig, savedStatus] = await Promise.all([
      api.readConfig(db), api.readStatus(db)
    ]);
    const config = savedConfig?.config;
    if (!config || config.environment !== "demo" || config.enabled !== true ||
        config.maxRiskPerTradePct !== 0.5 || config.maxDailyLossPct !== 2 ||
        config.maxOpenPositions !== 1) {
      return { safe: false, status: "PAUSED", reason: "DEMO_AUTOMATION_NOT_ENABLED_OR_CONFIG_INVALID" };
    }
    if (!savedStatus?.connected || savedStatus.environment !== "demo" ||
        savedStatus.isLive !== false || savedStatus.access !== "trading" ||
        savedStatus.permissionScope !== 1 || savedStatus.liveTradingEnabled !== false) {
      return { safe: false, status: "BLOCKED", reason: "VERIFIED_DEMO_TRADING_AUTHORIZATION_REQUIRED" };
    }

    const token = await api.loadToken({
      db,
      tokenKind: "trading",
      encryptionKey: env.CTRADER_TOKEN_ENCRYPTION_KEY,
      clientId: env.CTRADER_CLIENT_ID,
      clientSecret: env.CTRADER_CLIENT_SECRET,
      nowMs
    });
    if (!token || token.environment !== "demo" || token.access !== "trading" ||
        String(token.accountId ?? "") === "" ||
        !Number.isSafeInteger(token.expiresAt) || token.expiresAt <= nowMs) {
      return { safe: false, status: "BLOCKED", reason: "DEMO_TRADING_TOKEN_UNAVAILABLE" };
    }

    const lockId = crypto.randomUUID();
    const lockName = `ctrader-demo-${token.accountId}`;
    lock = await api.acquireLock(db, lockName, lockId, nowMs, 300_000);
    if (!lock) return { safe: false, status: "BLOCKED", reason: "EXECUTION_LOCKED" };

    session = sessionFactory();
    await session.connect();
    await session.authorize(
      token.accessToken, token.accountId, env.CTRADER_CLIENT_ID, env.CTRADER_CLIENT_SECRET
    );
    const brokerState = await session.reconcile();
    if (!brokerState || !Array.isArray(brokerState.positions) || !Array.isArray(brokerState.orders)) {
      throw new Error("Broker reconciliation response is incomplete.");
    }

    const [storedPosition, unresolvedIntents] = await Promise.all([
      api.readPosition(db, token.accountId),
      api.readIntents(db, token.accountId)
    ]);
    const positionState = api.reconcilePosition({
      brokerPositions: brokerState.positions,
      storedPosition
    });
    if (!positionState.safe) {
      await api.appendEvent(db, {
        accountId: token.accountId,
        eventType: "BROKER_D1_MISMATCH",
        event: { reason: positionState.reason, mismatches: positionState.mismatches ?? [] },
        nowMs
      });
      return {
        safe: false, status: "BLOCKED",
        reason: positionState.reason,
        brokerPositionCount: brokerState.positions.length
      };
    }

    const intentState = api.assertNoUnresolved(unresolvedIntents);
    if (!intentState.safe) {
      await api.appendEvent(db, {
        accountId: token.accountId,
        eventType: "UNRESOLVED_ORDER_INTENT",
        event: { count: unresolvedIntents.length },
        nowMs
      });
      return { safe: false, status: "BLOCKED", reason: "UNRESOLVED_ORDER_INTENT" };
    }
    if (brokerState.orders.length > 0) {
      await api.appendEvent(db, {
        accountId: token.accountId,
        eventType: "PENDING_BROKER_ORDER",
        event: { count: brokerState.orders.length },
        nowMs
      });
      return { safe: false, status: "BLOCKED", reason: "PENDING_BROKER_ORDER" };
    }

    const sessionGate = api.evaluateSession({
      liveTradingEnabled: false,
      automationEnabled: true,
      connected: true,
      authenticated: true,
      environment: "demo",
      isLive: false,
      permissionScope: 1,
      lastHeartbeatAt: session.lastMessageAt
    }, nowMs);
    if (!sessionGate.allowed) {
      return { safe: false, status: "BLOCKED", reason: "DEMO_SESSION_GUARD_REJECTED" };
    }

    await api.appendEvent(db, {
      accountId: token.accountId,
      eventType: "CYCLE_PREFLIGHT_RECONCILED",
      event: { state: positionState.state, brokerPositionCount: brokerState.positions.length },
      nowMs
    });
    return {
      safe: true,
      status: "RECONCILED",
      state: positionState.state,
      accountId: token.accountId,
      config,
      position: positionState
    };
  } catch {
    return { safe: false, status: "BLOCKED", reason: "DEMO_CYCLE_PREFLIGHT_FAILED" };
  } finally {
    if (session) {
      try { await session.close(); } catch { /* close is best-effort; no order is submitted here */ }
    }
    if (lock) {
      try { await api.releaseLock(db, lock.lockName, lock.lockId); } catch { /* lease expires safely */ }
    }
  }
}
