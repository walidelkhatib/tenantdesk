"""AgentCore Memory wiring for the support agent.

The actor ID is the user's Cognito `sub`. Every user belongs to exactly one
tenant, so per-user namespaces are also per-tenant. These namespace paths
must match the `namespaceTemplates` in agentcore/agentcore.template.json.
"""

import os
from typing import Optional

from bedrock_agentcore.memory.integrations.strands.config import AgentCoreMemoryConfig, RetrievalConfig
from bedrock_agentcore.memory.integrations.strands.session_manager import AgentCoreMemorySessionManager

# Set on the runtime by the AgentCore CDK construct at deploy time.
MEMORY_ID = os.getenv("MEMORY_SUPPORTAGENTMEMORY_ID")
REGION = os.getenv("AWS_REGION")


def get_memory_session_manager(session_id: str, actor_id: str) -> Optional[AgentCoreMemorySessionManager]:
    if not MEMORY_ID:
        return None

    retrieval_config = {
        f"/users/{actor_id}/facts": RetrievalConfig(top_k=3, relevance_score=0.5),
        f"/summaries/{actor_id}/{session_id}": RetrievalConfig(top_k=1, relevance_score=0.3),
    }
    return AgentCoreMemorySessionManager(
        AgentCoreMemoryConfig(
            memory_id=MEMORY_ID,
            session_id=session_id,
            actor_id=actor_id,
            retrieval_config=retrieval_config,
        ),
        REGION,
    )
