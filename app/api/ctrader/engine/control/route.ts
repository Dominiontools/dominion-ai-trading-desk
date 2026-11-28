export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST() {
  // Configuration writes stay disabled until Cloudflare Access identity
  // verification and D1 nonce replay protection are wired into this route.
  return Response.json({
    ok: false,
    error: "CTRADER_CONTROL_AUTH_NOT_CONFIGURED",
    trading_enabled: false,
    live_trading_enabled: false
  }, {
    status: 503,
    headers: { "cache-control": "no-store", "x-content-type-options": "nosniff" }
  });
}
