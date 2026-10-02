"""Evaluate the Cedar policies in policies/ offline with the open-source Cedar engine.

This models how AgentCore Policy presents a Gateway tool call to Cedar: an
AgentCore::OAuthUser principal whose JWT claims are string tags, the tool as
the action, the Gateway as the resource, and tool arguments in context.input.
It checks policy logic before deploy; the live isolation tests confirm the
deployed behavior.
"""

import json
from pathlib import Path

import cedarpy
import pytest

POLICY_DIR = Path(__file__).resolve().parents[2] / "policies"
GATEWAY = "arn:aws:bedrock-agentcore:us-east-1:000000000000:gateway/test"


def load_policies() -> str:
    texts = [p.read_text().replace("{{GATEWAY_ARN}}", GATEWAY) for p in sorted(POLICY_DIR.glob("*.cedar"))]
    return "\n".join(texts)


POLICIES = load_policies()


def decide(groups, tool, claims=None, **tool_input) -> str:
    tags = {"sub": "user-1", "token_use": "access"}
    if groups is not None:
        tags["cognito:groups"] = json.dumps(groups, separators=(",", ":"))  # arrays arrive as JSON text
    tags.update(claims or {})
    entities = [{"uid": {"type": "AgentCore::OAuthUser", "id": "user-1"}, "attrs": {}, "parents": [], "tags": tags}]
    request = {
        "principal": 'AgentCore::OAuthUser::"user-1"',
        "action": f'AgentCore::Action::"TenantTools___{tool}"',
        "resource": f'AgentCore::Gateway::"{GATEWAY}"',
        "context": {"input": tool_input},
    }
    result = cedarpy.is_authorized(request, POLICIES, entities)
    return "allow" if result.decision == cedarpy.Decision.Allow else "deny"


ACME = ["tenant-acme"]
GLOBEX = ["tenant-globex"]


def test_policies_parse():
    parsed = json.loads(cedarpy.policies_to_json_str(POLICIES))
    assert len(parsed["staticPolicies"]) == 5


# --- tenant isolation ------------------------------------------------------------

@pytest.mark.parametrize("tool", ["get_subscription", "get_usage", "list_invoices"])
def test_users_can_read_their_own_tenant(tool):
    assert decide(ACME, tool, tenant_id="acme") == "allow"
    assert decide(GLOBEX, tool, tenant_id="globex") == "allow"


@pytest.mark.parametrize("tool", ["get_subscription", "get_usage", "list_invoices", "create_ticket", "request_credit"])
def test_cross_tenant_calls_are_denied(tool):
    assert decide(ACME, tool, tenant_id="globex", amount=10, reason="outage") == "deny"
    assert decide(GLOBEX, tool, tenant_id="acme", amount=10, reason="outage") == "deny"


def test_missing_tenant_id_is_denied():
    assert decide(ACME, "get_subscription") == "deny"


@pytest.mark.parametrize("groups", [None, [], ["admins"], ["tenant-acmex"], ["xtenant-acme"]])
def test_users_without_a_matching_group_are_denied(groups):
    assert decide(groups, "get_subscription", tenant_id="acme") == "deny"


def test_unknown_tool_is_denied_by_default():
    assert decide(ACME, "delete_tenant", tenant_id="acme") == "deny"


# --- credit guardrails -----------------------------------------------------------

def test_credit_within_limit_with_reason_is_allowed():
    assert decide(GLOBEX, "request_credit", tenant_id="globex", invoice_id="INV-G-2041",
                  amount=50, reason="Outage on Sept 3") == "allow"


def test_credit_over_limit_is_denied():
    assert decide(GLOBEX, "request_credit", tenant_id="globex", invoice_id="INV-G-2041",
                  amount=51, reason="Outage on Sept 3") == "deny"


@pytest.mark.parametrize("missing", ["amount", "reason"])
def test_credit_with_missing_field_is_denied(missing):
    args = {"tenant_id": "globex", "invoice_id": "INV-G-2041", "amount": 20, "reason": "Outage on Sept 3"}
    del args[missing]
    assert decide(GLOBEX, "request_credit", **args) == "deny"


def test_credit_with_empty_reason_is_denied():
    assert decide(GLOBEX, "request_credit", tenant_id="globex", invoice_id="INV-G-2041",
                  amount=20, reason="") == "deny"


def test_credit_rule_does_not_affect_other_tools():
    assert decide(ACME, "create_ticket", tenant_id="acme", subject="Slow dashboards",
                  description="Dashboards take 30 seconds to load.") == "allow"


# --- internal ops client -----------------------------------------------------------

OPS = {"scope": "tenantdesk/ops.read", "client_id": "ops-client", "token_use": "access"}


def test_ops_client_can_read_tenant_health():
    assert decide(None, "get_tenant_health", claims=OPS) == "allow"


def test_customers_cannot_read_tenant_health():
    assert decide(ACME, "get_tenant_health") == "deny"
    # even a customer token that somehow carried the scope is denied, because it has a tenant group
    assert decide(ACME, "get_tenant_health", claims={"scope": "openid tenantdesk/ops.read"}) == "deny"


@pytest.mark.parametrize("tool", ["get_subscription", "list_invoices", "create_ticket", "request_credit"])
def test_ops_client_cannot_use_customer_tools(tool):
    assert decide(None, tool, claims=OPS, tenant_id="acme", amount=10, reason="outage") == "deny"


def test_token_without_ops_scope_cannot_read_tenant_health():
    assert decide(None, "get_tenant_health", claims={"scope": "openid email"}) == "deny"
