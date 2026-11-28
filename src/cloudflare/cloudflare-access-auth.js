const encoder = new TextEncoder();

function decodeBase64Url(value) {
  if (typeof value !== "string" || !/^[A-Za-z0-9_-]+$/.test(value)) return null;
  try {
    const base64 = value.replace(/-/g, "+").replace(/_/g, "/");
    const padded = base64 + "=".repeat((4 - base64.length % 4) % 4);
    const binary = atob(padded);
    return Uint8Array.from(binary, (character) => character.charCodeAt(0));
  } catch {
    return null;
  }
}

function decodeJsonPart(value) {
  const bytes = decodeBase64Url(value);
  if (!bytes) return null;
  try {
    return JSON.parse(new TextDecoder().decode(bytes));
  } catch {
    return null;
  }
}

function readAccessToken(request) {
  const headerToken = request.headers.get("cf-access-jwt-assertion");
  if (headerToken) return headerToken.trim();
  const cookie = request.headers.get("cookie") ?? "";
  for (const part of cookie.split(";")) {
    const separator = part.indexOf("=");
    if (separator >= 0 && part.slice(0, separator).trim() === "CF_Authorization") {
      return part.slice(separator + 1).trim();
    }
  }
  return null;
}

/**
 * Validate a Cloudflare Access JWT cryptographically and bind it to one
 * configured audience and one explicitly allowed operator email.
 */
export async function verifyCloudflareAccessRequest({
  request,
  issuer,
  audience,
  allowedEmail,
  nowMs = Date.now(),
  fetchImpl = fetch
}) {
  if (!request || typeof issuer !== "string" || typeof audience !== "string" ||
      typeof allowedEmail !== "string" || !allowedEmail.includes("@") ||
      !Number.isSafeInteger(nowMs)) return { ok: false, error: "ACCESS_AUTH_NOT_CONFIGURED" };

  let issuerUrl;
  try {
    issuerUrl = new URL(issuer);
  } catch {
    return { ok: false, error: "ACCESS_AUTH_NOT_CONFIGURED" };
  }
  if (issuerUrl.protocol !== "https:" || issuerUrl.pathname !== "/" ||
      issuerUrl.search || issuerUrl.hash || issuerUrl.username || issuerUrl.password) {
    return { ok: false, error: "ACCESS_AUTH_NOT_CONFIGURED" };
  }
  const normalizedIssuer = issuerUrl.origin;
  const token = readAccessToken(request);
  if (!token || token.length > 16_384) return { ok: false, error: "ACCESS_AUTH_REQUIRED" };

  const parts = token.split(".");
  if (parts.length !== 3) return { ok: false, error: "ACCESS_TOKEN_INVALID" };
  const header = decodeJsonPart(parts[0]);
  const claims = decodeJsonPart(parts[1]);
  const signature = decodeBase64Url(parts[2]);
  if (!header || !claims || !signature || header.alg !== "RS256" ||
      typeof header.kid !== "string" || header.kid.length > 256) {
    return { ok: false, error: "ACCESS_TOKEN_INVALID" };
  }

  const nowSeconds = Math.floor(nowMs / 1000);
  if (claims.iss !== normalizedIssuer ||
      !(Array.isArray(claims.aud) ? claims.aud : [claims.aud]).includes(audience) ||
      !Number.isFinite(claims.exp) || claims.exp <= nowSeconds ||
      (claims.nbf != null && (!Number.isFinite(claims.nbf) || claims.nbf > nowSeconds + 30)) ||
      (claims.iat != null && (!Number.isFinite(claims.iat) || claims.iat > nowSeconds + 30)) ||
      typeof claims.email !== "string" ||
      claims.email.toLowerCase() !== allowedEmail.trim().toLowerCase()) {
    return { ok: false, error: "ACCESS_TOKEN_CLAIMS_REJECTED" };
  }

  let jwksResponse;
  try {
    jwksResponse = await fetchImpl(`${normalizedIssuer}/cdn-cgi/access/certs`, {
      headers: { accept: "application/json" },
      signal: AbortSignal.timeout(5000)
    });
  } catch {
    return { ok: false, error: "ACCESS_KEYS_UNAVAILABLE" };
  }
  if (!jwksResponse.ok) return { ok: false, error: "ACCESS_KEYS_UNAVAILABLE" };
  let jwks;
  try {
    jwks = await jwksResponse.json();
  } catch {
    return { ok: false, error: "ACCESS_KEYS_INVALID" };
  }
  const jwk = Array.isArray(jwks?.keys)
    ? jwks.keys.find((key) => key.kid === header.kid && key.kty === "RSA" && key.use === "sig")
    : null;
  if (!jwk) return { ok: false, error: "ACCESS_SIGNING_KEY_NOT_FOUND" };

  try {
    const key = await crypto.subtle.importKey(
      "jwk", jwk, { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["verify"]
    );
    const valid = await crypto.subtle.verify(
      { name: "RSASSA-PKCS1-v1_5" },
      key,
      signature,
      encoder.encode(`${parts[0]}.${parts[1]}`)
    );
    if (!valid) return { ok: false, error: "ACCESS_SIGNATURE_INVALID" };
  } catch {
    return { ok: false, error: "ACCESS_SIGNATURE_INVALID" };
  }

  return { ok: true, email: claims.email };
}
