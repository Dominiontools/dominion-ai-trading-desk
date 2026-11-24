import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { Activity, ArrowDownRight, ArrowUpRight, Bot, CircleDollarSign, Gauge, LockKeyhole, Radar, ShieldCheck, Wallet, Waves } from "lucide-react";

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
  { symbol: "ETHUSDT", name: "Ethereum / Tether", price: "Not connected", change: "—", group: "Crypto", tone: "down" }
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
        <div className="top-actions"><span className="demo-pill"><span/> PAPER MODE ONLY</span><span className="muted">Engine runs separately on this phone</span></div>
      </header>

      <div className="notice"><LockKeyhole size={18}/><div><b>Protected development environment</b><span>Live orders are disabled. All future order routing must pass the Risk Agent and remain in demo/paper mode until separately approved.</span></div></div>

      <div className="metric-grid">
        <Metric icon={<CircleDollarSign/>} label="Account equity" value="$10,000.00" note="Illustrative demo balance"/>
        <Metric icon={<Activity/>} label="Open positions" value="0" note="No simulated positions"/>
        <Metric icon={<ShieldCheck/>} label="Risk status" value="Protected" note="Pre-trade checks staged" positive/>
        <Metric icon={<Gauge/>} label="Today's P/L" value="$0.00" note="No trades executed"/>
      </div>

      <div className="section-head"><div><div className="eyebrow">MARKET MONITOR</div><h2>Watchlist</h2></div><select value={market} onChange={e => setMarket(e.target.value as Market)}><option>All markets</option><option>Forex & Gold</option><option>Crypto</option></select></div>
      <div className="panel watch-panel">
        <div className="table-head"><span>INSTRUMENT</span><span>LAST PRICE</span><span>24H CHANGE</span><span>FEED STATUS</span></div>
        {filtered.map(item => <div className="watch-row" key={item.symbol}><div className="instrument"><b>{item.symbol}</b><small>{item.name}</small></div><b className="price">{item.price}</b><span className={item.tone === "up" ? "positive" : "negative"}>{item.tone === "up" ? <ArrowUpRight size={14}/> : <ArrowDownRight size={14}/>} {item.change}</span><span className="feed-pending">Awaiting data</span></div>)}
        <div className="panel-foot">No fabricated prices. Forex and gold will show live data after cTrader is connected; crypto snapshots appear in the paper monitor below.</div>
      </div>

      <CryptoMonitorPanel />

      <div className="section-head agent-heading"><div><div className="eyebrow">AUTONOMOUS WORKFORCE</div><h2>Eight-agent system</h2></div><span className="muted">"System staged — agents not yet fully connected"</span></div>
      <div className="agent-grid">{agents.map(([name, role, status, Icon], i) => <div className="agent-card" key={name}><div className="agent-top"><div className="agent-icon"><Icon size={18}/></div><span className="agent-state"}>STAGED</span></div><b>{name}</b><small>{role}</small><p>{status}</p></div>)}</div>
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

  const refresh = useCallback(async () => {
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
      const quoteRows = Array.isArray(items[0]?.quotes) ? items[0].quotes.filter((item): item is Record<string, unknown> => !!item && typeof item === "object") : [];
      setLatestQuotes(quoteRows);
      setConnection("connected");
      setLastUpdated(new Date().toLocaleTimeString());
    } catch {
      setConnection("offline");
      setStatus(null);
      setDecisions([]);\n      setLatestQuotes([]);
    } finally {
      window.clearTimeout(timeout);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 5000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const engine = typeof status?.engine === "string" ? status.engine : typeof status?.status === "string" ? status.status : "Status unavailable";
  return <section className="crypto-monitor">
    <div className="section-head"><div><div className="eyebrow">CRYPTO / CROSS-EXCHANGE</div><h2>Paper arbitrage monitor</h2></div><span className={"monitor-state " + connection}><i/> {connection === "connected" ? "LOCAL API CONNECTED" : connection === "checking" ? "CHECKING LOCAL API" : "LOCAL API OFFLINE"}</span></div>
    <div className="crypto-summary">
      <div><small>ENGINE</small><b>{engine}</b></div>
      <div><small>MODE</small><b>Paper only</b></div>
      <div><small>ORDER ROUTING</small><b>Disabled</b></div>
      <div><small>LAST UPDATE</small><b>{lastUpdated || "Not connected"}</b></div>
    </div>
    <div className="decision-list">
      <div className="decision-list-head"><b>LIVE TOP-OF-BOOK QUOTES</b><span>{latestQuotes.length} venues</span></div>
      {latestQuotes.length === 0 ? <div className="decision-empty"><Activity size={18}/><div><b>No live quote snapshot yet</b><span>Start the local paper service to fetch current Binance, Bitget and HTX prices.</span></div></div> :
        latestQuotes.map((quote, index) => <div className="decision-row" key={String(quote.exchange || index)}><div><b>{String(quote.exchange || "Exchange")}</b><small>Bid size {String(quote.bid_size ?? "—")} · Ask size {String(quote.ask_size ?? "—")}</small></div><span>Bid {String(quote.bid ?? "—")}</span><span>Ask {String(quote.ask ?? "—")}</span></div>)}
      <div className="decision-list-head"><b>RECENT SCANNER DECISIONS</b><span>{decisions.length} records</span></div>
      {connection !== "connected" ? <div className="decision-empty"><Activity size={18}/><div><b>Waiting for the local paper API</b><span>When the paper-monitor service is running on this phone, its status and decisions will appear here.</span></div></div> :
        decisions.length === 0 ? <div className="decision-empty"><Activity size={18}/><div><b>No decision records yet</b><span>The API is connected, but the monitor has not written any decisions.</span></div></div> :
        decisions.map((item, index) => <div className="decision-row" key={String(item.recorded_at || index)}><div><b>{String(item.symbol || "Unknown symbol")}</b><small>{String(item.reason || "No reason supplied")}</small></div><span>{String(item.status || "UNKNOWN")}</span><small>{String(item.recorded_at || "")}</small></div>)
      }
    </div>
    <div className="panel-foot">Read-only local connection. Paper mode only; no order controls are available.</div>
  </section>;
}
