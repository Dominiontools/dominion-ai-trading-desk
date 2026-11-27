/** Verify OAuth access against the cTrader demo Open API and authenticate one demo account. */
export async function verifyCTraderDemoAccount({ accessToken, clientId, clientSecret, expectedScope, timeoutMs = 18_000 }) {
  if (typeof accessToken !== "string" || !accessToken ||
      typeof clientId !== "string" || !clientId ||
      typeof clientSecret !== "string" || !clientSecret ||
      ![0, 1].includes(expectedScope)) {
    throw new Error("Invalid cTrader demo verification input.");
  }
  if (typeof WebSocket !== "function") throw new Error("WebSocket support is unavailable.");
  const socket = new WebSocket("wss://demo.ctraderapi.com:5036");
  return await new Promise((resolve, reject) => {
    let stage = "connecting";
    let settled = false;
    let demoAccounts = [];
    let permissionScope = null;
    let authorizedAccountId = null;
    const finish = (error, result) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      try { socket.close(); } catch { /* already closed */ }
      if (error) reject(error);
      else resolve(result);
    };
    const send = (payloadType, payload) => {
      socket.send(JSON.stringify({
        clientMsgId: crypto.randomUUID(),
        payloadType,
        payload
      }));
    };
    const timeout = setTimeout(() => finish(new Error("cTrader demo account verification timed out.")), timeoutMs);
    socket.addEventListener("open", () => {
      stage = "app-auth";
      send(2100, { clientId, clientSecret });
    });
    socket.addEventListener("message", (event) => {
      try {
        const message = JSON.parse(String(event.data));
        if (message.payloadType === 2142) {
          finish(new Error("cTrader rejected demo Open API authorization."));
          return;
        }
        if (stage === "app-auth" && message.payloadType === 2101) {
          stage = "account-list";
          send(2149, { accessToken });
          return;
        }
        if (stage === "account-list" && message.payloadType === 2150) {
          const payload = message.payload ?? {};
          permissionScope = Number(payload.permissionScope);
          if (permissionScope !== expectedScope) {
            finish(new Error("cTrader permission scope does not match the requested access."));
            return;
          }
          const listed = Array.isArray(payload.ctidTraderAccount) ? payload.ctidTraderAccount : [];
          demoAccounts = listed.filter((account) => account?.isLive === false);
          if (!demoAccounts.length) {
            finish(new Error("No cTrader demo account is available for this authorization."));
            return;
          }
          const accountId = Number(demoAccounts[0].ctidTraderAccountId);
          if (!Number.isSafeInteger(accountId) || accountId <= 0) {
            finish(new Error("cTrader returned an invalid demo account ID."));
            return;
          }
          stage = "account-auth";
          send(2102, { ctidTraderAccountId: accountId, accessToken });
          return;
        }
        if (stage === "account-auth" && message.payloadType === 2103) {
          const returnedId = String(message.payload?.ctidTraderAccountId ?? "");
          const expectedId = String(demoAccounts[0].ctidTraderAccountId);
          if (!returnedId || returnedId !== expectedId) {
            finish(new Error("cTrader authenticated a different account than the selected demo account."));
            return;
          }
          authorizedAccountId = returnedId;
          finish(null, {
            permissionScope,
            demoAccountCount: demoAccounts.length,
            authorizedAccountId
          });
        }
      } catch {
        finish(new Error("cTrader returned an unreadable demo account response."));
      }
    });
    socket.addEventListener("error", () => finish(new Error("Could not connect to the cTrader demo Open API.")));
    socket.addEventListener("close", () => {
      if (!settled) finish(new Error("cTrader closed the demo connection before verification completed."));
    });
  });
}
