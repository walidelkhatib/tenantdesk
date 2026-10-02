# Cost per tenant

Every model call the support agent makes is recorded as a `chat` span with the tenant ID (set by
`trace_attributes` in `app/SupportAgent/main.py`) and token counts. Summing those per tenant gives
model cost per customer, which is the number a SaaS business needs to price plans.

## Query

Run in **CloudWatch → Logs Insights** against the SupportAgent runtime log group
(`/aws/bedrock-agentcore/runtimes/<runtime-id>-DEFAULT`). Spans are in the `spans` log stream.

```
fields @timestamp
| filter name = "chat" and ispresent(`attributes.tenant.id`)
| stats count(*) as model_calls,
        sum(`attributes.gen_ai.usage.input_tokens`) as input_tokens,
        sum(`attributes.gen_ai.usage.output_tokens`) as output_tokens,
        count_distinct(`attributes.session.id`) as sessions
  by `attributes.tenant.id` as tenant
| fields input_tokens / 1000000 * 3 + output_tokens / 1000000 * 15 as est_model_cost_usd
| sort est_model_cost_usd desc
```

The cost columns use example rates of **$3 per million input tokens and $15 per million output tokens**.
Replace them with the current Amazon Bedrock price for the model in `app/SupportAgent/model/load.py`.

## What's not included

This covers model tokens, which are usually the largest variable cost. AgentCore Runtime, Memory,
Gateway, Lambda, and DynamoDB charges are billed separately and are not broken down by tenant here.
