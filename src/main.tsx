import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import CTraderConnection from "./CTraderConnection";
import "./styles.css";

if (import.meta.env.PROD && "serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {
      // The dashboard remains usable if offline support is unavailable.
    });
  });
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode><App /><CTraderConnection /></React.StrictMode>
);
