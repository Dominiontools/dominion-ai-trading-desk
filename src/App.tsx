import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { Capacitor, registerPlugin } from "@capacitor/core";
import { Activity, ArrowDownRight, ArrowUpRight, Bot, CircleDollarSign, Gauge, LockKeyhole, Radar, ShieldCheck, Wallet, Waves } from "lucide-react";
import CTraderEngineControls from "./CTraderEngineControls";
interface TradingEngineBridge {
  start(): Promise<{ accepted: boolean }>;
  stop(): Promise<{ stopped: boolean }>;
  status(): Promise<{ running: boolean; error?: string }>;
  saveBinanceTestnetCredentials(options: { apiKey: string; apiSecret: string }): Promise<{ saved: boolean; storage: string }>;
  binanceTestnetCredentialStatus(): Promise<{ saved: boolean; storage: string }>;
  getBinanceTestnetAccount(): Promise<{ connected: boolean; environment?: string; can_trade?: boolean; can_withdraw?: boolean; account_type?: string; balances?: { asset: string; free: string; locked: string }[]; error?: string; exchange_code?: number | null }>;
  clearBinanceTestnetCredentials(): Promise<{ cleared: boolean }>;
  saveGmgnApiKey(options: { apiKey: string }): Promise<{ saved: boolean; storage: string }>;
  gmgnApiKeyStatus(): Promise<{ saved: boolean; storage: string }>;
  clearGmgnApiKey(): Promise<{ cleared: boolean }>;
}
const TradingEngine = registerPlugin<TradingEngineBridge>("TradingEngine");


type Market = "All markets" | "Forex & Gold" | "Crypto";
const agents = [
  ["SCANNER", "Market discovery", "Watching configured symbols", Radar],
  ["RISK", "Pre-trade protection", "Awaiting candidate setup", ShieldCheck],
  ["SNIPER", "Order execution", "Simulation adapter only", Activity],
  ["WHALE", "Large participant flow", "Data connection pending", Waves],
  ["RUG", "Market integrity", "Checks available when data connects", LockKeyhole],
  ["EXIT", "Position management", "Stops and targets engine staged", ArrowDownRight],
  ["HYPE", "News & sentiment", "Sentiment feed pending", Gauge],
  ["DESK MANAGER", "Agent coordination", "Supervising demo environment", Bot]
] as const;

const watch = [
  { symbol: "XAUUSD", name: "Gold / US Dollar", price: "Not connected", change: "—", group: "Forex & Gold", tone: "up" },
  { symbol: "EURUSD", name: "Euro / US Dollar", price: "Not connected", change: "—", group: "Forex & Gold", tone: "up" },
  { symbol: "GBPUSD", name: "Pound / US Dollar", price: "Not connected", change: "—", group: "Forex & Gold", tone: "down" },
  { symbol: "BTCUSDT", name: "Bitcoin / Tether", price: "Not connected", change: "—", group: "Crypto", tone: "up" },
  { symbol: "ETHUSDT", name: "Ethereum / Tether", price: "Not connected", change: "—", group: "Crypto", tone: "down" },
  { symbol: "PAXGUSDT", name: "PAX Gold / Tether", price: "Not connected", change: "—", group: "Crypto", tone: "up" }
];

export default function App() {
  const [market, setMarket] = useState<Market>("All markets");
  const filtered = useMemo(() => market === "All markets" ? watch : watch.filter(x => x.group === market), [market]);

  return <main className="shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark">D</div><div><b>DOMINION</b><span>AI TRADING DESK</span></div></div>
      <div className="side-label">WORKSPACE</div>
      <a className="nav active"><Gauge size={17}/> Overview</a>
      <a className="nav"><Radar size={17}/> Market scanner</a>
      <a className="nav"><Bot size={17}/> Agent control</a>
      <a className="nav"><Wallet size={17}/> Positions</a>
      <a className="nav"><Activity size={17}/> Activity log</a>
      <div className="side-bottom"><div className="connection-dot"/> Local dashboard<br/><small>Broker connection not configured</small></div>
    </aside>

    <section className="content">
      <header className="topbar">
        <div><div className="eyebrow">CONTROL CENTER / OVERVIEW</div><h1>Trading command center</h1></div>
        <div className="top-actions"><span className="demo-pill"><span/> DEMO + PAPER ONLY</span><span className="muted">cTrader scheduled engine · Crypto phone monitor</span></div>
      </header>

      <div className="notice"><LockKeyhole size={18}/><div><b>Protected development environment</b><span>Live-money orders are disabled. cTrader demo orders require separate trading authorization and explicit automation enablement; crypto remains paper/testnet only.</span></div></div>

      <CTraderEngineControls />

      <div className="metric-grid">
        <Metric icon={<CircleDollarSign/>} label="Starting capital" value="$20.00" note="Planned balance · not an account connection"/>
        <Metric icon={<Activity/>} label="Open positions" value="—" note="Broker account not connected"/>
        <Metric icon={<ShieldCheck/>} label="Risk policy" value="0.5% / 2%" note="Per trade / daily stop" positive/>
        <Metric icon={<Gauge/>} label="Today's P/L" value="—" note="No account connection"/>
      </div>

      <div className="section-head"><div><div className="eyebrow">MARKET MONITOR</div><h2>Watchlist</h2></div><select value={market} onChange={e => setMarket(e.target.value as Market)}><option>All markets</option><option>Forex & Gold</option><option>Crypto</option></select></div>
      <div className="panel watch-panel">
        <div className="table-head"><span>INSTRUMENT</span><span>LAST PRICE</span><span>24H CHANGE</span><span>FEED STATUS</span></div>
        {filtered.map(item => <div className="watch-row" key={item.symbol}><div className="instrument"><b>{item.symbol}</b><small>{item.name}</small></div><b className="price">{item.price}</b><span className={item.tone === "up" ? "positive" : "negative"}>{item.tone === "up" ? <ArrowUpRight size={14}/> : <ArrowDownRight size={14}/>} {item.change}</span><span className="feed-pending">Awaiting data</span></div>)}
        <div className="panel-foot">No fabricated prices. Forex and gold will show live data after cTrader is connected; crypto snapshots appear in the paper monitor below.</div>
      </div>

      <CryptoMonitorPanel />

      <div className="section-head agent-heading"><div><div className="eyebrow">AUTONOMOUS WORKFORCE</div><h2>Eight-agent components</h2></div><span className="muted">Actual readiness is reported in the runtime panel above</span></div>
      <div className="agent-grid">{agents.map(([name, role, status, Icon], i) => <div className="agent-card" key={name}><div className="agent-top"><div className="agent-icon"><Icon size={18}/></div><span className="agent-state">COMPONENT</span></div><b>{name}</b><small>{role}</small><p>{status}</p></div>)}</div>
      <footer>DOMINION AI TRADING DESK <span>FOUNDATION BUILD · DEMO ONLY · v0.1.0</span></footer>
    </section>
  </main>;
}

function Metric({ icon, label, value, note, positive = false }: { icon: ReactNode; label: string; value: string; note: string; positive?: boolean }) {
  return <div className="metric"><div className="metric-icon">{icon}</div><span>{label}</span><strong className={positive ? "positive" : ""}>{value}</strong><small>{note}</small></div>;
}


function CryptoMonitorPanel() {
  const [status, setStatus] = useState<Record<string, unknown> | null>(null);
  const [decisions, setDecisions] = useState<Record<string, unknown>[]>([]);
  const [latestQuotes, setLatestQuotes] = useState<Record<string, unknown>[]>([]);
  const [connection, setConnection] = useState<"checking" | "connected" | "offline">("checking");
  const [lastUpdated, setLastUpdated] = useState("");
  const [testnetApiKey, setTestnetApiKey] = useState("");
  const [testnetApiSecret, setTestnetApiSecret] = useState("");
  const [credentialSaved, setCredentialSaved] = useState(false);
  const [credentialMessage, setCredentialMessage] = useState("Credentials not saved");
  const [credentialBusy, setCredentialBusy] = useState(false);
  const [testnetAccount, setTestnetAccount] = useState<{ connected: boolean; environment?: string; can_trade?: boolean; can_withdraw?: boolean; account_type?: string; balances?: { asset: string; free: string; locked: string }[]; error?: string; exchange_code?: number | null } | null>(null);
  const [accountBusy, setAccountBusy] = useState(false);
  const [gmgnApiKey, setGmgnApiKey] = useState("");
  const [gmgnKeySaved, setGmgnKeySaved] = useState(false);
  const [gmgnKeyBusy, setGmgnKeyBusy] = useState(false);
  const [gmgnKeyMessage, setGmgnKeyMessage] = useState("GMGN API key not configured");
  const [engineControl, setEngineControl] = useState<"web" | "stopped" | "starting" | "running" | "error">(
    Capacitor.isNativePlatform() ? "stopped" : "web"
  );
  const isNativeApp = Capacitor.isNativePlatform();

  useEffect(() => {
    if (!isNativeApp) return;
    void Promise.all([
      TradingEngine.binanceTestnetCredentialStatus(),
      TradingEngine.gmgnApiKeyStatus()
    ]).then(([binance, gmgn]) => {
      setCredentialSaved(binance.saved);
      setCredentialMessage(binance.saved ? "Encrypted credentials are stored on this phone." : "Credentials not saved");
      setGmgnKeySaved(gmgn.saved);
      setGmgnKeyMessage(gmgn.saved ? "GMGN API key is encrypted on this phone." : "GMGN API key not configured");
    }).catch(() => {
      setCredentialMessage("Secure storage status unavailable");
      setGmgnKeyMessage("Secure storage status unavailable");
    });
  }, [isNativeApp]);

  const saveTestnetCredentials = useCallback(async () => {
    if (!isNativeApp || !testnetApiKey.trim() || !testnetApiSecret.trim()) return;
    setCredentialBusy(true);
    setCredentialMessage("Encrypting credentials on this phone…");
    try {
      const result = await TradingEngine.saveBinanceTestnetCredentials({
        apiKey: testnetApiKey.trim(),
        apiSecret: testnetApiSecret.trim()
      });
      setCredentialSaved(result.saved);
      setTestnetApiKey("");
      setTestnetApiSecret("");
      setCredentialMessage("Saved in Android Keystore encrypted storage. Secret cleared from the form.");
    } catch {
      setCredentialMessage("Could not save credentials. Check the Testnet key and try again.");
    } finally {
      setCredentialBusy(false);
    }
  }, [isNativeApp, testnetApiKey, testnetApiSecret]);

  const checkTestnetAccount = useCallback(async () => {
    if (!isNativeApp || !credentialSaved) return;
    setAccountBusy(true);
    setTestnetAccount(null);
    try {
      const result = await TradingEngine.getBinanceTestnetAccount();
      setTestnetAccount(result);
      setCredentialMessage(result.connected ? "Connected to Binance Spot Testnet (read-only account check)." : "Testnet account check failed. Verify credentials and network.");
    } catch {
      setTestnetAccount({ connected: false, error: "ACCOUNT_CHECK_FAILED" });
      setCredentialMessage("Could not check the Testnet account.");
    } finally {
      setAccountBusy(false);
    }
  }, [isNativeApp, credentialSaved]);

  const clearTestnetCredentials = useCallback(async () => {
    if (!isNativeApp) return;
    setCredentialBusy(true);
    try {
      await TradingEngine.clearBinanceTestnetCredentials();
      setCredentialSaved(false);
      setTestnetAccount(null);
      setTestnetApiKey("");
      setTestnetApiSecret("");
      setCredentialMessage("Stored credentials and their encryption key were cleared.");
    } catch {
      setCredentialMessage("Could not clear the stored credentials.");
    } finally {
      setCredentialBusy(false);
    }
  }, [isNativeApp]);

  const saveGmgnKey = useCallback(async () => {
    if (!isNativeApp || !gmgnApiKey.trim()) return;
    setGmgnKeyBusy(true);
    setGmgnKeyMessage("Encrypting GMGN API key on this phone…");
    try {
      const result = await TradingEngine.saveGmgnApiKey({ apiKey: gmgnApiKey.trim() });
      setGmgnKeySaved(result.saved);
      setGmgnApiKey("");
      setGmgnKeyMessage("Saved in Android Keystore. Stop and restart the phone engine to load GMGN data.");
    } catch {
      setGmgnKeyMessage("Could not save GMGN API key. Check the key and try again.");
    } finally {
      setGmgnKeyBusy(false);
    }
  }, [isNativeApp, gmgnApiKey]);

  const clearGmgnKey = useCallback(async () => {
    if (!isNativeApp) return;
    setGmgnKeyBusy(true);
    try {
      await TradingEngine.clearGmgnApiKey();
      setGmgnKeySaved(false);
      setGmgnApiKey("");
      setGmgnKeyMessage("GMGN API key and encrypted record cleared.");
    } catch {
      setGmgnKeyMessage("Could not clear the GMGN API key.");
    } finally {
      setGmgnKeyBusy(false);
    }
  }, [isNativeApp]);

  const startPhoneEngine = useCallback(async () => {
    if (!isNativeApp) return;
    setEngineControl("starting");
    try {
      await TradingEngine.start();
    } catch {
      setEngineControl("error");
    }
  }, [isNativeApp]);

  const stopPhoneEngine = useCallback(async () => {
    if (!isNativeApp) return;
    try {
      await TradingEngine.stop();
      setEngineControl("stopped");
    } catch {
      setEngineControl("error");
    }
  }, [isNativeApp]);

  const refresh = useCallback(async () => {
    if (isNativeApp) {
      try {
        const nativeStatus = await TradingEngine.status();
        setEngineControl(nativeStatus.running ? "running" : nativeStatus.error ? "error" : "stopped");
      } catch {
        setEngineControl("error");
      }
    }
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 2500);
    try {
      const [statusResponse, decisionsResponse] = await Promise.all([
        fetch("http://localhost:8766/api/crypto/status", { cache: "no-store", signal: controller.signal, credentials: "omit" }),
        fetch("http://localhost:8766/api/crypto/decisions?limit=20", { cache: "no-store", signal: controller.signal, credentials: "omit" })
      ]);
      if (!statusResponse.ok || !decisionsResponse.ok) throw new Error("Local API unavailable");
      const statusData = await statusResponse.json() as Record<string, unknown>;
      const decisionData = await decisionsResponse.json() as { items?: unknown };
      setStatus(statusData);
      const items = Array.isArray(decisionData.items) ? decisionData.items.filter((item): item is Record<string, unknown> => !!item && typeof item === "object") : [];
      setDecisions(items);
      const quoteRows: Record<string, unknown>[] = [];
      const seenQuotes = new Set<string>();
      for (const record of items) {
        const recordQuotes = Array.isArray(record.quotes_preview)
          ? record.quotes_preview
          : Array.isArray(record.quotes) ? record.quotes : [];
        for (const quote of recordQuotes) {
          if (!quote || typeof quote !== "object") continue;
          const row = quote as Record<string, unknown>;
          const quoteSymbol = String(row.symbol || record.symbol);
          const key = quoteSymbol + ":" + String(row.exchange);
          if (seenQuotes.has(key)) continue;
          seenQuotes.add(key);
          quoteRows.push({ ...row, symbol: quoteSymbol });
        }
      }
      setLatestQuotes(quoteRows);
      setConnection("connected");
      setLastUpdated(new Date().toLocaleTimeString());
    } catch {
      setConnection("offline");
      setStatus(null);
      setDecisions([]);
      setLatestQuotes([]);
    } finally {
      window.clearTimeout(timeout);
    }
  }, [isNativeApp]);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 5000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const engine = typeof status?.engine === "string" ? status.engine : typeof status?.status === "string" ? status.status : "Status unavailable";
  const paperTrading = status?.paper_trading && typeof status.paper_trading === "object"
    ? status.paper_trading as Record<string, unknown>
    : null;
  const paperPosition = paperTrading?.open_position && typeof paperTrading.open_position === "object"
    ? paperTrading.open_position as Record<string, unknown>
    : null;
  const strategyEngine = status?.strategy_engine && typeof status.strategy_engine === "object"
    ? status.strategy_engine as Record<string, unknown>
    : null;
  const arbitrageScanner = status?.arbitrage_scanner && typeof status.arbitrage_scanner === "object"
    ? status.arbitrage_scanner as Record<string, unknown>
    : null;
  const arbitrageUniverse = status?.arbitrage_universe && typeof status.arbitrage_universe === "object"
    ? status.arbitrage_universe as Record<string, unknown>
    : null;
  const scannerOpportunities = Array.isArray(arbitrageScanner?.opportunities)
    ? arbitrageScanner.opportunities.filter((item): item is Record<string, unknown> => !!item && typeof item === "object")
    : [];
  const gmgnFeed = status?.gmgn_feed && typeof status.gmgn_feed === "object"
    ? status.gmgn_feed as Record<string, unknown>
    : null;
  const gmgnTokens = Array.isArray(gmgnFeed?.tokens)
    ? gmgnFeed.tokens.filter((item): item is Record<string, unknown> => !!item && typeof item === "object")
    : [];
  const gmgnSniper = status?.gmgn_sniper && typeof status.gmgn_sniper === "object"
    ? status.gmgn_sniper as Record<string, unknown>
    : null;
  const gmgnSniperCandidates = Array.isArray(gmgnSniper?.candidates)
    ? gmgnSniper.candidates.filter((item): item is Record<string, unknown> => !!item && typeof item === "object")
    : [];
  const paperTrades = Array.isArray(paperTrading?.recent_trades)
    ? (paperTrading.recent_trades as Record<string, unknown>[]).slice(-5).reverse()
    : [];
  const agentStates = status?.agents && typeof status.agents === "object"
    ? status.agents as Record<string, { status?: unknown; detail?: unknown }>
    : {};
  const readiness = status?.integration_readiness && typeof status.integration_readiness === "object"
    ? status.integration_readiness as { overall_status?: unknown; verified_tasks?: unknown; total_tasks?: unknown; tasks?: unknown }
    : null;
  const readinessTasks = Array.isArray(readiness?.tasks)
    ? readiness.tasks.filter((task): task is Record<string, unknown> => !!task && typeof task === "object")
    : [];
  return <section className="crypto-monitor">
    <div className="section-head"><div><div className="eyebrow">CRYPTO / CROSS-EXCHANGE</div><h2>Paper arbitrage monitor</h2></div><span className={"monitor-state " + connection}><i/> {connection === "connected" ? "LOCAL API CONNECTED" : connection === "checking" ? "CHECKING LOCAL API" : "LOCAL API OFFLINE"}</span></div>
    <div className="engine-controls">
      <div className="engine-controls-copy"><b>On-device paper engine</b><span>{isNativeApp ? "Runs inside this app as an Android foreground service." : "Install the Android app to control the on-device service."}</span></div>
      <div className="engine-control-actions">
        <button className="engine-start" onClick={() => void startPhoneEngine()} disabled={!isNativeApp || engineControl === "starting" || engineControl === "running"}>Start phone engine</button>
        <button className="engine-stop" onClick={() => void stopPhoneEngine()} disabled={!isNativeApp || engineControl === "stopped" || engineControl === "web"}>Stop</button>
      </div>
      <small className={"engine-control-state " + engineControl}>Phone service: {engineControl === "web" ? "Android app required" : engineControl}</small>
    </div>
    <div className="agent-runtime-list credential-panel">
      <div className="decision-list-head"><b>GMGN OFFICIAL API · READ ONLY</b><span>{gmgnKeySaved ? "ENCRYPTED ON DEVICE" : "NOT CONFIGURED"}</span></div>
      <div className="panel-foot">Use your GMGN API key from gmgn.ai/ai. This first connection enables official token discovery and trending data only. The key is encrypted with Android Keystore and is never sent to our server. No wallet private key or trade permission is requested.</div>
      <input aria-label="GMGN API key" type="password" autoComplete="off" placeholder={isNativeApp ? "GMGN API key" : "Available in the Android app"} value={gmgnApiKey} onChange={event => setGmgnApiKey(event.target.value)} disabled={!isNativeApp || gmgnKeyBusy} />
      <div className="engine-control-actions">
        <button className="engine-start" onClick={() => void saveGmgnKey()} disabled={!isNativeApp || gmgnKeyBusy || !gmgnApiKey.trim()}>Save GMGN key securely</button>
        <button className="engine-stop" onClick={() => void clearGmgnKey()} disabled={!isNativeApp || gmgnKeyBusy || !gmgnKeySaved}>Clear GMGN key</button>
      </div>
      <small className="engine-control-state">{isNativeApp ? gmgnKeyMessage : "Install the Android app to use device-secure GMGN API storage."}</small>
    </div>
    <div className="agent-runtime-list credential-panel">
      <div className="decision-list-head"><b>BINANCE SPOT TESTNET CREDENTIALS</b><span>{credentialSaved ? "ENCRYPTED ON DEVICE" : "NOT CONNECTED"}</span></div>
      <div className="panel-foot">Enter Testnet-only API credentials. They are encrypted by Android Keystore and are not sent to a server. Do not use production keys; disable withdrawals on the Testnet key.</div>
      <input aria-label="Binance Testnet API key" type="password" autoComplete="off" placeholder={isNativeApp ? "Binance Spot Testnet API key" : "Available in the Android app"} value={testnetApiKey} onChange={event => setTestnetApiKey(event.target.value)} disabled={!isNativeApp || credentialBusy} />
      <input aria-label="Binance Testnet API secret" type="password" autoComplete="off" placeholder="Binance Spot Testnet API secret" value={testnetApiSecret} onChange={event => setTestnetApiSecret(event.target.value)} disabled={!isNativeApp || credentialBusy} />
      <div className="engine-control-actions">
        <button className="engine-start" onClick={() => void saveTestnetCredentials()} disabled={!isNativeApp || credentialBusy || !testnetApiKey.trim() || !testnetApiSecret.trim()}>Save encrypted credentials</button>
        <button className="engine-start" onClick={() => void checkTestnetAccount()} disabled={!isNativeApp || !credentialSaved || accountBusy || credentialBusy}>{accountBusy ? "Checking account…" : "Check Testnet account"}</button>
        <button className="engine-stop" onClick={() => void clearTestnetCredentials()} disabled={!isNativeApp || credentialBusy || !credentialSaved}>Clear credentials</button>
      </div>
      <small className="engine-control-state">{isNativeApp ? credentialMessage : "Install the Android app to use device-secure credential storage."}</small>
      {testnetAccount && <div className="decision-list">
        <div className="decision-list-head"><b>BINANCE SPOT TESTNET ACCOUNT</b><span>{testnetAccount.connected ? "CONNECTED · READ ONLY" : "NOT CONNECTED"}</span></div>
        {testnetAccount.connected ? <>
          <div className="crypto-summary">
            <div><small>ENVIRONMENT</small><b>{testnetAccount.environment || "—"}</b></div>
            <div><small>ACCOUNT TYPE</small><b>{testnetAccount.account_type || "—"}</b></div>
            <div><small>TRADING PERMISSION</small><b>{testnetAccount.can_trade ? "Enabled" : "Disabled"}</b></div>
            <div><small>WITHDRAWAL PERMISSION</small><b>{testnetAccount.can_withdraw ? "Enabled" : "Disabled"}</b></div>
          </div>
          {(testnetAccount.balances || []).length === 0 ? <div className="decision-empty"><div><b>No non-zero balances returned</b><span>The Testnet account responded, but no asset balance is currently available.</span></div></div> :
            (testnetAccount.balances || []).map(balance => <div className="decision-row" key={balance.asset}><b>{balance.asset}</b><span>Free {balance.free}</span><span>Locked {balance.locked}</span></div>)}
        </> : <div className="decision-empty"><div><b>Account check failed</b><span>{testnetAccount.error || "The exchange did not confirm the account."}{testnetAccount.exchange_code ? " (Exchange code " + testnetAccount.exchange_code + ")" : ""}</span></div></div>}
      </div>}
    </div>
    <div className="crypto-summary">
      <div><small>GMGN FEED</small><b>{String(gmgnFeed?.status || "NOT CONFIGURED")}</b></div>
      <div><small>ENGINE</small><b>{engine}</b></div>
      <div><small>MODE</small><b>Paper only</b></div>
      <div><small>ORDER ROUTING</small><b>Disabled</b></div>
      <div><small>FEE CONFIG</small><b>{String(status?.fee_configuration || "Not loaded")}</b></div>
      <div><small>LAST UPDATE</small><b>{lastUpdated || "Not connected"}</b></div>
      <div><small>52-MARKET CROSS-EXCHANGE SCAN</small><b>{String(arbitrageScanner?.status || "Waiting")}</b></div>
      <div><small>MARKETS SCANNED</small><b>{String(arbitrageScanner?.symbols_scanned ?? 0)} / {String(arbitrageUniverse?.target_count ?? 52)}</b></div>
      <div><small>TWO-VENUE COVERAGE</small><b>{String(arbitrageScanner?.symbols_with_two_venues ?? 0)}</b></div>
      <div><small>PAPER OPPORTUNITIES</small><b>{String(arbitrageScanner?.opportunities_count ?? 0)}</b></div>
      <div><small>MARKET UNIVERSE</small><b>{String(arbitrageUniverse?.status || "Waiting")}</b></div>
      <div><small>SCAN TARGET</small><b>{String(status?.poll_interval_seconds ?? "1")}s · batch REST</b></div>
      <div><small>STRATEGY PROFILE</small><b>{String(strategyEngine?.profile || "Intraday")} · {String(strategyEngine?.execution_timeframe || "15m")}/{String(strategyEngine?.context_timeframe || "4h")}</b></div>
    </div>
    <div className="agent-runtime-list">
      <div className="decision-list-head"><b>GMGN TOKEN DISCOVERY</b><span>{String(gmgnFeed?.status || "NOT CONFIGURED")}</span></div>
      <div className="panel-foot">{String(gmgnFeed?.detail || "Configure the official GMGN API key in the Android app to enable this feed.")}</div>
      {gmgnTokens.slice(0, 10).map((token, index) => <div className="decision-row" key={String(token.token_address || index)}>
        <div><b>{String(token.symbol || "—")} · {String(token.name || "Token")}</b><small>{String(token.launchpad || "GMGN Trenches")} · {String(token.chain || "sol")}</small></div>
        <small>{String(token.token_address || "")}</small>
        <span>{token.rug_ratio === undefined ? "Risk score pending" : "Rug ratio " + String(token.rug_ratio)}</span>
      </div>)}
      {gmgnFeed?.trenches_preview ? <pre className="gmgn-preview">{String(gmgnFeed.trenches_preview)}</pre> : null}
      {gmgnFeed?.trending_preview ? <pre className="gmgn-preview">{String(gmgnFeed.trending_preview)}</pre> : null}
      {gmgnFeed?.security_preview ? <pre className="gmgn-preview">{String(gmgnFeed.security_preview)}</pre> : null}
    </div>
    <div className="agent-runtime-list">
      <div className="decision-list-head"><b>GMGN SNIPER · PAPER REVIEW ONLY</b><span>{String(gmgnSniper?.status || "WAITING")}</span></div>
      <div className="panel-foot">{String(gmgnSniper?.detail || "Candidates require current liquidity and complete GMGN security evidence. No orders are enabled.")}</div>
      <div className="crypto-summary">
        <div><small>QUALIFIED CANDIDATES</small><b>{String(gmgnSniper?.candidate_count ?? 0)}</b></div>
        <div><small>BLOCKED TOKENS</small><b>{String(gmgnSniper?.blocked_count ?? 0)}</b></div>
        <div><small>EXECUTION</small><b>DISABLED</b></div>
      </div>
      {gmgnSniperCandidates.map((item, index) => <div className="decision-row" key={String(item.token_address || index)}>
        <div><b>{String(item.symbol || "—")}</b><small>{String(item.chain || "sol")} · Liquidity ${Number(item.liquidity_usd ?? 0).toLocaleString()}</small></div>
        <span>Rug ratio {String(item.rug_ratio ?? "—")}</span>
        <small>{String(item.token_address || "")}</small>
      </div>)}
    </div>
    <div className="agent-runtime-list readiness-panel">
      <div className="decision-list-head"><b>REMAINING INTEGRATION WORK</b><span>{String(readiness?.verified_tasks ?? 0)}/{String(readiness?.total_tasks ?? 9)} verified · {String(readiness?.overall_status ?? "WAITING FOR ENGINE")}</span></div>
      {readinessTasks.map(task => <div className="readiness-row" key={String(task.id)}>
        <div><b>{String(task.title || task.id)}</b><small>{String(task.detail || "")}</small></div>
        <span className={"readiness-state " + String(task.status || "UNKNOWN").toLowerCase()}>{String(task.status || "UNKNOWN").replaceAll("_", " ")}</span>
      </div>)}
      {readinessTasks.length === 0 && <div className="decision-empty"><div><b>Integration checklist unavailable</b><span>Start the phone engine to load the outstanding work and external approval gates.</span></div></div>}
      <div className="panel-foot">The cross-exchange monitor selects up to 52 liquid USDT pairs from Binance 24-hour quote volume and requests one batched REST snapshot per venue. One-second polling is a target, not a guarantee; actual cycles depend on venue response times and rate limits. This checklist separates code work from external approvals and tests. Live-money trading remains locked, even after demo checks pass.</div>
    </div>
    <div className="agent-runtime-list paper-book-panel">
      <div className="decision-list-head"><b>PAPER TRADING ACCOUNT</b><span>{paperTrading ? "CONNECTED TO LOCAL ENGINE" : "WAITING FOR ENGINE"}</span></div>
      <div className="crypto-summary">
        <div><small>STARTING EQUITY</small><b>${String(paperTrading?.starting_equity ?? "20.00")}</b></div>
        <div><small>PAPER EQUITY</small><b>${String(paperTrading?.equity ?? "—")}</b></div>
        <div><small>REALIZED P/L</small><b>${String(paperTrading?.realized_pnl ?? "—")}</b></div>
        <div><small>DAILY LOSS</small><b>{paperTrading ? (Number(paperTrading.daily_loss_pct ?? 0) * 100).toFixed(2) + "%" : "—"}</b></div>
        <div><small>OPEN POSITION</small><b>{paperPosition ? String(paperPosition.symbol) + " " + String(paperPosition.side) : "None"}</b></div>
        <div><small>STRATEGY</small><b>{String(strategyEngine?.status || "Waiting")} · {String(strategyEngine?.score ?? "—")}/{String(strategyEngine?.score_threshold ?? 6)}</b></div>
      </div>
      <div className="panel-foot">Directional strategy: multi-timeframe confluence using EMA50/200 and EMA20/50, MACD, RSI, BOS/CHoCH, liquidity sweeps, order blocks, FVG and Fibonacci zones. Current crypto execution is paper-only; cross-exchange price gaps are not treated as directional entry signals.</div>
      <div className="decision-list-head"><b>RECENT PAPER EVENTS</b><span>{paperTrades.length} records</span></div>
      {paperTrades.length === 0 ? <div className="decision-empty"><div><b>No paper trades yet</b><span>Entries and exits will be recorded here after a validated multi-timeframe confluence signal.</span></div></div> :
        paperTrades.map((trade, index) => <div className="decision-row" key={String(trade.timestamp || index)}>
          <div><b>{String(trade.event || "PAPER EVENT")} · {String(trade.symbol || trade.position && (trade.position as Record<string, unknown>).symbol || "—")}</b>
            <small>{String(trade.exit_reason || trade.reason || trade.signal_reason || "Paper decision")}</small></div>
          <span>{trade.realized_pnl === undefined ? "—" : "P/L " + String(trade.realized_pnl)}</span>
          <small>{String(trade.timestamp || "")}</small>
        </div>)
      }
    </div>
    <div className="agent-runtime-list">
      <div className="decision-list-head"><b>AGENT RUNTIME STATUS</b><span>{Object.keys(agentStates).length}/8 reported</span></div>
      {Object.entries(agentStates).map(([name, agent]) => <div className="agent-runtime-row" key={name}>
        <b>{name}</b><span className={"agent-runtime-state " + String(agent.status || "UNKNOWN").toLowerCase()}>{String(agent.status || "UNKNOWN").replaceAll("_", " ")}</span>
        <small>{String(agent.detail || "")}</small>
      </div>)}
      {Object.keys(agentStates).length === 0 && <div className="decision-empty"><div><b>Agent runtime not connected</b><span>Start the phone engine to retrieve actual agent states.</span></div></div>}
    </div>
    <div className="decision-list">
      <div className="decision-list-head"><b>LIVE TOP-OF-BOOK QUOTES</b><span>{latestQuotes.length} venues</span></div>
      {latestQuotes.length === 0 ? <div className="decision-empty"><Activity size={18}/><div><b>No live quote snapshot yet</b><span>Start the local paper service to fetch current Binance, Bitget and HTX prices.</span></div></div> :
        latestQuotes.map((quote, index) => <div className="decision-row" key={String(quote.exchange || index)}><div><b>{String(quote.symbol || "Symbol")} · {String(quote.exchange || "Exchange")}</b><small>Bid size {String(quote.bid_size ?? "—")} · Ask size {String(quote.ask_size ?? "—")}</small></div><span>Bid {String(quote.bid ?? "—")}</span><span>Ask {String(quote.ask ?? "—")}</span></div>)}
      <div className="decision-list-head"><b>TOP CROSS-EXCHANGE OPPORTUNITIES</b><span>{scannerOpportunities.length} candidates · paper only</span></div>
      {scannerOpportunities.length === 0
        ? <div className="decision-empty"><div><b>No qualifying price gaps</b><span>Only fresh quotes with verified fees, depth and net edge are shown here.</span></div></div>
        : scannerOpportunities.slice(0, 10).map((item, index) => <div className="decision-row" key={String(item.symbol || index) + ":" + String(item.buy_exchange || "")}>
            <div><b>{String(item.symbol || "—")}</b><small>Buy {String(item.buy_exchange || "—")} → Sell {String(item.sell_exchange || "—")}</small></div>
            <span>Net {Number(item.net_edge_bps ?? 0).toFixed(1)} bps</span>
            <small>Top-of-book cap ${Number(item.max_notional_at_top_of_book ?? 0).toFixed(2)}</small>
          </div>)}
      <div className="decision-list-head"><b>RECENT SCANNER DECISIONS</b><span>{decisions.length} records</span></div>
      {connection !== "connected" ? <div className="decision-empty"><Activity size={18}/><div><b>Waiting for the local paper API</b><span>When the paper-monitor service is running on this phone, its status and decisions will appear here.</span></div></div> :
        decisions.length === 0 ? <div className="decision-empty"><Activity size={18}/><div><b>No decision records yet</b><span>The API is connected, but the monitor has not written any decisions.</span></div></div> :
        decisions.map((item, index) => <div className="decision-row" key={String(item.recorded_at || index)}><div><b>{String(item.symbol || "Unknown symbol")}</b><small>{String(item.reason || "No reason supplied")}</small>{item.error ? <small className="feed-error">{String(item.error_type || "Feed error")}: {String(item.error)}</small> : null}</div><span>{String(item.status || "UNKNOWN")}</span><small>{String(item.recorded_at || "")}</small></div>)
      }
    </div>
    <div className="panel-foot">Read-only local connection. Paper mode only; no order controls are available.</div>
  </section>;
}
