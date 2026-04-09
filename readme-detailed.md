# Detailed Design Notes

This document expands on the architecture and runtime behavior of the Bedrock incident remediation workflow.

## Core Components

The system is defined by an AWS SAM template and is composed of the following building blocks:

- **Orchestrator (AWS Step Functions)**
  The central state machine in `statemachine/incident_remediation.asl.json` manages control flow, retries, validation routing, and escalation paths.

- **Context Collector (`GetContext` Lambda)**
  The Lambda in `lambdas/get_context/app.py` gathers recent CloudWatch logs and metric statistics, such as `TargetResponseTime`, to provide the model with enough evidence to reason about the incident.

- **Reasoning Engine (Amazon Bedrock)**
  The workflow uses the optimized `invokeModel` Step Functions integration to process incident context and produce a structured remediation recommendation.

- **Validator (`ValidateAgentOutput` Lambda)**
  The Lambda in `lambdas/validate_agent_output/app.py` uses `jsonschema` to verify that the model response is valid JSON and contains only approved fields and actions.

- **Executor (`ExecuteRemediation` Lambda)**
  The Lambda in `lambdas/execute_remediation/app.py` performs the actual ECS remediation by calling `update_service` to roll back the workload to a previous task definition.

- **Safety and Escalation Controls**
  SNS is used for manual intervention notifications when the workflow cannot proceed safely, and DynamoDB is used to track idempotency for remediation attempts.

## Execution Flow

The workflow follows a strict sequence to keep the remediation path safe and deterministic.

### 1. Initialize and Gather Context

The workflow starts by initializing a self-correction counter. It then invokes the `GetContext` Lambda, which retrieves the last 15 minutes of CloudWatch logs and metrics for the affected ECS service.

### 2. Analyze the Incident with Bedrock

The collected context is sent to a Bedrock model, such as Claude 3.5 Sonnet. The prompt instructs the model to behave as a production remediation agent and return JSON only, with an `action_type`, `resource_id`, `reasoning`, and an optional `target_task_definition`.

### 3. Validate the Model Output

The `ValidateResponse` state invokes the validation Lambda, which checks the model output against a strict schema. If the payload is malformed or contains an unsupported action, the workflow marks it as invalid.

### 4. Self-Correction Loop

If validation fails, the workflow increments the self-correction counter and re-prompts Bedrock with the validation error.

- If the retry count is still below the configured limit, the `SelfCorrect` state gives the model another chance to return valid JSON.
- If validation keeps failing after two correction attempts, the workflow trips the circuit breaker behavior and escalates to a human operator through SNS.

### 5. Safe Execution

When the response is both valid and safe, the workflow invokes the `ExecuteAction` Lambda. Before performing the rollback, the Lambda checks DynamoDB to ensure the same Step Functions execution ID has not already triggered the remediation.

### 6. Remediation

The execution Lambda identifies the previous ECS task definition and updates the ECS service to use it, which triggers a new deployment.

### 7. Escalation Path

Any unhandled Lambda exception, Bedrock failure, invalid output exhaustion, or unsafe action proposal is routed to `ManualInterventionNotification`, which publishes the incident payload and failure details to SNS for engineer review.

## Resiliency and Security Features

### Idempotency

The remediation path uses the Step Functions execution ID as the stable idempotency key in DynamoDB. This prevents duplicate rollback actions when Lambda retries happen because of transient failures, timeouts, or partial execution.

### Least Privilege

IAM permissions are narrowly scoped:

- The execution Lambda is limited to describing and updating the intended ECS service and cluster.
- The validation Lambda does not need AWS API permissions.
- The Step Functions role is restricted to invoking only the required Lambdas, Bedrock model, and SNS topic.

### Deterministic Safety

The model is allowed to reason probabilistically, but the workflow is not allowed to act probabilistically.

The state machine wraps the model with deterministic controls:

- strict schema validation
- explicit allowlisting of remediation actions
- a bounded self-correction loop
- a fail-closed escalation path

That combination ensures the workflow escalates to humans instead of taking open-ended or unsafe actions.
