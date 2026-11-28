import { useCallback, useEffect, useState } from "react";
import { PauseCircle, PlayCircle, RefreshCw, Save, ShieldCheck } from "lucide-react";

type EngineStatus = {
  status?: string;
  reason?: string;
  enabled?: boolean;
  profile?: string;
  scoreThreshold?: number;
  useSessionFilter?: boolean;
  riskPerTradePct?: number;
  dailyLossLimitPct?: number;
  symbols?: string[];
  tradingAuthorized?: boolean;
  tradingAccountCount?: number;
  environment?: string;
  liveTradingEnabled?: boolean;
  lastUpdatedAt?: string | null;
};

const STATUS_URL = "/api/ctrader/status";
const CONTROL_URL = "/api/ctrader/engine/control";

export default function CTraderEngineControls() {
  const [status, setStatus] = useState<EngineStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [dirty, setDirty] = useState(false);
  const [profile, setProfile] = useState("intraday");
  const [scoreThreshold, setScoreThreshold] = useState(6);
  const [symbolsInput, setSymbolsInput] = useState("XAUUSD, EURUSD, GBPUSD");
  const [useSessionFilter, setUseSessionFilter] = useState(true);
  const [riskPerTradePct, setRiskPerTradePct] = useState(0.5);
  const [dailyLossLimitPct, setDailyLossLimitPct] = useState(2);

  const refresh = useCallback(async () => {
    try {
      const response = await fetch(STATUS_URL, { cache: "no-store", credentials: "omit" });
      if (!response.ok) throw new Error("Status endpoint unavailable");
      const data = await response.json() as EngineStatus;
      setStatus(data);
      if (!dirty) {
        setProfile(data.profile || "intraday");
        setScoreThreshold(data.scoreThreshold ?? 6);
        setSymbolsInput((data.symbols || ["XAUUSD", "EURUSD", "GBPUSD"]).join(", "));
        setUseSessionFilter(data.useSessionFilter !== false);
        setRiskPerTradePct(data.riskPerTradePct ?? 0.5);
        setDailyLossLimitPct(data.dailyLossLimitPct ?? 2);
      }
    } catch {
      setStatus(null);
    } finally {
      setLoading(false);
    }
  }, [dirty]);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 30000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const submitConfig = async (enabled: boolean) => {
    const symbols = symbolsInput.split(",").map((item) => item.trim()).filter(Boolean);
    if (!symbols.length) {
      setMessage("Enter at least one broker symbol.");
      return;
    }
    setBusy(true);
    setMessage("");
    try {
      const response = await fetch(CONTROL_URL, {
        method: "POST",
        credentials: "include",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          enabled,
          confirmDemoAutomation: enabled,
          profile,
          scoreThreshold,
          useSessionFilter,
          riskPerTradePct,
          dailyLossLimitPct,
          symbols,
        }),
      });
      const result = await response.json() as { ok?: boolean; error?: string; enabled?: boolean };
      if (!response.ok || result.ok !== true) {
        throw new Error(result.error || "Could not update demo engine settings.");
      }
      setDirty(false);
      setMessage(enabled
        ? "Demo automation is enabled. The scheduled engine will evaluate on its next cycle."
        : "Strategy settings saved. Demo automation remains paused.");
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Control request failed.");
    } finally {
      setBusy(false);
    }
  };

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
    await submitConfig(nextEnabled);
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
      <div><small>FOREX / GOLD PROFILE</small><b>{profile}</b></div>
      <div><small>CONFLUENCE SCORE</small><b>{scoreThreshold} / 15</b></div>
      <div><small>WATCHLIST</small><b>{symbolsInput || "Not configured"}</b></div>
      <div><small>RISK / DAILY STOP</small><b>{riskPerTradePct}% / {dailyLossLimitPct}%</b></div>
      <div><small>EXECUTION MODE</small><b>Demo only · Live locked</b></div>
    </div>

    <div className="ctrader-config-grid">
      <label className="ctrader-config-field">
        <span>Forex & Gold timeframe profile</span>
        <select value={profile} onChange={(event) => { setProfile(event.target.value); setDirty(true); }}>
          <option value="scalp">Scalp · 5m / 1h</option>
          <option value="intraday">Intraday · 15m / 4h</option>
          <option value="swing">Swing · 4h / 1d</option>
        </select>
      </label>
      <label className="ctrader-config-field">
        <span>Minimum confluence score</span>
        <input type="number" min={1} max={15} step={1} value={scoreThreshold}
          onChange={(event) => { setScoreThreshold(Number(event.target.value)); setDirty(true); }}/>
      </label>
      <label className="ctrader-config-field">
        <span>Risk per trade · maximum 0.5%</span>
        <input type="number" min={0.05} max={0.5} step={0.05} value={riskPerTradePct}
          onChange={(event) => { setRiskPerTradePct(Number(event.target.value)); setDirty(true); }}/>
      </label>
      <label className="ctrader-config-field">
        <span>Daily loss stop · maximum 2%</span>
        <input type="number" min={0.5} max={2} step={0.25} value={dailyLossLimitPct}
          onChange={(event) => { setDailyLossLimitPct(Number(event.target.value)); setDirty(true); }}/>
      </label>
      <label className="ctrader-config-field ctrader-symbol-field">
        <span>Broker symbols · comma separated</span>
        <input type="text" value={symbolsInput}
          placeholder="XAUUSD, EURUSD, GBPUSD"
          onChange={(event) => { setSymbolsInput(event.target.value); setDirty(true); }}/>
      </label>
      <label className="ctrader-session-toggle">
        <input type="checkbox" checked={useSessionFilter}
          onChange={(event) => { setUseSessionFilter(event.target.checked); setDirty(true); }}/>
        <span>Trade only during London and New York sessions</span>
      </label>
    </div>
    <div className="panel-foot">These candle timeframes apply only to the cTrader Forex/Gold strategy. Crypto uses a separate continuous cross-exchange scanner with a one-second scan target; it does not use this Forex timeframe profile.</div>

    <div className="engine-control-actions">
      <button className="engine-start" onClick={() => void submitConfig(enabled)} disabled={busy || loading || !status}>
        {busy ? <RefreshCw size={15} className="spin"/> : <Save size={15}/>}
        {busy ? "Saving…" : "Save strategy settings"}
      </button>
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
        ? "The scheduled engine evaluates every minute after final deployment. Pausing blocks new entries but continues managing an existing bot position. Each order must pass server-side risk, margin, spread, slippage and protective-order checks."
        : "First complete the separate cTrader demo trading authorization. Your existing view-only authorization is preserved.")}
    </small>
    <div className="panel-foot"><ShieldCheck size={14}/> This control can enable demo orders only. Live-money trading remains disabled in code and is not available from this panel.</div>
  </section>;
}
