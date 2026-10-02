"""Demo data for two fictional customers of "Planwise", a project-management SaaS.

Each tenant's records live under the partition key TENANT#<tenant_id>.
The two tenants differ on purpose (plan, billing state, usage pressure) so the
agent has different, recognizable answers per tenant, which makes any
cross-tenant leak easy to spot in tests and evals.
"""

TENANTS = {
    "acme": {
        "group": "tenant-acme",
        "demo_user": "alex@acme.example",
        "profile": {
            "tenant_id": "acme", "company": "Acme Robotics", "plan": "Business",
            "seats": 50, "seats_used": 47, "status": "active",
            "renewal_date": "2026-12-01", "monthly_price": 1500,
        },
        "usage": [
            {"month": "2026-08", "api_calls": 812000, "api_limit": 1000000,
             "storage_gb": 64, "storage_limit_gb": 100, "active_projects": 38},
            {"month": "2026-09", "api_calls": 968000, "api_limit": 1000000,
             "storage_gb": 71, "storage_limit_gb": 100, "active_projects": 41},
        ],
        "invoices": [
            {"invoice_id": "INV-A-1007", "period": "2026-07", "amount": 1500, "status": "paid", "due_date": "2026-08-01"},
            {"invoice_id": "INV-A-1008", "period": "2026-08", "amount": 1500, "status": "paid", "due_date": "2026-09-01"},
            {"invoice_id": "INV-A-1009", "period": "2026-09", "amount": 1500, "status": "open", "due_date": "2026-10-01"},
        ],
    },
    "globex": {
        "group": "tenant-globex",
        "demo_user": "sam@globex.example",
        "profile": {
            "tenant_id": "globex", "company": "Globex Logistics", "plan": "Starter",
            "seats": 10, "seats_used": 10, "status": "past_due",
            "renewal_date": "2027-03-15", "monthly_price": 120,
        },
        "usage": [
            {"month": "2026-08", "api_calls": 41000, "api_limit": 100000,
             "storage_gb": 9, "storage_limit_gb": 10, "active_projects": 12},
            {"month": "2026-09", "api_calls": 47500, "api_limit": 100000,
             "storage_gb": 10, "storage_limit_gb": 10, "active_projects": 14},
        ],
        "invoices": [
            {"invoice_id": "INV-G-2041", "period": "2026-08", "amount": 120, "status": "past_due", "due_date": "2026-09-01"},
            {"invoice_id": "INV-G-2042", "period": "2026-09", "amount": 120, "status": "open", "due_date": "2026-10-01"},
        ],
    },
}


def items() -> list[dict]:
    """All DynamoDB items for the demo tenants."""
    out = []
    for tenant_id, t in TENANTS.items():
        pk = f"TENANT#{tenant_id}"
        out.append({"pk": pk, "sk": "PROFILE", **t["profile"]})
        out += [{"pk": pk, "sk": f"USAGE#{u['month']}", **u} for u in t["usage"]]
        out += [{"pk": pk, "sk": f"INVOICE#{i['invoice_id']}", **i} for i in t["invoices"]]
    return out
