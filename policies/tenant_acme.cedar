// Members of the tenant-acme group may read their account and open tickets, only for tenant "acme".
permit(
  principal is AgentCore::OAuthUser,
  action in [
    AgentCore::Action::"TenantTools___get_subscription",
    AgentCore::Action::"TenantTools___get_usage",
    AgentCore::Action::"TenantTools___list_invoices",
    AgentCore::Action::"TenantTools___create_ticket"
  ],
  resource == AgentCore::Gateway::"{{GATEWAY_ARN}}"
)
when {
  principal.hasTag("cognito:groups") &&
  principal.getTag("cognito:groups") like "*\"tenant-acme\"*" &&
  context.input.tenant_id == "acme"
};
