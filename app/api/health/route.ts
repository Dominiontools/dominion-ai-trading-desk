export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  return Response.json({
    ok: true,
    service: "dominion-ai-trading-desk",
    runtime: "nextjs-cloudflare",
    stage: "backend-migration",
    trading_enabled: false,
    live_trading_enabled: false
  }, {
    headers: {
      "cache-control": "no-store",
      "x-content-type-options": "nosniff"
    }
  });
}
