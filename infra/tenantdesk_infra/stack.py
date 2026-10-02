"""Shared infrastructure that the AgentCore CLI does not create for us.

- Cognito user pool: who the user is (`sub`) and which tenant they belong to
  (a `tenant-<id>` group, sent in the access token's `cognito:groups` claim).
- DynamoDB table: tenant data, partitioned by tenant.
- Tools Lambda: the Gateway target that serves all five support tools.

Everything AgentCore-specific (runtime, memory, gateway, policies) is declared
in agentcore/agentcore.json and deployed by the AgentCore CLI.
"""

from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
    aws_cognito as cognito,
    aws_dynamodb as dynamodb,
    aws_lambda as _lambda,
    aws_logs as logs,
)
from constructs import Construct

TENANT_GROUPS = ["tenant-acme", "tenant-globex"]


class TenantDeskInfraStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, callback_url: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # --- Data ------------------------------------------------------------
        table = dynamodb.Table(
            self, "DataTable",
            partition_key=dynamodb.Attribute(name="pk", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="sk", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            encryption=dynamodb.TableEncryption.AWS_MANAGED,
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=True
            ),
            removal_policy=RemovalPolicy.DESTROY,  # demo project: tear down cleanly
        )

        # --- Identity --------------------------------------------------------
        user_pool = cognito.UserPool(
            self, "UserPool",
            feature_plan=cognito.FeaturePlan.LITE,
            self_sign_up_enabled=False,  # admins create users; nobody can sign themselves in
            sign_in_aliases=cognito.SignInAliases(email=True),
            account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
            password_policy=cognito.PasswordPolicy(
                min_length=12, require_digits=True, require_lowercase=True,
                require_uppercase=True, require_symbols=True,
            ),
            removal_policy=RemovalPolicy.DESTROY,
        )

        for group in TENANT_GROUPS:
            cognito.CfnUserPoolGroup(
                self, f"Group-{group}",
                user_pool_id=user_pool.user_pool_id,
                group_name=group,
                description=f"Members of tenant '{group.removeprefix('tenant-')}'",
            )

        domain = user_pool.add_domain(
            "HostedUiDomain",
            cognito_domain=cognito.CognitoDomainOptions(domain_prefix=f"tenantdesk-{self.account}"),
        )

        # Public browser client: authorization code + PKCE, no secret.
        # ADMIN_USER_PASSWORD_AUTH is enabled only so the test suite can get
        # tokens; that flow needs IAM credentials, so it is not usable from a browser.
        web_client = user_pool.add_client(
            "WebClient",
            generate_secret=False,
            auth_flows=cognito.AuthFlow(admin_user_password=True),
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(authorization_code_grant=True),
                scopes=[cognito.OAuthScope.OPENID, cognito.OAuthScope.EMAIL, cognito.OAuthScope.PROFILE],
                callback_urls=[callback_url],
                logout_urls=[callback_url],
            ),
            prevent_user_existence_errors=True,
            access_token_validity=Duration.hours(1),
            id_token_validity=Duration.hours(1),
            refresh_token_validity=Duration.days(1),
        )

        # Machine client for the internal OpsInsights harness. It signs in as itself
        # (client credentials) and only gets the ops.read scope, which Cedar maps
        # to the aggregate ops tool. It has no tenant group, so customer tools stay denied.
        ops_scope = cognito.ResourceServerScope(scope_name="ops.read", scope_description="Read aggregate tenant health")
        resource_server = user_pool.add_resource_server(
            "TenantDeskApi", identifier="tenantdesk", scopes=[ops_scope],
        )
        ops_client = user_pool.add_client(
            "OpsClient",
            generate_secret=True,
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(client_credentials=True),
                scopes=[cognito.OAuthScope.resource_server(resource_server, ops_scope)],
            ),
            access_token_validity=Duration.hours(1),
        )

        # --- Tools Lambda ----------------------------------------------------
        tools_fn = _lambda.Function(
            self, "ToolsFunction",
            runtime=_lambda.Runtime.PYTHON_3_13,
            architecture=_lambda.Architecture.ARM_64,
            handler="handler.handler",
            code=_lambda.Code.from_asset("../tools", exclude=["seed_data.py", "tool_schema.json", "__pycache__"]),
            timeout=Duration.seconds(10),
            memory_size=256,
            environment={"TABLE_NAME": table.table_name},
            log_group=logs.LogGroup(
                self, "ToolsLogGroup",
                retention=logs.RetentionDays.ONE_MONTH,
                removal_policy=RemovalPolicy.DESTROY,
            ),
        )
        table.grant_read_write_data(tools_fn)

        # --- Outputs (consumed by scripts/render_config.py) -------------------
        discovery_url = (
            f"https://cognito-idp.{self.region}.amazonaws.com/{user_pool.user_pool_id}"
            "/.well-known/openid-configuration"
        )
        CfnOutput(self, "UserPoolId", value=user_pool.user_pool_id)
        CfnOutput(self, "WebClientId", value=web_client.user_pool_client_id)
        CfnOutput(self, "OpsClientId", value=ops_client.user_pool_client_id)
        CfnOutput(self, "CognitoDiscoveryUrl", value=discovery_url)
        CfnOutput(self, "HostedUiDomain", value=domain.base_url())
        CfnOutput(self, "ToolsFunctionArn", value=tools_fn.function_arn)
        CfnOutput(self, "TableName", value=table.table_name)
        CfnOutput(self, "Region", value=self.region)
