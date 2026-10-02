// tenant-acme members may request a credit for tenant "acme" of at most $50, with a reason. Missing fields are denied.
permit(
  principal is AgentCore::OAuthUser,
  action == AgentCore::Action::"TenantTools___request_credit",
  resource == AgentCore::Gateway::"{{GATEWAY_ARN}}"
)
when {
  principal.hasTag("cognito:groups") &&
  principal.getTag("cognito:groups") like "*\"tenant-acme\"*" &&
  context.input.tenant_id == "acme" &&
  context.input has amount &&
  context.input.amount <= 50 &&
  context.input has reason &&
  context.input.reason != ""
};
