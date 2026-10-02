#!/usr/bin/env python3
import os

import aws_cdk as cdk

from tenantdesk_infra.stack import TenantDeskInfraStack

app = cdk.App()
TenantDeskInfraStack(
    app, "TenantDeskInfra",
    # Where the frontend runs; Cognito only redirects here after sign-in.
    callback_url=app.node.try_get_context("callbackUrl") or "http://localhost:8080/",
    env=cdk.Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region=os.environ.get("CDK_DEFAULT_REGION", "us-east-1"),
    ),
)
cdk.Tags.of(app).add("project", "tenantdesk")
app.synth()
