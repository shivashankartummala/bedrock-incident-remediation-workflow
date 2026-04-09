Core Components
The system is defined by an AWS SAM template and consists of the following primary parts:

Orchestrator (Step Functions): The central state machine (incident_remediation.asl.json) that manages the logic, retries, and failure paths.

Context Collector (GetContext Lambda): Gathers recent CloudWatch logs and metric statistics (e.g., TargetResponseTime) to provide the AI model with the necessary data to make an informed decision.

Reasoning Engine (Amazon Bedrock): Uses the optimized invokeModel integration to process the incident context and propose a structured remediation plan.

Validator (ValidateAgentOutput Lambda): A critical safety component that uses jsonschema to ensure the model's response is valid JSON and contains only allowed actions, such as an ECS rollback.

Executor (ExecuteRemediation Lambda): Performs the actual update_service call in Amazon ECS to roll back to a previous task definition.

Safety & Escalation: An SNS Topic for manual intervention if the automated system cannot safely resolve the issue, and a DynamoDB Table for idempotency tracking.

Execution Flow
The workflow follows a strict sequence of actions to ensure reliability and safety:

Initialize & Context Gathering: The workflow starts by initializing a self-correction counter. The GetContext Lambda then pulls the last 15 minutes of logs and metrics for the affected ECS service.

AI Analysis (Invoke Bedrock): The gathered context is sent to a Bedrock model (e.g., Claude 3.5 Sonnet). The model is prompted to act as a production remediation agent and must return a JSON response specifying an action_type (restricted to ecs_rollback) and its reasoning.

Structured Validation: The ValidateResponse state invokes a Lambda that checks the model's output against a strict schema. If the output is malformed or proposes an unsupported action, it is flagged as invalid.

Self-Correction Loop (Circuit Breaker): * If the validation fails, the workflow increments a counter.

If the counter is below two, the SelfCorrect state re-prompts Bedrock, explicitly including the validation error to help the model fix its output.

If validation fails twice, the workflow triggers the Circuit Breaker logic, escalating to a human via SNS.

Safe Execution: Once an action is validated as both valid and safe, the ExecuteAction Lambda is called. It checks a DynamoDB table to ensure this specific execution ID has not already performed a rollback, providing idempotency even if the Lambda itself is retried.

Remediation: The Lambda identifies the previous "ACTIVE" task definition for the ECS service and updates the service to use it, triggering a new deployment.

Escalation Path: Any unhandled errors in the Lambdas or unsafe model proposals lead to the ManualInterventionNotification state, which publishes the full incident context to an SNS topic for engineer review.

Resiliency & Security Features
Idempotency: The system uses the Step Functions execution ID as a hash key in DynamoDB. This prevents accidental duplicate rollbacks if the execution environment encounters a timeout or intermittent failure.

Least Privilege: IAM roles are narrowly scoped. For example, the ExecuteRemediation Lambda only has permission to describe and update the specific ECS service and cluster defined in the template.

Deterministic Safety: By wrapping the AI's "probabilistic" reasoning inside a deterministic Step Functions state machine, the system ensures it always "fails closed" and escalates to a human rather than taking unpredictable or infinite actions.