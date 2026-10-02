"""Render account-specific AgentCore config from committed templates.

Inputs (none of these are committed):
  infra/outputs.json                 Cognito and Lambda values from the infra stack
  agentcore/.cli/deployed-state.json Gateway ARN, after the first AgentCore deploy
  the active AWS profile             account ID for aws-targets.json

Outputs (gitignored):
  agentcore/agentcore.json
  agentcore/aws-targets.json
  agentcore/.env.local              ops client ID and secret, stored in the token vault on deploy
  app/OpsInsights/harness.json      after the Gateway exists
  frontend/config.js

Cedar policies live in policies/*.cedar and reference the Gateway ARN, which
only exists after the Gateway is deployed. So the first deploy goes out with
the Gateway but no policy engine; render again and redeploy to attach policies:

  python scripts/render_config.py && agentcore deploy -y      # 1st: gateway, no policies
  python scripts/render_config.py && agentcore deploy -y      # 2nd: policies in ENFORCE
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "agentcore" / "agentcore.template.json"
OUTPUT = ROOT / "agentcore" / "agentcore.json"
TARGETS = ROOT / "agentcore" / "aws-targets.json"
INFRA_OUTPUTS = ROOT / "infra" / "outputs.json"
DEPLOYED_STATE = ROOT / "agentcore" / ".cli" / "deployed-state.json"
POLICY_DIR = ROOT / "policies"
FRONTEND_CONFIG = ROOT / "frontend" / "config.js"
ENV_LOCAL = ROOT / "agentcore" / ".env.local"
HARNESS_DIR = ROOT / "app" / "OpsInsights"
OPS_CREDENTIAL = "ops-gateway-oauth"
OPS_SCOPE = "tenantdesk/ops.read"
GATEWAY_NAME = "tenantdesk-gateway"
RUNTIME_NAME = "SupportAgent"
POLICY_ENGINE = "TenantDeskPolicies"


def infra_outputs() -> dict:
    if not INFRA_OUTPUTS.exists():
        sys.exit("infra/outputs.json not found. Deploy infra/ first (see README).")
    return json.loads(INFRA_OUTPUTS.read_text())["TenantDeskInfra"]


def deployed_resources() -> dict:
    """Resources from the AgentCore CLI's deployed state, or {} before the first deploy."""
    if not DEPLOYED_STATE.exists():
        return {}
    state = json.loads(DEPLOYED_STATE.read_text())
    for target in state.get("targets", {}).values():
        return target.get("resources", {})
    return {}


def deployed_gateway_arn() -> str | None:
    return deployed_resources().get("gateways", {}).get(GATEWAY_NAME, {}).get("gatewayArn")


def deployed_runtime_arn() -> str:
    return deployed_resources().get("runtimes", {}).get(RUNTIME_NAME, {}).get("runtimeArn", "")


def load_policies(gateway_arn: str) -> list[dict]:
    """Each policies/<name>.cedar file becomes one policy. A leading // line is its description."""
    policies = []
    for path in sorted(POLICY_DIR.glob("*.cedar")):
        text = path.read_text()
        first_line = text.splitlines()[0] if text else ""
        description = first_line.removeprefix("//").strip() if first_line.startswith("//") else None
        statement = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("//")).strip()
        statement = statement.replace("{{GATEWAY_ARN}}", gateway_arn)
        if "{{" in statement:
            sys.exit(f"{path.name}: unresolved placeholder")
        policy = {
            "name": path.stem,
            "statement": statement,
            "validationMode": "FAIL_ON_ANY_FINDINGS",
            "enforcementMode": "ACTIVE",
        }
        if description:
            policy["description"] = description
        policies.append(policy)
    return policies


def write_ops_credential(out: dict) -> list[dict]:
    """OAuth client the OpsInsights harness uses to call the Gateway.

    The client secret is read from Cognito and written only to agentcore/.env.local
    (gitignored). The AgentCore CLI stores it in the token vault on deploy.
    """
    client = boto3.client("cognito-idp", region_name=out["Region"]).describe_user_pool_client(
        UserPoolId=out["UserPoolId"], ClientId=out["OpsClientId"])["UserPoolClient"]
    prefix = "AGENTCORE_CREDENTIAL_" + OPS_CREDENTIAL.upper().replace("-", "_")
    ENV_LOCAL.write_text(f"{prefix}_CLIENT_ID={client['ClientId']}\n{prefix}_CLIENT_SECRET={client['ClientSecret']}\n")
    ENV_LOCAL.chmod(0o600)
    return [{
        "authorizerType": "OAuthCredentialProvider",
        "name": OPS_CREDENTIAL,
        "discoveryUrl": out["CognitoDiscoveryUrl"],
        "scopes": [OPS_SCOPE],
        "vendor": "CustomOauth2",
    }]


def write_harness(gateway_arn: str, account: str, region: str) -> None:
    provider_arn = (f"arn:aws:bedrock-agentcore:{region}:{account}:token-vault/default/"
                    f"oauth2credentialprovider/{OPS_CREDENTIAL}")
    text = (HARNESS_DIR / "harness.template.json").read_text()
    text = text.replace("{{GATEWAY_ARN}}", gateway_arn).replace("{{OPS_PROVIDER_ARN}}", provider_arn)
    (HARNESS_DIR / "harness.json").write_text(text)


def render() -> None:
    out = infra_outputs()
    account = boto3.client("sts").get_caller_identity()["Account"]
    values = {
        "COGNITO_DISCOVERY_URL": out["CognitoDiscoveryUrl"],
        "WEB_CLIENT_ID": out["WebClientId"],
        "OPS_CLIENT_ID": out["OpsClientId"],
        "TOOLS_FUNCTION_ARN": out["ToolsFunctionArn"],
    }
    text = TEMPLATE.read_text()
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    config = json.loads(text)
    config["credentials"] = write_ops_credential(out)

    gateway_arn = deployed_gateway_arn()
    gateway = next(g for g in config["agentCoreGateways"] if g["name"] == GATEWAY_NAME)
    engine = next(e for e in config["policyEngines"] if e["name"] == POLICY_ENGINE)
    if gateway_arn:
        engine["policies"] = load_policies(gateway_arn)
        write_harness(gateway_arn, account, out["Region"])
        config["harnesses"] = [{"name": "OpsInsights", "path": "app/OpsInsights"}]
        stage = f"gateway deployed, attaching {len(engine['policies'])} Cedar policies (ENFORCE) and OpsInsights"
    else:
        # First deploy: no Gateway ARN yet, so ship the Gateway without policies or the harness.
        config["policyEngines"] = []
        config["harnesses"] = []
        gateway.pop("policyEngineConfiguration", None)
        stage = "first deploy: gateway without policies; render again after deploying"

    leftover = re.findall(r"\{\{[A-Z_]+\}\}", json.dumps(config))
    if leftover:
        sys.exit(f"unresolved placeholders: {sorted(set(leftover))}")

    OUTPUT.write_text(json.dumps(config, indent=2) + "\n")
    TARGETS.write_text(json.dumps([{
        "name": "default",
        "description": "TenantDesk deployment target",
        "account": account,
        "region": out["Region"],
    }], indent=2) + "\n")
    print(f"Wrote {OUTPUT.relative_to(ROOT)} and {TARGETS.relative_to(ROOT)} ({stage})")

    runtime_arn = deployed_runtime_arn()
    frontend = {
        "region": out["Region"],
        "cognitoDomain": out["HostedUiDomain"],
        "clientId": out["WebClientId"],
        "runtimeArn": runtime_arn,
    }
    FRONTEND_CONFIG.write_text(
        "// Generated by scripts/render_config.py. Do not commit.\n"
        f"export default {json.dumps(frontend, indent=2)};\n"
    )
    note = "" if runtime_arn else " (no runtime ARN yet; render again after deploying the agent)"
    print(f"Wrote {FRONTEND_CONFIG.relative_to(ROOT)}{note}")


if __name__ == "__main__":
    render()
