"""MCP client for the TenantDesk Gateway.

The client is created per request with the caller's own bearer token, so the
Gateway (and its Cedar policies) see the real user and tenant on every tool
call. A client built once at startup would keep the first user's token.
"""

import logging
import os

from mcp.client.streamable_http import streamablehttp_client
from strands.tools.mcp.mcp_client import MCPClient

logger = logging.getLogger(__name__)

# Set on the runtime by the AgentCore CDK construct at deploy time.
GATEWAY_URL_ENV = "AGENTCORE_GATEWAY_TENANTDESK_GATEWAY_URL"


def get_gateway_client(bearer: str) -> MCPClient | None:
    url = os.environ.get(GATEWAY_URL_ENV)
    if not url:
        logger.warning("%s is not set; support tools are unavailable", GATEWAY_URL_ENV)
        return None
    return MCPClient(lambda: streamablehttp_client(url=url, headers={"Authorization": bearer}))
