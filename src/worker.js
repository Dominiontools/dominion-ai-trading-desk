const json = (body, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      "x-content-type-options": "nosniff"
    }
  });

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === "/api/health") {
      if (request.method !== "GET") {
        return json({ ok: false, error: "method_not_allowed" }, 405);
      }
      return json({
        ok: true,
        service: "dominion-ai-trading-desk",
        runtime: "cloudflare-workers",
        stage: "backend-migration-scaffold",
        trading_enabled: false,
        live_trading_enabled: false
      });
    }

    if (url.pathname.startsWith("/api/ctrader/")) {
      return json({
        ok: false,
        service: "ctrader",
        status: "not_migrated",
        trading_enabled: false,
        message: "The cTrader demo service is not connected to this Worker yet."
      }, 503);
    }

    if (url.pathname.startsWith("/api/crypto/")) {
      return json({
        ok: false,
        service: "crypto",
        status: "phone_engine_required",
        trading_enabled: false,
        message: "Crypto market monitoring still requires the Android phone engine. No exchange orders are routed by this Worker."
      }, 503);
    }

    if (url.pathname.startsWith("/api/")) {
      return json({ ok: false, error: "not_found" }, 404);
    }

    return env.ASSETS.fetch(request);
  }
};
