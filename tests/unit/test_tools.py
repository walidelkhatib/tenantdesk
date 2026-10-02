"""Unit tests for the tools Lambda. Runs offline against an in-memory store."""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import handler  # noqa: E402
import seed_data  # noqa: E402


class FakeStore(handler.Store):
    def __init__(self, items):
        self.items = {(i["pk"], i["sk"]): dict(i) for i in items}

    def get(self, pk, sk):
        return self.items.get((pk, sk))

    def put(self, item):
        self.items[(item["pk"], item["sk"])] = dict(item)

    def query_prefix(self, pk, prefix, newest_first=False, limit=None):
        rows = sorted(
            (v for (p, s), v in self.items.items() if p == pk and s.startswith(prefix)),
            key=lambda v: v["sk"], reverse=newest_first,
        )
        return rows[:limit] if limit else rows

    def scan_profiles(self):
        return [v for (_, s), v in self.items.items() if s == "PROFILE"]


def ctx(tool: str):
    return SimpleNamespace(client_context=SimpleNamespace(custom={"bedrockAgentCoreToolName": f"TenantTools___{tool}"}))


@pytest.fixture
def store():
    return FakeStore(seed_data.items())


def call(store, tool, **args):
    return handler.handler(args, ctx(tool), store=store)


# --- routing and validation ---------------------------------------------------

def test_routes_by_tool_name_and_strips_target_prefix(store):
    assert call(store, "get_subscription", tenant_id="acme")["company"] == "Acme Robotics"


def test_unknown_tool_is_rejected(store):
    assert call(store, "delete_everything", tenant_id="acme") == {"error": "unknown tool 'delete_everything'"}


def test_missing_tool_name_is_rejected(store):
    assert "missing tool name" in handler.handler({"tenant_id": "acme"}, SimpleNamespace(), store=store)["error"]


@pytest.mark.parametrize("tenant_id", [None, "", "ACME", "acme; drop", "a" * 40, 123])
def test_malformed_tenant_id_is_rejected(store, tenant_id):
    assert call(store, "get_subscription", tenant_id=tenant_id) == {"error": "invalid tenant_id"}


def test_unknown_tenant_is_rejected(store):
    assert call(store, "get_subscription", tenant_id="initech") == {"error": "unknown tenant"}


def test_storage_keys_are_not_returned(store):
    result = call(store, "get_subscription", tenant_id="globex")
    assert "pk" not in result and "sk" not in result


# --- tenant isolation inside the Lambda ---------------------------------------

def test_invoices_are_scoped_to_the_tenant(store):
    ids = {i["invoice_id"] for i in call(store, "list_invoices", tenant_id="acme")["invoices"]}
    assert ids == {"INV-A-1007", "INV-A-1008", "INV-A-1009"}


def test_credit_on_another_tenants_invoice_is_not_found(store):
    result = call(store, "request_credit", tenant_id="acme", invoice_id="INV-G-2041",
                  amount=10, reason="Trying to credit a Globex invoice from Acme")
    assert result == {"error": "invoice INV-G-2041 not found"}


def test_ticket_is_written_under_the_callers_tenant(store):
    result = call(store, "create_ticket", tenant_id="globex", subject="Cannot export Gantt chart",
                  description="Export button spins forever on every project.")
    assert ("TENANT#globex", f"TICKET#{result['ticket_id']}") in store.items


# --- tool behavior ------------------------------------------------------------

def test_usage_defaults_to_latest_month(store):
    assert call(store, "get_usage", tenant_id="acme")["month"] == "2026-09"


def test_usage_for_specific_month(store):
    assert call(store, "get_usage", tenant_id="acme", month="2026-08")["api_calls"] == 812000


def test_usage_rejects_bad_month(store):
    assert "YYYY-MM" in call(store, "get_usage", tenant_id="acme", month="September")["error"]


def test_list_invoices_filters_by_status(store):
    result = call(store, "list_invoices", tenant_id="globex", status="past_due")
    assert [i["invoice_id"] for i in result["invoices"]] == ["INV-G-2041"]


def test_ticket_requires_valid_priority(store):
    result = call(store, "create_ticket", tenant_id="acme", subject="Slow dashboards",
                  description="Dashboards take 30s to load.", priority="urgent!!")
    assert "priority" in result["error"]


@pytest.mark.parametrize("amount", [0, -5, 12.5, "20", True])
def test_credit_amount_must_be_positive_integer(store, amount):
    result = call(store, "request_credit", tenant_id="globex", invoice_id="INV-G-2041",
                  amount=amount, reason="Service outage on Sept 3")
    assert "amount" in result["error"]


def test_credit_requires_a_reason(store):
    result = call(store, "request_credit", tenant_id="globex", invoice_id="INV-G-2041", amount=10)
    assert "reason" in result["error"]


def test_credit_cannot_exceed_invoice(store):
    result = call(store, "request_credit", tenant_id="globex", invoice_id="INV-G-2041",
                  amount=500, reason="Service outage on Sept 3")
    assert result == {"error": "credit cannot exceed the invoice amount"}


def test_valid_credit_is_recorded(store):
    result = call(store, "request_credit", tenant_id="globex", invoice_id="INV-G-2041",
                  amount=20, reason="Service outage on Sept 3")
    assert result["status"] == "applied"
    assert ("TENANT#globex", f"CREDIT#{result['credit_id']}") in store.items


def test_unexpected_errors_do_not_leak_details(store, monkeypatch):
    def boom(*_):
        raise RuntimeError("secret internal detail")

    monkeypatch.setitem(handler.TOOLS, "get_subscription", boom)
    assert call(store, "get_subscription", tenant_id="acme") == {"error": "internal error"}


# --- ops tool -----------------------------------------------------------------

def test_tenant_health_covers_every_tenant_with_aggregates_only(store):
    result = call(store, "get_tenant_health")
    by_id = {t["tenant_id"]: t for t in result["tenants"]}
    assert set(by_id) == {"acme", "globex"}
    assert by_id["acme"]["api_utilization_pct"] == 97        # 968000 / 1000000
    assert by_id["globex"]["account_status"] == "past_due"
    assert by_id["globex"]["storage_utilization_pct"] == 100
    assert "invoices" not in str(result) and "INV-" not in str(result)


def test_tenant_health_ignores_any_tenant_argument(store):
    assert call(store, "get_tenant_health", tenant_id="acme")["count"] == 2
