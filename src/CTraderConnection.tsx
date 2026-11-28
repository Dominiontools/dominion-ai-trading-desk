"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

type ConnectionStatus = {
  connected: boolean;
  broker?: string;
  environment?: string | null;
  access?: "view-only" | "trading" | "none" | null;
  demoAccountCount?: number;
  verifiedAt?: string | null;
};

type StatusResponse = ConnectionStatus;

const STATUS_URL = "/api/ctrader/status";
const CONNECT_URL = "/api/ctrader/oauth/start?mode=view-only";
const TRADING_CONNECT_URL = "/api/ctrader/oauth/start?mode=trading";

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
        const response = await fetch(STATUS_URL, {
          method: "GET",
          cache: "no-store",
          credentials: "same-origin"
        });
        if (!response.ok) throw new Error("cTrader status unavailable");
        const data = await response.json() as StatusResponse;
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
  const tradingConnected = connected && status?.access === "trading";
  const accountCount = status?.demoAccountCount ?? 0;
  const label = connected
    ? `CTRADER DEMO · ${tradingConnected ? "TRADING ACCESS" : "VIEW ONLY"} · ${accountCount} ACCOUNT${accountCount === 1 ? "" : "S"}`
    : checking ? "CHECKING CTRADER" : "CTRADER NOT CONNECTED";

  return createPortal(
    <div className={`ctrader-connection ${connected ? "is-connected" : "is-pending"}`} role="status" aria-live="polite">
      <span className="ctrader-dot" />
      <span className="ctrader-label">{label}</span>
      <a href={CONNECT_URL} className="ctrader-reconnect" rel="noreferrer">
        {connected && !tradingConnected ? "View access" : "Connect"}
      </a>
      <a href={TRADING_CONNECT_URL} className="ctrader-reconnect" rel="noreferrer" aria-label="Authorize cTrader demo trading permission">
        {tradingConnected ? "Reauthorize demo trading" : "Authorize demo trading"}
      </a>
    </div>,
    target
  );
}
