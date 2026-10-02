// Sign-in with the Cognito hosted UI: OAuth 2.0 authorization code flow with PKCE.
// The user types their password on Cognito's page, never on ours, and the app
// client has no secret. Tokens are kept in sessionStorage, so they are cleared
// when the tab closes.

import config from "./config.js";
import { decodeJwtPayload, pkceChallenge, randomString } from "./lib.js";

const TOKENS_KEY = "tenantdesk.tokens";
const PENDING_KEY = "tenantdesk.pkce";
const redirectUri = `${window.location.origin}/`;

const loadTokens = () => JSON.parse(sessionStorage.getItem(TOKENS_KEY) || "null");
const saveTokens = (tokens) => sessionStorage.setItem(TOKENS_KEY, JSON.stringify(tokens));

export async function signIn() {
  const verifier = randomString(48);
  const state = randomString(16);
  sessionStorage.setItem(PENDING_KEY, JSON.stringify({ verifier, state }));
  const params = new URLSearchParams({
    response_type: "code",
    client_id: config.clientId,
    redirect_uri: redirectUri,
    scope: "openid email profile",
    state,
    code_challenge_method: "S256",
    code_challenge: await pkceChallenge(verifier),
  });
  window.location.assign(`${config.cognitoDomain}/oauth2/authorize?${params}`);
}

// Called on page load. If Cognito just redirected back with ?code=..., trade it for tokens.
export async function completeSignInIfReturning() {
  const params = new URLSearchParams(window.location.search);
  if (!params.has("code") && !params.has("error")) return;
  window.history.replaceState({}, "", redirectUri); // remove the code from the address bar

  if (params.has("error")) {
    throw new Error(params.get("error_description") || params.get("error"));
  }
  const pending = JSON.parse(sessionStorage.getItem(PENDING_KEY) || "null");
  sessionStorage.removeItem(PENDING_KEY);
  if (!pending || pending.state !== params.get("state")) {
    throw new Error("Sign-in could not be verified. Please try again.");
  }
  await requestTokens({
    grant_type: "authorization_code",
    code: params.get("code"),
    redirect_uri: redirectUri,
    code_verifier: pending.verifier,
  });
}

async function requestTokens(fields) {
  const resp = await fetch(`${config.cognitoDomain}/oauth2/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ client_id: config.clientId, ...fields }),
  });
  if (!resp.ok) throw new Error(`Token request failed (${resp.status})`);
  const body = await resp.json();
  const previous = loadTokens();
  saveTokens({
    accessToken: body.access_token,
    idToken: body.id_token,
    refreshToken: body.refresh_token || previous?.refreshToken, // refresh responses omit it
    expiresAt: Date.now() + body.expires_in * 1000,
  });
}

// Returns a valid access token, refreshing it if it expires within a minute.
export async function getAccessToken() {
  const tokens = loadTokens();
  if (!tokens) return null;
  if (Date.now() < tokens.expiresAt - 60_000) return tokens.accessToken;
  try {
    if (!tokens.refreshToken) throw new Error("no refresh token");
    await requestTokens({ grant_type: "refresh_token", refresh_token: tokens.refreshToken });
    return loadTokens().accessToken;
  } catch {
    sessionStorage.removeItem(TOKENS_KEY);
    return null;
  }
}

// ID token claims (email, groups) for display in the header.
export function displayClaims() {
  const tokens = loadTokens();
  return tokens?.idToken ? decodeJwtPayload(tokens.idToken) : null;
}

export function signOut() {
  sessionStorage.clear();
  const params = new URLSearchParams({ client_id: config.clientId, logout_uri: redirectUri });
  window.location.assign(`${config.cognitoDomain}/logout?${params}`);
}
