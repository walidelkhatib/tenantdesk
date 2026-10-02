// The internal ops client (scope tenantdesk/ops.read) may read aggregate tenant health. Customers never can.
permit(
  principal is AgentCore::OAuthUser,
  action == AgentCore::Action::"TenantTools___get_tenant_health",
  resource == AgentCore::Gateway::"{{GATEWAY_ARN}}"
)
when {
  principal.hasTag("scope") &&
  principal.getTag("scope") like "*tenantdesk/ops.read*" &&
  !(principal.hasTag("cognito:groups"))
};
