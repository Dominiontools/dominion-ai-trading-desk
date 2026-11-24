import type { CapacitorConfig } from "@capacitor/cli";

const config: CapacitorConfig = {
  appId: "com.dominion.aitradingdesk",
  appName: "Dominion AI Trading Desk",
  webDir: "dist",
  bundledWebRuntime: false,
  android: {
    backgroundColor: "#080d18",
    allowMixedContent: true
  }
};

export default config;
