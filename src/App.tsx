import { useMemo, useState, type ReactNode } from "react";
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
  { symbol: "XAUUSD", name: "Gold / US Dollar", price: "2,684.32", change: "+0.42%", group: "Forex & Gold", tone: "up" },
  { symbol: "EURUSD", name: "Euro / US Dollar", price: "1.15482", change: "+0.11%", group: "Forex & Gold", tone: "up" },
  { symbol: "GBPUSD", name: "Pound / US Dollar", price: "1.31206", change: "-0.08%", group: "Forex & Gold", tone: "down" },
  { symbol: "BTCUSDT", name: "Bitcoin / Tether", price: "87,420.50", change: "+1.26%", group: "Crypto", tone: "up" },
  { symbol: "ETHUSDT", name: "Ethereum / Tether", price: "2,914.80", change: "-0.34%", group: "Crypto", tone: "down" }
];

export default function App() {
  const [market, setMarket] = useState<Market>("All markets");
  const [paused, setPaused] = useState(false);
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
        <div className="top-actions"><span className="demo-pill"><span/> DEMO MODE ONLY</span><button className={paused ? "resume" : "pause"} onClick={() => setPaused(!paused)}>{paused ? "Resume scanner" : "Pause scanner"}</button></div>
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
        <div className="panel-foot">Illustrative interface values only — not live market prices.</div>
      </div>

      <section className="crypto-monitor">
        <div className="section-head"><div><div className="eyebrow">CRYPTO / CROSS-EXCHANGE</div><h2>Paper arbitrage monitor</h2></div><span className="monitor-state"><i/> ENGINE NOT CONNECTED</span></div>
        <div className="crypto-venues">
          {[
            ["BINANCE", "Public ticker adapter", "Waiting for backend"],
            ["BITGET", "Public ticker adapter", "Waiting for backend"],
            ["HTX", "Public ticker adapter", "Waiting for backend"]
          ].map(([name, source, state]) => <div className="venue-card" key={name}><div><b>{name}</b><span className="venue-dot"/></div><small>{source}</small><p>{state}</p></div>)}
        </div>
        <div className="crypto-summary">
          <div><small>MONITOR MODE</small><b>Paper only</b></div>
          <div><small>POLL INTERVAL</small><b>5 seconds (configured)</b></div>
          <div><small>FEE CONFIGURATION</small><b className="blocked-text">Not verified · scanning blocked</b></div>
          <div><small>ORDER ROUTING</small><b>Disabled</b></div>
        </div>
        <div className="decision-empty"><Activity size={18}/><div><b>No decision records yet</b><span>When the monitor backend is connected and run, accepted and rejected scan decisions will appear here.</span></div></div>
        <div className="panel-foot">Dashboard preview only. It does not fetch prices or start the Python monitor. No exchange credentials or order permissions are connected.</div>
      </section>

      <div className="section-head agent-heading"><div><div className="eyebrow">AUTONOMOUS WORKFORCE</div><h2>Eight-agent system</h2></div><span className="muted">{paused ? "Scanner paused" : "System staged"}</span></div>
      <div className="agent-grid">{agents.map(([name, role, status, Icon], i) => <div className="agent-card" key={name}><div className="agent-top"><div className="agent-icon"><Icon size={18}/></div><span className={i === 1 || i === 7 ? "agent-state ready" : "agent-state"}>{i === 1 || i === 7 ? "READY" : "STAGED"}</span></div><b>{name}</b><small>{role}</small><p>{name === "SCANNER" && paused ? "Scanner paused by operator" : status}</p></div>)}</div>
      <footer>DOMINION AI TRADING DESK <span>FOUNDATION BUILD · DEMO ONLY · v0.1.0</span></footer>
    </section>
  </main>;
}

function Metric({ icon, label, value, note, positive = false }: { icon: ReactNode; label: string; value: string; note: string; positive?: boolean }) {
  return <div className="metric"><div className="metric-icon">{icon}</div><span>{label}</span><strong className={positive ? "positive" : ""}>{value}</strong><small>{note}</small></div>;
}
