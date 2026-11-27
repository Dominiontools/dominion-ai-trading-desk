const encoder = new TextEncoder();

function fromHex(value) {
  if (typeof value !== "string" || !/^[0-9a-f]{64}$/i.test(value)) return null;
  const bytes = new Uint8Array(32);
  for (let i = 0; i < bytes.length; i += 1) {
    bytes[i] = Number.parseInt(value.slice(i * 2, i * 2 + 2), 16);
  }
  return bytes;
}

/**
 * Verifies the legacy Dominion control HMAC format using Worker Web Crypto.
 * It performs no persistence; callers must consume the nonce in D1 after verification.
 */
export async function verifyCTraderControlSignature({
  secret,
  timestampText,
  nonce,
  signature,
  rawBody,
  nowMs = Date.now(),
}) {
  if (typeof secret !== "string" || secret.length < 32 ||
      typeof timestampText !== "string" || !/^\d{10,13}$/.test(timestampText) ||
      typeof nonce !== "string" || !/^[0-9a-f-]{36}$/i.test(nonce) ||
      typeof rawBody !== "string" || rawBody.length > 16_384 ||
      !Number.isSafeInteger(nowMs)) return false;

  const timestamp = Number(timestampText);
  if (!Number.isSafeInteger(timestamp) || Math.abs(nowMs - timestamp) > 60_000) return false;
  const supplied = fromHex(signature);
  if (!supplied) return false;

  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["verify"],
  );
  const message = encoder.encode(`${timestampText}.${nonce}.${rawBody}`);
  return crypto.subtle.verify("HMAC", key, supplied, message);
}
