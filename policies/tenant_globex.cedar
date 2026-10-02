// Members of the tenant-globex group may read their account and open tickets, only for tenant "globex".
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
  principal.getTag("cognito:groups") like "*\"tenant-globex\"*" &&
  context.input.tenant_id == "globex"
};
