// Pure helpers used by auth.js and app.js. No DOM access, so Node tests can import them.

export function base64UrlEncode(bytes) {
  let binary = "";
  for (const b of bytes) binary += String.fromCharCode(b);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function randomString(byteLength = 32) {
  const bytes = new Uint8Array(byteLength);
  crypto.getRandomValues(bytes);
  return base64UrlEncode(bytes);
}

// PKCE (RFC 7636): the browser proves it started the sign-in by revealing the
// verifier whose SHA-256 hash it sent up front. No client secret is needed.
export async function pkceChallenge(verifier) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
  return base64UrlEncode(new Uint8Array(digest));
}

// Reads claims for display only. The server validates tokens; the browser never trusts them.
export function decodeJwtPayload(token) {
  const part = String(token).split(".")[1];
  if (!part) throw new Error("malformed token");
  const b64 = part.replace(/-/g, "+").replace(/_/g, "/");
  const padded = b64.padEnd(Math.ceil(b64.length / 4) * 4, "=");
  const bytes = Uint8Array.from(atob(padded), (c) => c.charCodeAt(0));
  return JSON.parse(new TextDecoder().decode(bytes));
}

export function tenantFromClaims(claims) {
  const tenants = (claims?.["cognito:groups"] || [])
    .map((g) => /^tenant-([a-z0-9-]{2,32})$/.exec(g))
    .filter(Boolean)
    .map((m) => m[1]);
  return tenants.length === 1 ? tenants[0] : null;
}

// The agent streams server-sent events. Each text chunk arrives as `data: "<json string>"`.
export function textFromSseLine(line) {
  if (!line.startsWith("data:")) return "";
  const raw = line.slice(5).trim();
  if (!raw) return "";
  try {
    const value = JSON.parse(raw);
    return typeof value === "string" ? value : "";
  } catch {
    return raw;
  }
}
