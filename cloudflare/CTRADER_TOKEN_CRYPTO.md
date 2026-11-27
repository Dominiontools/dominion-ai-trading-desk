# cTrader token cryptography port

The original cTrader service stores a JSON record encrypted with AES-256-GCM using a
base64-encoded 32-byte `CTRADER_TOKEN_ENCRYPTION_KEY`. The record contains
`version`, `algorithm`, `iv`, `tag`, `ciphertext`, and `savedAt`.

`src/cloudflare/ctrader-token-crypto.js` implements the same record shape using the
Web Crypto API available in Cloudflare Workers. It uses a fresh 96-bit IV per encryption
and a 128-bit authentication tag. The helper accepts the key as an argument and never
reads or logs secrets.

## Migration safety

- This helper is not wired to a route or D1 yet.
- Do not copy the old Netlify Blob ciphertext into D1 until the existing key is securely
  available as a Cloudflare Worker secret and a round-trip compatibility test has passed.
- Never put the key, OAuth client secret, access token, or refresh token in GitHub.
- Keep view-only and trading records separate.
- A decrypted token must not be returned to the browser or included in logs.
- A token record alone is not proof of a verified Pepperstone demo account. Status must
  remain disconnected until the broker account-list and account-auth handshake succeeds.
- No trade is placed by this helper.
