# IAM Least Privilege Notes

This project keeps permissions intentionally narrow:

## Step Functions state machine role

- `lambda:InvokeFunction` on:
  - `GetContextFunction`
  - `ValidateAgentOutputFunction`
  - `ExecuteRemediationFunction`
- `bedrock:InvokeModel` only for the selected model ARN
- `sns:Publish` only for the manual intervention topic

## GetContext Lambda

- `logs:FilterLogEvents`
- `cloudwatch:GetMetricStatistics`

If you know the exact log group ARN and metric namespace scope at deploy time, replace the wildcard resource with narrower resources.

## ValidateAgentOutput Lambda

- No AWS API permissions required

## ExecuteRemediation Lambda

- `ecs:DescribeServices` for the target ECS service and cluster
- `ecs:UpdateService` for the target ECS service only
- `dynamodb:GetItem`
- `dynamodb:PutItem`
- `dynamodb:UpdateItem`

## Suggested guardrails

- Use a dedicated IAM role for the Step Functions state machine.
- Keep the remediation Lambda limited to a single ECS cluster and service where possible.
- Use CloudTrail and CloudWatch alarms on `ecs:UpdateService`.
- Add a service allowlist inside the remediation Lambda if you later extend the workflow to multiple services.
