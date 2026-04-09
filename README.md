# Bedrock Incident Remediation Workflow

This repository contains a production-oriented incident-remediation workflow for application latency using AWS Step Functions, Amazon Bedrock model inference, and AWS Lambda.

## What is included

- An AWS Step Functions state machine in Amazon States Language
- A context collection Lambda for CloudWatch logs and metrics
- A validation Lambda that enforces structured model output with `jsonschema`
- An execution Lambda that performs ECS remediation with explicit idempotency tracking
- An AWS SAM template that wires the components together
- IAM guidance with least-privilege policy suggestions

## Important design note

The workflow uses the Step Functions optimized Bedrock integration:

- `arn:aws:states:::bedrock:invokeModel`

That is the integration modeled in the state machine. If you later need a strict Amazon Bedrock Agent `InvokeAgent` call, wrap that API in Lambda and swap the `InvokeBedrockAgent` task to a Lambda invocation. The rest of the workflow stays the same.

## Deployment

1. Update the parameter defaults or provide stack parameters for:
   - ECS cluster and service names
   - Bedrock model ID
   - CloudWatch log group
   - CloudWatch metric namespace/name
   - SNS email endpoint
2. Build and deploy:

```bash
sam build
sam deploy --guided
```

## State machine behavior

1. `GetContext` gathers recent CloudWatch signals.
2. `InvokeBedrockAgent` sends the incident context to Bedrock using the optimized integration.
3. `ValidateResponse` checks the model output against a strict schema.
4. `SelfCorrect` re-prompts the model with the validation error if the output is malformed.
5. `ExecuteAction` performs a controlled ECS rollback when the action is valid and safe.
6. Failures or unsafe proposals go to SNS for manual intervention.

## Idempotency

The remediation Lambda uses a DynamoDB table keyed by the Step Functions execution ID. That makes the rollback operation safe to retry because the same execution can only record one successful remediation action.

## Circuit breaker

The state machine uses a bounded self-correction loop with a maximum of two retries. That acts as a circuit breaker for malformed model output so the workflow fails closed and escalates to humans instead of looping indefinitely.
