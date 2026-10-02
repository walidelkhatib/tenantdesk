"""Unit tests for the support agent's identity and input handling. Offline."""

import base64
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app" / "SupportAgent"))

from identity import AuthError, caller_from_headers  # noqa: E402
from prompts import build_system_prompt  # noqa: E402


def token(**claims) -> str:
    """Build an unsigned JWT. Signature checks happen in AgentCore Runtime, not here."""
    def b64(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()
    return f"{b64({'alg': 'none'})}.{b64(claims)}.sig"


def headers(**claims):
    base = {"sub": "user-123", "token_use": "access", "username": "alex", "cognito:groups": ["tenant-acme"]}
    base.update(claims)
    return {"Authorization": f"Bearer {token(**{k: v for k, v in base.items() if v is not None})}"}


def test_reads_user_and_tenant():
    caller = caller_from_headers(headers())
    assert (caller.user_id, caller.tenant_id) == ("user-123", "acme")
    assert caller.bearer.startswith("Bearer ")


def test_header_name_is_case_insensitive():
    h = headers()
    assert caller_from_headers({"authorization": h["Authorization"]}).tenant_id == "acme"


@pytest.mark.parametrize("bad_headers", [None, {}, {"Authorization": "Basic abc"}, {"Authorization": "Bearer not-a-jwt"}])
def test_rejects_missing_or_malformed_token(bad_headers):
    with pytest.raises(AuthError):
        caller_from_headers(bad_headers)


def test_rejects_id_tokens():
    with pytest.raises(AuthError, match="access token"):
        caller_from_headers(headers(token_use="id"))


def test_rejects_token_without_subject():
    with pytest.raises(AuthError, match="subject"):
        caller_from_headers(headers(sub=None))


@pytest.mark.parametrize("groups", [[], None, ["admins"], ["tenant-acme", "tenant-globex"], ["tenant-ACME"], ["tenant-x"]])
def test_requires_exactly_one_valid_tenant_group(groups):
    with pytest.raises(AuthError, match="exactly one tenant"):
        caller_from_headers(headers(**{"cognito:groups": groups}))


def test_non_tenant_groups_are_ignored():
    assert caller_from_headers(headers(**{"cognito:groups": ["beta-testers", "tenant-globex"]})).tenant_id == "globex"


def test_prompt_pins_the_tenant():
    prompt = build_system_prompt("globex")
    assert 'tenant_id "globex"' in prompt
    assert "acme" not in prompt
