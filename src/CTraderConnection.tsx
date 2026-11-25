import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

type ConnectionStatus = {
  connected: boolean;
  broker?: string;
  environment?: string | null;
  access?: string | null;
  demoAccountCount?: number;
  verifiedAt?: string | null;
};

const STATUS_URL = "https://dominion-ai-trading-desk-p7cp.netlify.app/.netlify/functions/ctrader-status";
const CONNECT_URL = "https://dominion-ai-trading-desk-p7cp.netlify.app/.netlify/functions/ctrader-callback";

export default function CTraderConnection() {
  const [target, setTarget] = useState<HTMLElement | null>(null);
  const [status, setStatus] = useState<ConnectionStatus | null>(null);
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    setTarget(document.querySelector<HTMLElement>(".top-actions"));
  }, []);

  useEffect(() => {
    let active = true;
    const refresh = async () => {
      try {
        const response = await fetch(STATUS_URL, { method: "GET", cache: "no-store", credentials: "omit" });
        if (!response.ok) throw new Error("Status endpoint unavailable");
        const data = await response.json() as ConnectionStatus;
        if (active) setStatus(data);
      } catch {
        if (active) setStatus(null);
      } finally {
        if (active) setChecking(false);
      }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 30000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  if (!target) return null;

  const connected = status?.connected === true;
  const label = connected
    ? `PEPPERSTONE DEMO · VIEW ONLY · ${status.demoAccountCount ?? 0} ACCOUNT${status.demoAccountCount === 1 ? "" : "S"}`
    : checking ? "CHECKING CTRADER" : status ? "CTRADER NOT CONNECTED" : "CTRADER STATUS UNAVAILABLE";

  return createPortal(
    <div className={`ctrader-connection ${connected ? "is-connected" : "is-pending"}`} role="status" aria-live="polite">
      <span className="ctrader-dot" />
      <span className="ctrader-label">{label}</span>
      <a href={CONNECT_URL} className="ctrader-reconnect" rel="noreferrer">
        {connected ? "Reconnect" : "Connect"}
      </a>
    </div>,
    target
  );
}
