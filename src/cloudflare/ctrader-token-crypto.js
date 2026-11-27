const encoder = new TextEncoder();
const decoder = new TextDecoder();

function toBase64(bytes) {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

function fromBase64(value) {
  if (typeof value !== "string" || value.length === 0 ||
      !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(value)) {
    throw new Error("Invalid base64 data in cTrader token record.");
  }
  const binary = atob(value);
  const bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0));
  if (toBase64(bytes) !== value) {
    throw new Error("Non-canonical base64 data in cTrader token record.");
  }
  return bytes;
}

function decodeKey(keyText) {
  const key = fromBase64(keyText);
  if (key.byteLength !== 32) {
    throw new Error("CTRADER_TOKEN_ENCRYPTION_KEY must be a base64-encoded 32-byte key.");
  }
  return key;
}

/**
 * AES-256-GCM token-record encryption compatible with the legacy record shape.
 * This helper deliberately does not read environment variables or persist data.
 */
export async function encryptCTraderTokenRecord(payload, keyText, now = new Date()) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    throw new Error("cTrader token payload must be a JSON object.");
  }
  const keyBytes = decodeKey(keyText);
  const key = await crypto.subtle.importKey("raw", keyBytes, "AES-GCM", false, ["encrypt"]);
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const clear = encoder.encode(JSON.stringify(payload));
  const encrypted = new Uint8Array(await crypto.subtle.encrypt(
    { name: "AES-GCM", iv, tagLength: 128 },
    key,
    clear,
  ));
  const ciphertext = encrypted.slice(0, -16);
  const tag = encrypted.slice(-16);
  return {
    version: 1,
    algorithm: "aes-256-gcm",
    iv: toBase64(iv),
    tag: toBase64(tag),
    ciphertext: toBase64(ciphertext),
    savedAt: now.toISOString(),
  };
}

/** Decrypts only the known AES-256-GCM legacy record format. */
export async function decryptCTraderTokenRecord(record, keyText) {
  if (!record || record.algorithm !== "aes-256-gcm" || record.version !== 1 ||
      typeof record.iv !== "string" || typeof record.tag !== "string" ||
      typeof record.ciphertext !== "string") {
    throw new Error("Stored cTrader token record has an unsupported format.");
  }
  const key = await crypto.subtle.importKey("raw", decodeKey(keyText), "AES-GCM", false, ["decrypt"]);
  const iv = fromBase64(record.iv);
  const ciphertext = fromBase64(record.ciphertext);
  const tag = fromBase64(record.tag);
  if (iv.byteLength !== 12 || tag.byteLength !== 16 || ciphertext.byteLength === 0) {
    throw new Error("Stored cTrader token record has invalid AES-GCM component lengths.");
  }
  const combined = new Uint8Array(ciphertext.length + tag.length);
  combined.set(ciphertext);
  combined.set(tag, ciphertext.length);
  const clear = await crypto.subtle.decrypt(
    { name: "AES-GCM", iv, tagLength: 128 },
    key,
    combined,
  );
  return JSON.parse(decoder.decode(clear));
}
