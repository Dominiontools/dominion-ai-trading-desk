const DEFAULT_HEARTBEAT_MAX_AGE_MS = 15_000;

/**
 * Pure fail-closed gate for a future cTrader demo execution cycle.
 * This function never connects to cTrader and never places orders.
 */
export function evaluateCTraderDemoSession(input, nowMs = Date.now()) {
  const fail = (reason) => ({ allowed: false, reason });
  if (!input || typeof input !== "object") return fail("missing_session");
  if (input.liveTradingEnabled !== false) return fail("live_trading_must_remain_disabled");
  if (input.automationEnabled !== true) return fail("demo_automation_not_enabled");
  if (input.connected !== true || input.authenticated !== true) return fail("broker_session_not_authenticated");
  if (input.environment !== "demo" || input.isLive !== false) return fail("demo_account_not_verified");
  if (input.permissionScope !== 1) return fail("trading_scope_not_verified");
  if (!Number.isSafeInteger(nowMs) || !Number.isSafeInteger(input.lastHeartbeatAt)) {
    return fail("heartbeat_timestamp_missing");
  }
  const ageMs = nowMs - input.lastHeartbeatAt;
  if (ageMs < 0 || ageMs > DEFAULT_HEARTBEAT_MAX_AGE_MS) {
    return fail("broker_heartbeat_stale");
  }
  return { allowed: true, reason: "verified_demo_session" };
}

/**
 * Bounded exponential backoff with injectable randomness for deterministic tests.
 * The caller must still enforce a reconnect attempt budget and a fail-closed state.
 */
export function getCTraderReconnectDelayMs(attempt, options = {}) {
  const baseMs = options.baseMs ?? 1_000;
  const maxMs = options.maxMs ?? 30_000;
  const jitterRatio = options.jitterRatio ?? 0.2;
  const random = options.random ?? Math.random;

  if (!Number.isSafeInteger(attempt) || attempt < 0 ||
      !Number.isFinite(baseMs) || baseMs < 1 ||
      !Number.isFinite(maxMs) || maxMs < baseMs ||
      !Number.isFinite(jitterRatio) || jitterRatio < 0 || jitterRatio > 1 ||
      typeof random !== "function") {
    throw new Error("Invalid cTrader reconnect backoff options.");
  }

  const exponential = Math.min(maxMs, baseMs * (2 ** Math.min(attempt, 30)));
  const jitter = exponential * jitterRatio * ((random() * 2) - 1);
  return Math.max(1, Math.min(maxMs, Math.round(exponential + jitter)));
}
