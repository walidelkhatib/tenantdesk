// TenantDesk chat page. The browser calls AgentCore Runtime directly with the
// signed-in user's access token. The Runtime validates the token before the
// agent runs; nothing on this page is trusted for authorization.

import config from "./config.js";
import { completeSignInIfReturning, displayClaims, getAccessToken, signIn, signOut } from "./auth.js";
import { tenantFromClaims, textFromSseLine } from "./lib.js";

const $ = (id) => document.getElementById(id);
const SESSION_KEY = "tenantdesk.session";

// One AgentCore session per conversation. Reusing the ID lets the agent reload history from Memory.
function sessionId() {
  let id = sessionStorage.getItem(SESSION_KEY);
  if (!id) {
    id = crypto.randomUUID(); // 36 chars; AgentCore requires at least 33
    sessionStorage.setItem(SESSION_KEY, id);
  }
  return id;
}

function newConversation() {
  sessionStorage.removeItem(SESSION_KEY);
  $("messages").replaceChildren();
  $("prompt").focus();
}

function addMessage(role, text = "") {
  const el = document.createElement("div");
  el.className = `message ${role}`;
  el.textContent = text; // textContent, never innerHTML: model output is untrusted
  $("messages").append(el);
  el.scrollIntoView({ block: "end" });
  return el;
}

function showError(message) {
  $("error").textContent = message;
  $("error").hidden = false;
}

function invocationUrl() {
  const arn = encodeURIComponent(config.runtimeArn);
  return `https://bedrock-agentcore.${config.region}.amazonaws.com/runtimes/${arn}/invocations?qualifier=DEFAULT`;
}

async function streamReply(resp, el) {
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  el.textContent = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop(); // keep a partial line for the next chunk
    for (const line of lines) el.textContent += textFromSseLine(line);
    el.scrollIntoView({ block: "end" });
  }
  el.textContent += textFromSseLine(buffer);
  if (!el.textContent) el.textContent = "(no response)";
}

async function send(prompt) {
  const token = await getAccessToken();
  if (!token) return signIn();

  addMessage("user", prompt);
  const reply = addMessage("assistant", "Thinking…");
  $("send").disabled = true;
  try {
    const resp = await fetch(invocationUrl(), {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
        "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": sessionId(),
      },
      body: JSON.stringify({ prompt }),
    });
    if (!resp.ok) {
      reply.classList.add("error");
      reply.textContent = `Error ${resp.status}: ${await resp.text()}`;
      return;
    }
    await streamReply(resp, reply);
  } catch (err) {
    reply.classList.add("error");
    reply.textContent = `Request failed: ${err.message}`;
  } finally {
    $("send").disabled = false;
    $("prompt").focus();
  }
}

async function init() {
  $("sign-in").addEventListener("click", signIn);
  $("sign-out").addEventListener("click", signOut);
  $("new-chat").addEventListener("click", newConversation);
  $("chat-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const prompt = $("prompt").value.trim();
    if (!prompt) return;
    $("prompt").value = "";
    send(prompt);
  });
  $("prompt").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      $("chat-form").requestSubmit();
    }
  });
  for (const button of document.querySelectorAll("[data-prompt]")) {
    button.addEventListener("click", () => send(button.dataset.prompt));
  }

  try {
    await completeSignInIfReturning();
  } catch (err) {
    showError(err.message);
  }
  if (!config.runtimeArn) {
    showError("No agent configured yet. Deploy the agent, then run scripts/render_config.py.");
  }

  const signedIn = Boolean(await getAccessToken());
  $("signed-out").hidden = signedIn;
  $("signed-in").hidden = !signedIn;
  if (signedIn) {
    const claims = displayClaims();
    $("who").textContent = `${claims?.email ?? "signed in"} · tenant: ${tenantFromClaims(claims) ?? "none"}`;
    $("prompt").focus();
  }
}

init();
