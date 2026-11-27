const AUTHORIZE_URL = "https://id.ctrader.com/my/settings/openapi/grantingaccess/";
const CALLBACK_PATH = "/api/ctrader/oauth/callback";

function isBase64UrlState(value) {
  return typeof value === "string" && /^[A-Za-z0-9_-]{40,60}$/.test(value);
}

/** Build a cTrader authorization URL only for this Worker origin's callback. */
export function buildCTraderAuthorizationUrl({ clientId, redirectUri, requestOrigin, accessKind, state }) {
  if (typeof clientId !== "string" || !clientId.trim() || clientId.length > 256) {
    throw new Error("A valid cTrader client ID is required.");
  }
  if (accessKind !== "view-only" && accessKind !== "trading") {
    throw new Error("Unsupported cTrader access kind.");
  }
  if (!isBase64UrlState(state)) throw new Error("A high-entropy OAuth state is required.");

  let redirect;
  let origin;
  try {
    redirect = new URL(redirectUri);
    origin = new URL(requestOrigin);
  } catch {
    throw new Error("The cTrader callback URL or request origin is invalid.");
  }
  if (redirect.protocol !== "https:" || origin.protocol !== "https:" ||
      redirect.origin !== origin.origin || redirect.pathname !== CALLBACK_PATH ||
      redirect.search || redirect.hash || redirect.username || redirect.password) {
    throw new Error("The cTrader callback URL must be the HTTPS callback on this Worker origin.");
  }

  const url = new URL(AUTHORIZE_URL);
  url.search = new URLSearchParams({
    client_id: clientId.trim(),
    redirect_uri: redirect.toString(),
    scope: accessKind === "trading" ? "trading" : "accounts",
    product: "web",
    state,
  }).toString();
  return url.toString();
}

/** Validate the token endpoint response before any token can be encrypted or saved. */
export function validateCTraderTokenResponse(value) {
  if (!value || typeof value !== "object" || Array.isArray(value) ||
      value.errorCode ||
      typeof value.accessToken !== "string" || !value.accessToken ||
      typeof value.refreshToken !== "string" || !value.refreshToken ||
      typeof value.tokenType !== "string" || !value.tokenType ||
      !Number.isFinite(Number(value.expiresIn)) || Number(value.expiresIn) <= 0) {
    throw new Error("cTrader returned an incomplete authorization token response.");
  }
  return {
    ...value,
    accessToken: value.accessToken,
    refreshToken: value.refreshToken,
    tokenType: value.tokenType,
    expiresIn: Number(value.expiresIn),
  };
}
