"""TenantDesk support agent (AgentCore Runtime entrypoint).

Request flow:
1. AgentCore Runtime validates the caller's Cognito JWT before this code runs.
2. `caller_from_headers` reads the user (`sub`) and tenant (`cognito:groups`).
3. A new agent is built for this request with that tenant in its prompt, the
   user's memory, and a Gateway client carrying the user's own token.
4. The Gateway checks each tool call against Cedar policies; the tools Lambda
   scopes data to the tenant.

The agent is built per request rather than cached. Conversation history is
reloaded from AgentCore Memory, so nothing is lost, and a later request can
never reuse an earlier caller's token or tenant.
"""

import uuid

from strands import Agent
from strands.agent.conversation_manager import SlidingWindowConversationManager
from bedrock_agentcore.runtime import BedrockAgentCoreApp

from identity import AuthError, caller_from_headers
from mcp_client.client import get_gateway_client
from memory.session import get_memory_session_manager
from model.load import load_model
from prompts import build_system_prompt

app = BedrockAgentCoreApp()
log = app.logger

MAX_PROMPT_CHARS = 4000


def read_prompt(payload) -> str:
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")
    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("'prompt' must be a non-empty string")
    if len(prompt) > MAX_PROMPT_CHARS:
        raise ValueError(f"'prompt' must be at most {MAX_PROMPT_CHARS} characters")
    return prompt.strip()


def build_agent(caller, session_id: str) -> Agent:
    gateway = get_gateway_client(caller.bearer)
    return Agent(
        model=load_model(),
        system_prompt=build_system_prompt(caller.tenant_id),
        tools=[gateway] if gateway else [],
        session_manager=get_memory_session_manager(session_id, caller.user_id),
        # Bound what is sent to the model each turn; full history stays in Memory.
        conversation_manager=SlidingWindowConversationManager(window_size=20),
        # Searchable in traces: cost and quality per tenant.
        trace_attributes={"tenant.id": caller.tenant_id, "session.id": session_id},
    )


@app.entrypoint
async def invoke(payload, context):
    try:
        caller = caller_from_headers(getattr(context, "request_headers", None))
        prompt = read_prompt(payload)
    except (AuthError, ValueError) as err:
        log.warning("Rejected request: %s", err)
        yield f"Request rejected: {err}"
        return

    session_id = getattr(context, "session_id", None) or uuid.uuid4().hex
    log.info("tenant=%s session=%s", caller.tenant_id, session_id)

    agent = build_agent(caller, session_id)
    async for event in agent.stream_async(prompt):
        if isinstance(event, dict) and isinstance(event.get("data"), str):
            yield event["data"]


if __name__ == "__main__":
    app.run()
