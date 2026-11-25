import { useCallback, useEffect, useState } from "react";
import { Activity, LockKeyhole, PauseCircle, PlayCircle, RefreshCw, ShieldCheck } from "lucide-react";

type EngineStatus = {
  status?: string;
  reason?: string;
  enabled?: boolean;
  profile?: string;
  scoreThreshold?: number;
  symbols?: string[];
  tradingAuthorized?: boolean;
  tradingAccountCount?: number;
  environment?: string;
  liveTradingEnabled?: boolean;
  lastUpdatedAt?: string | null;
};

const STATUS_URL = "https://dominion-ai-trading-desk-p7cp.netlify.app/.netlify/functions/ctrader-engine-status";

export default function CTraderEngineControls() {
  const [status, setStatus] = useState<EngineStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  const refresh = useCallback(async () => {
    try {
      const response = await fetch(STATUS_URL, { cache: "no-store", credentials: "omit" });
      if (!response.ok) throw new Error("Status endpoint unavailable");
      setStatus(await response.json() as EngineStatus);
    } catch {
      setStatus(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 30000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const toggle = async () => {
    if (!status) return;
    const nextEnabled = !status.enabled;
    if (nextEnabled && !status.tradingAuthorized) {
      setMessage("Authorize cTrader demo trading permission before enabling automation.");
      return;
    }
    if (nextEnabled && !window.confirm(
      "Enable automatic trading on your Pepperstone DEMO account? The engine may open and close demo positions. It cannot place live-money orders."
    )) return;

    setBusy(true);
    setMessage("");
    try {
      const response = await fetch("/.netlify/functions/ctrader-control-proxy", {
        method: "POST",
        credentials: "include",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          enabled: nextEnabled,
          confirmDemoAutomation: nextEnabled,
          profile: status.profile || "intraday",
          scoreThreshold: status.scoreThreshold || 6,
          symbols: status.symbols || ["XAUUSD", "EURUSD", "GBPUSD"],
        }),
      });
      const result = await response.json() as { ok?: boolean; error?: string; enabled?: boolean };
      if (!response.ok || result.ok !== true) {
        throw new Error(result.error || "Could not update demo automation.");
      }
      setMessage(nextEnabled
        ? "Demo automation enabled. The scheduled engine will evaluate on its next cycle."
        : "Demo automation paused. Existing broker-side stop-loss and take-profit orders remain active.");
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Control request failed.");
    } finally {
      setBusy(false);
    }
  };

  const enabled = status?.enabled === true;
  const authorized = status?.tradingAuthorized === true;
  return <section className="agent-runtime-list ctrader-engine-panel">
    <div className="decision-list-head">
      <b>CTRADER / PEPPERSTONE DEMO ENGINE</b>
      <span>{loading ? "CHECKING" : enabled ? "AUTOMATION ENABLED" : "AUTOMATION PAUSED"}</span>
    </div>
    <div className="crypto-summary">
      <div><small>TRADING PERMISSION</small><b>{authorized ? "Verified · Demo" : "Not authorized"}</b></div>
      <div><small>ENGINE STATUS</small><b>{status?.status || (loading ? "Checking…" : "Not deployed")}</b></div>
      <div><small>STRATEGY PROFILE</small><b>{status?.profile || "Intraday"}</b></div>
      <div><small>CONFLUENCE SCORE</small><b>{status?.scoreThreshold ?? 6} / 15</b></div>
      <div><small>WATCHLIST</small><b>{(status?.symbols || ["XAUUSD", "EURUSD", "GBPUSD"]).join(", ")}</b></div>
      <div><small>EXECUTION MODE</small><b>Demo only · Live locked</b></div>
    </div>
    <div className="engine-control-actions">
      <button
        className={enabled ? "engine-stop" : "engine-start"}
        onClick={() => void toggle()}
        disabled={busy || loading || !status || (!authorized && !enabled)}
      >
        {busy ? <RefreshCw size={15} className="spin"/> : enabled ? <PauseCircle size={15}/> : <PlayCircle size={15}/>}
        {busy ? "Updating…" : enabled ? "Pause demo automation" : "Enable demo automation"}
      </button>
      <button className="engine-start" onClick={() => void refresh()} disabled={busy || loading}>
        <RefreshCw size={15}/> Refresh status
      </button>
    </div>
    <small className="engine-control-state">
      {message || (authorized
        ? "Scheduled evaluation runs every minute after the final deployment. Every order must pass server-side risk, margin, spread, slippage and protective-order checks."
        : "First complete the separate cTrader demo trading authorization. Your existing view-only authorization is preserved.")}
    </small>
    <div className="panel-foot"><ShieldCheck size={14}/> This control can enable demo orders only. Live-money trading remains disabled in code and is not available from this panel.</div>
  </section>;
}
