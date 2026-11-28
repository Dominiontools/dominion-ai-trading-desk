import type { Metadata, Viewport } from "next";
import "../src/styles.css";

export const metadata: Metadata = {
  title: "Dominion AI Trading Desk",
  description: "Demo-first Forex, Gold and Crypto trading control center.",
  applicationName: "Dominion AI Trading Desk",
  manifest: "/manifest.webmanifest",
  icons: { icon: "/icons/dominion-mark.svg" }
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: "#080d18"
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
