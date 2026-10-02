# SupportAgent

The customer-facing TenantDesk agent, deployed to AgentCore Runtime as a CodeZip.
See [docs/WALKTHROUGH.md](../../docs/WALKTHROUGH.md) for a file-by-file explanation.

| File | Purpose |
|---|---|
| `main.py` | Runtime entrypoint. Builds a new agent for each request. |
| `identity.py` | Reads the user (`sub`) and tenant (`cognito:groups`) from the validated access token. |
| `prompts.py` | System prompt, pinned to the caller's tenant. |
| `mcp_client/client.py` | Gateway client that forwards the user's own token. |
| `memory/session.py` | AgentCore Memory session manager, keyed by the user's `sub`. |
| `model/load.py` | Bedrock model selection. |
