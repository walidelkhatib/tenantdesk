"""Load demo data and create one demo user per tenant.

Run after deploying infra/ with:
    cd infra && npx aws-cdk@2 deploy --outputs-file outputs.json

Usage:
    AWS_PROFILE=<profile> python scripts/bootstrap_demo.py

Generated passwords are written to .env.demo (gitignored), never printed.
Safe to re-run: data is overwritten, existing users are kept and re-added to
their group.
"""

from __future__ import annotations

import json
import secrets
import string
import sys
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import seed_data  # noqa: E402

OUTPUTS_FILE = ROOT / "infra" / "outputs.json"
CREDENTIALS_FILE = ROOT / ".env.demo"


def load_outputs() -> dict:
    if not OUTPUTS_FILE.exists():
        sys.exit(f"{OUTPUTS_FILE} not found. Deploy infra/ with --outputs-file outputs.json first.")
    return json.loads(OUTPUTS_FILE.read_text())["TenantDeskInfra"]


def random_password() -> str:
    # Meets the pool policy: 12+ chars with upper, lower, digit, and symbol.
    alphabet = string.ascii_letters + string.digits
    core = "".join(secrets.choice(alphabet) for _ in range(16))
    return f"{core}a1A!"


def seed_table(table_name: str, region: str) -> int:
    table = boto3.resource("dynamodb", region_name=region).Table(table_name)
    rows = seed_data.items()
    with table.batch_writer() as batch:
        for row in rows:
            batch.put_item(Item=row)
    return len(rows)


def ensure_user(cognito, pool_id: str, email: str, group: str) -> str | None:
    """Create the user if missing. Returns a new password, or None if the user existed."""
    password = None
    try:
        cognito.admin_get_user(UserPoolId=pool_id, Username=email)
    except cognito.exceptions.UserNotFoundException:
        password = random_password()
        cognito.admin_create_user(
            UserPoolId=pool_id, Username=email, MessageAction="SUPPRESS",
            UserAttributes=[{"Name": "email", "Value": email}, {"Name": "email_verified", "Value": "true"}],
        )
        cognito.admin_set_user_password(UserPoolId=pool_id, Username=email, Password=password, Permanent=True)
    cognito.admin_add_user_to_group(UserPoolId=pool_id, Username=email, GroupName=group)
    return password


def main() -> None:
    out = load_outputs()
    region = out["Region"]
    print(f"Seeded {seed_table(out['TableName'], region)} items into {out['TableName']}")

    cognito = boto3.client("cognito-idp", region_name=region)
    new_creds = {}
    for tenant_id, tenant in seed_data.TENANTS.items():
        password = ensure_user(cognito, out["UserPoolId"], tenant["demo_user"], tenant["group"])
        state = "created" if password else "already existed"
        print(f"User {tenant['demo_user']} ({tenant['group']}): {state}")
        if password:
            new_creds[tenant_id] = (tenant["demo_user"], password)

    if new_creds:
        lines = [f"# Demo user credentials for TenantDesk. Do not commit.\n"]
        for tenant_id, (email, password) in new_creds.items():
            key = tenant_id.upper()
            lines.append(f"DEMO_{key}_USER={email}\nDEMO_{key}_PASSWORD={password}\n")
        with CREDENTIALS_FILE.open("a") as f:
            f.writelines(lines)
        CREDENTIALS_FILE.chmod(0o600)
        print(f"New passwords written to {CREDENTIALS_FILE.relative_to(ROOT)} (gitignored)")


if __name__ == "__main__":
    main()
