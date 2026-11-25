import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

type ConnectionStatus = {
  connected: boolean;
  broker?: string;
  environment?: string | null;
  access?: "view-only" | "trading" | null;
  demoAccountCount?: number;
  verifiedAt?: string | null;
};

const STATUS_URL = "https://dominion-ai-trading-desk-p7cp.netlify.app/.netlify/functions/ctrader-status";
const CONNECT_URL = "https://dominion-ai-trading-desk-p7cp.netlify.app/.netlify/functions/ctrader-callback";
const TRADING_STATUS_URL = `${STATUS_URL}?mode=trading`;
const TRADING_CONNECT_URL = `${CONNECT_URL}?mode=trading`;

export default function CTraderConnection() {
  const [target, setTarget] = useState<HTMLElement | null>(null);
  const [status, setStatus] = useState<ConnectionStatus | null>(null);
  const [tradingStatus, setTradingStatus] = useState<ConnectionStatus | null>(null);
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    setTarget(document.querySelector<HTMLElement>(".top-actions"));
  }, []);

  useEffect(() => {
    let active = true;
    const refresh = async () => {
      const readStatus = async (url: string): Promise<ConnectionStatus | null> => {
        try {
          const response = await fetch(url, {
            method: "GET",
            cache: "no-store",
            credentials: "omit",
          });
          if (!response.ok) return null;
          return await response.json() as ConnectionStatus;
        } catch {
          return null;
        }
      };
      const [viewOnly, trading] = await Promise.all([
        readStatus(STATUS_URL),
        readStatus(TRADING_STATUS_URL),
      ]);
      if (active) {
        setStatus(viewOnly);
        setTradingStatus(trading);
        setChecking(false);
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
  const tradingConnected = tradingStatus?.connected === true;
  const accountCount = tradingConnected
    ? tradingStatus?.demoAccountCount ?? 0
    : status?.demoAccountCount ?? 0;
  const label = connected || tradingConnected
    ? `PEPPERSTONE DEMO · ${tradingConnected ? "TRADING ACCESS" : "VIEW ONLY"} · ${accountCount} ACCOUNT${accountCount === 1 ? "" : "S"}`
    : checking ? "CHECKING CTRADER" : "CTRADER NOT CONNECTED";

  return createPortal(
    <div className={`ctrader-connection ${connected || tradingConnected ? "is-connected" : "is-pending"}`} role="status" aria-live="polite">
      <span className="ctrader-dot" />
      <span className="ctrader-label">{label}</span>
      <a href={CONNECT_URL} className="ctrader-reconnect" rel="noreferrer">
        {connected ? "View access" : "Connect"}
      </a>
      <a
        href={TRADING_CONNECT_URL}
        className="ctrader-reconnect"
        rel="noreferrer"
        aria-label="Authorize cTrader demo trading permission"
      >
        {tradingConnected ? "Reauthorize demo trading" : "Authorize demo trading"}
      </a>
    </div>,
    target
  );
}
