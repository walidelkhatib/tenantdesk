"""TenantDesk tools Lambda.

One Lambda serves every tool behind the AgentCore Gateway target. The Gateway
passes the tool arguments as `event` and the tool name in the client context as
"<target>___<tool>", so the handler routes on that name.

Tenant isolation here is defense in depth. The Cedar policy at the Gateway has
already checked that `tenant_id` matches the caller's Cognito group. This code
still scopes every read and write to that tenant's partition, so a record ID
from another tenant can never be found.
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable

log = logging.getLogger()
log.setLevel(logging.INFO)

TENANT_ID_RE = re.compile(r"^[a-z0-9-]{2,32}$")
MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
INVOICE_ID_RE = re.compile(r"^INV-[A-Z0-9-]{1,32}$")
PRIORITIES = {"low", "normal", "high"}
INVOICE_STATUSES = {"paid", "open", "past_due"}


class ToolError(Exception):
    """A user-facing error. The message is returned to the agent."""


class Store:
    """Thin wrapper over the DynamoDB table so tests can swap in a fake."""

    def __init__(self, table):
        self._table = table

    def get(self, pk: str, sk: str) -> dict | None:
        return self._table.get_item(Key={"pk": pk, "sk": sk}).get("Item")

    def put(self, item: dict) -> None:
        self._table.put_item(Item=item)

    def query_prefix(self, pk: str, prefix: str, newest_first: bool = False,
                     limit: int | None = None) -> list[dict]:
        from boto3.dynamodb.conditions import Key

        kwargs: dict[str, Any] = {
            "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").begins_with(prefix),
            "ScanIndexForward": not newest_first,
        }
        if limit:
            kwargs["Limit"] = limit
        return self._table.query(**kwargs).get("Items", [])

    def scan_profiles(self) -> list[dict]:
        """All tenant profile records. Fine for a demo table; a real system would keep a tenant index."""
        from boto3.dynamodb.conditions import Attr

        items, kwargs = [], {"FilterExpression": Attr("sk").eq("PROFILE")}
        while True:
            page = self._table.scan(**kwargs)
            items += page.get("Items", [])
            if "LastEvaluatedKey" not in page:
                return items
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


_store: Store | None = None


def get_store() -> Store:
    global _store
    if _store is None:
        import boto3

        _store = Store(boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"]))
    return _store


# --- helpers -----------------------------------------------------------------

def tenant_pk(tenant_id: str) -> str:
    return f"TENANT#{tenant_id}"


def public(item: dict) -> dict:
    """Drop storage keys and convert DynamoDB Decimals for JSON."""
    out = {}
    for key, value in item.items():
        if key in ("pk", "sk"):
            continue
        if isinstance(value, Decimal):
            value = int(value) if value == value.to_integral_value() else float(value)
        out[key] = value
    return out


def require_str(event: dict, name: str, min_len: int, max_len: int) -> str:
    value = event.get(name)
    if not isinstance(value, str) or not (min_len <= len(value.strip()) <= max_len):
        raise ToolError(f"'{name}' must be text between {min_len} and {max_len} characters")
    return value.strip()


def resolve_tenant(store: Store, event: dict) -> str:
    tenant_id = event.get("tenant_id")
    if not isinstance(tenant_id, str) or not TENANT_ID_RE.match(tenant_id):
        raise ToolError("invalid tenant_id")
    if store.get(tenant_pk(tenant_id), "PROFILE") is None:
        raise ToolError("unknown tenant")
    return tenant_id


def tool_name_from(context) -> str:
    try:
        full_name = context.client_context.custom["bedrockAgentCoreToolName"]
    except (AttributeError, KeyError, TypeError):
        raise ToolError("missing tool name in request context")
    return full_name.split("___", 1)[-1]


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- tools -------------------------------------------------------------------

def get_subscription(store: Store, tenant_id: str, event: dict) -> dict:
    return public(store.get(tenant_pk(tenant_id), "PROFILE"))


def get_usage(store: Store, tenant_id: str, event: dict) -> dict:
    month = event.get("month")
    if month is not None:
        if not isinstance(month, str) or not MONTH_RE.match(month):
            raise ToolError("'month' must look like YYYY-MM")
        item = store.get(tenant_pk(tenant_id), f"USAGE#{month}")
        if item is None:
            raise ToolError(f"no usage recorded for {month}")
        return public(item)
    latest = store.query_prefix(tenant_pk(tenant_id), "USAGE#", newest_first=True, limit=1)
    if not latest:
        raise ToolError("no usage recorded yet")
    return public(latest[0])


def list_invoices(store: Store, tenant_id: str, event: dict) -> dict:
    status = event.get("status")
    if status is not None and status not in INVOICE_STATUSES:
        raise ToolError(f"'status' must be one of {sorted(INVOICE_STATUSES)}")
    invoices = [public(i) for i in store.query_prefix(tenant_pk(tenant_id), "INVOICE#")]
    if status:
        invoices = [i for i in invoices if i.get("status") == status]
    return {"invoices": invoices, "count": len(invoices)}


def create_ticket(store: Store, tenant_id: str, event: dict) -> dict:
    subject = require_str(event, "subject", 5, 120)
    description = require_str(event, "description", 10, 2000)
    priority = event.get("priority", "normal")
    if priority not in PRIORITIES:
        raise ToolError(f"'priority' must be one of {sorted(PRIORITIES)}")
    ticket_id = f"TCK-{uuid.uuid4().hex[:8].upper()}"
    store.put({
        "pk": tenant_pk(tenant_id), "sk": f"TICKET#{ticket_id}",
        "ticket_id": ticket_id, "subject": subject, "description": description,
        "priority": priority, "status": "open", "created_at": now_iso(),
    })
    return {"ticket_id": ticket_id, "status": "open", "priority": priority}


def request_credit(store: Store, tenant_id: str, event: dict) -> dict:
    invoice_id = event.get("invoice_id")
    if not isinstance(invoice_id, str) or not INVOICE_ID_RE.match(invoice_id):
        raise ToolError("'invoice_id' must look like INV-A-1009")
    amount = event.get("amount")
    if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        raise ToolError("'amount' must be a positive whole number of dollars")
    reason = require_str(event, "reason", 10, 500)

    # Looked up inside this tenant's partition, so another tenant's invoice ID
    # simply does not exist from here.
    invoice = store.get(tenant_pk(tenant_id), f"INVOICE#{invoice_id}")
    if invoice is None:
        raise ToolError(f"invoice {invoice_id} not found")
    if amount > int(invoice["amount"]):
        raise ToolError("credit cannot exceed the invoice amount")

    credit_id = f"CR-{uuid.uuid4().hex[:8].upper()}"
    store.put({
        "pk": tenant_pk(tenant_id), "sk": f"CREDIT#{credit_id}",
        "credit_id": credit_id, "invoice_id": invoice_id, "amount": amount,
        "reason": reason, "status": "applied", "created_at": now_iso(),
    })
    return {"credit_id": credit_id, "invoice_id": invoice_id, "amount": amount, "status": "applied"}


def get_tenant_health(store: Store, event: dict) -> dict:
    """Internal ops view across all tenants: plan, account status, and usage pressure.

    Returns only aggregate indicators, never invoices, tickets, or other records.
    Cedar allows this tool only for the ops machine client, and never for customers.
    """
    tenants = []
    for profile in store.scan_profiles():
        tenant_id = profile["tenant_id"]
        latest = store.query_prefix(tenant_pk(tenant_id), "USAGE#", newest_first=True, limit=1)
        usage = latest[0] if latest else {}

        def pct(used, limit):
            return round(100 * int(used) / int(limit)) if used is not None and limit else None

        tenants.append({
            "tenant_id": tenant_id,
            "company": profile["company"],
            "plan": profile["plan"],
            "account_status": profile["status"],
            "seat_utilization_pct": pct(profile.get("seats_used"), profile.get("seats")),
            "usage_month": usage.get("month"),
            "api_utilization_pct": pct(usage.get("api_calls"), usage.get("api_limit")),
            "storage_utilization_pct": pct(usage.get("storage_gb"), usage.get("storage_limit_gb")),
        })
    return {"tenants": sorted(tenants, key=lambda t: t["tenant_id"]), "count": len(tenants)}


TOOLS: dict[str, Callable[[Store, str, dict], dict]] = {
    "get_subscription": get_subscription,
    "get_usage": get_usage,
    "list_invoices": list_invoices,
    "create_ticket": create_ticket,
    "request_credit": request_credit,
}

# Tools that work across tenants and take no tenant_id. Only the ops client may call them.
OPS_TOOLS: dict[str, Callable[[Store, dict], dict]] = {
    "get_tenant_health": get_tenant_health,
}


# --- entry point -------------------------------------------------------------

def handler(event, context, store: Store | None = None) -> dict:
    tool = "unknown"
    tenant_id = None
    try:
        tool = tool_name_from(context)
        if not isinstance(event, dict):
            raise ToolError("tool arguments must be an object")
        if tool in OPS_TOOLS:
            result = OPS_TOOLS[tool](store or get_store(), event)
            log.info(json.dumps({"tool": tool, "tenant_id": "*", "outcome": "ok"}))
            return result
        fn = TOOLS.get(tool)
        if fn is None:
            raise ToolError(f"unknown tool '{tool}'")
        store = store or get_store()
        tenant_id = resolve_tenant(store, event)
        result = fn(store, tenant_id, event)
        log.info(json.dumps({"tool": tool, "tenant_id": tenant_id, "outcome": "ok"}))
        return result
    except ToolError as err:
        log.warning(json.dumps({"tool": tool, "tenant_id": tenant_id, "outcome": "rejected", "reason": str(err)}))
        return {"error": str(err)}
    except Exception:
        log.exception(json.dumps({"tool": tool, "tenant_id": tenant_id, "outcome": "error"}))
        return {"error": "internal error"}
