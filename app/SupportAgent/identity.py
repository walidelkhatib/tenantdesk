"""Who is calling, and which tenant they belong to.

AgentCore Runtime validates the JWT (signature, issuer, expiry, client ID)
before this code runs. Here we only read the claims we need:

- `sub`: the user's stable ID. Used as the memory actor ID, so a recreated
  user with the same email never inherits someone else's memory.
- `cognito:groups`: tenant membership. A user must be in exactly one
  `tenant-<id>` group; anything else is rejected rather than guessed.
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass

TENANT_GROUP_RE = re.compile(r"^tenant-([a-z0-9-]{2,32})$")


class AuthError(Exception):
    """The request cannot be tied to exactly one user and one tenant."""


@dataclass(frozen=True)
class Caller:
    user_id: str      # Cognito `sub`
    tenant_id: str    # e.g. "acme"
    username: str     # for logs only, never for authorization
    bearer: str       # "Bearer <token>", forwarded to the Gateway


def _claims(token: str) -> dict:
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except (IndexError, ValueError) as err:
        raise AuthError("malformed token") from err


def caller_from_headers(headers: dict | None) -> Caller:
    headers = {k.lower(): v for k, v in (headers or {}).items()}
    auth = headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        raise AuthError("missing bearer token")

    claims = _claims(auth.removeprefix("Bearer ").strip())
    if claims.get("token_use") != "access":
        raise AuthError("an access token is required")

    sub = claims.get("sub")
    if not isinstance(sub, str) or not sub:
        raise AuthError("token has no subject")

    groups = claims.get("cognito:groups") or []
    tenants = [m.group(1) for g in groups if isinstance(g, str) and (m := TENANT_GROUP_RE.match(g))]
    if len(tenants) != 1:
        raise AuthError("user must belong to exactly one tenant")

    return Caller(user_id=sub, tenant_id=tenants[0],
                  username=str(claims.get("username", "")), bearer=auth)
