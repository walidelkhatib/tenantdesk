// Run with: node --test 'tests/frontend/*.test.mjs'
import assert from "node:assert/strict";
import test from "node:test";

import {
  base64UrlEncode,
  decodeJwtPayload,
  pkceChallenge,
  randomString,
  tenantFromClaims,
  textFromSseLine,
} from "../../frontend/lib.js";

test("PKCE challenge matches the RFC 7636 test vector", async () => {
  // RFC 7636 Appendix B: this verifier must hash to this challenge.
  const challenge = await pkceChallenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk");
  assert.equal(challenge, "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM");
});

test("random strings are URL-safe and unique", () => {
  const a = randomString(48);
  assert.match(a, /^[A-Za-z0-9_-]+$/);
  assert.equal(a.length, 64);
  assert.notEqual(a, randomString(48));
});

test("base64url has no padding or unsafe characters", () => {
  assert.equal(base64UrlEncode(new Uint8Array([251, 255])), "-_8");
});

test("decodes a JWT payload with unicode and missing padding", () => {
  const payload = { email: "zoë@acme.example", "cognito:groups": ["tenant-acme"] };
  const encoded = Buffer.from(JSON.stringify(payload)).toString("base64url");
  assert.deepEqual(decodeJwtPayload(`h.${encoded}.s`), payload);
  assert.throws(() => decodeJwtPayload("not-a-jwt"));
});

test("tenant is shown only when the user has exactly one tenant group", () => {
  assert.equal(tenantFromClaims({ "cognito:groups": ["beta", "tenant-globex"] }), "globex");
  assert.equal(tenantFromClaims({ "cognito:groups": ["tenant-acme", "tenant-globex"] }), null);
  assert.equal(tenantFromClaims({}), null);
  assert.equal(tenantFromClaims(null), null);
});

test("SSE lines become text chunks", () => {
  assert.equal(textFromSseLine('data: "Hello, "'), "Hello, ");
  assert.equal(textFromSseLine('data: "line\\nbreak"'), "line\nbreak");
  assert.equal(textFromSseLine("data: plain text"), "plain text");
  assert.equal(textFromSseLine('data: {"event": 1}'), "");
  assert.equal(textFromSseLine(": keep-alive"), "");
  assert.equal(textFromSseLine(""), "");
});
