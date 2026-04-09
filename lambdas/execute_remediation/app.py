import hashlib
import os
from datetime import datetime, timezone
from typing import Any

import boto3
from botocore.exceptions import ClientError


ecs_client = boto3.client("ecs")
dynamodb = boto3.resource("dynamodb")
IDEMPOTENCY_TABLE = dynamodb.Table(os.environ["IDEMPOTENCY_TABLE_NAME"])


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    action = event["remediation_action"]
    execution_id = event["execution_id"]
    cluster_name = event.get("ecs_cluster", os.environ["ECS_CLUSTER_NAME"])
    service_name = event.get("ecs_service", os.environ["ECS_SERVICE_NAME"])

    if action["action_type"] != "ecs_rollback":
        raise ValueError(f"Unsafe remediation action requested: {action['action_type']}")

    idempotency_token = stable_token(execution_id)

    record = claim_execution(execution_id, idempotency_token, action)
    if record.get("Status") == "COMPLETED":
        return {
            "status": "SKIPPED_ALREADY_EXECUTED",
            "execution_id": execution_id,
            "idempotency_token": idempotency_token,
            "service": record.get("ServiceName", service_name),
        }
    if record.get("Status") == "IN_PROGRESS":
        return {
            "status": "SKIPPED_IN_PROGRESS",
            "execution_id": execution_id,
            "idempotency_token": idempotency_token,
            "service": record.get("ServiceName", service_name),
        }

    target_task_definition = action.get("target_task_definition")
    if not target_task_definition:
        target_task_definition = resolve_previous_task_definition(cluster_name, service_name)

    response = ecs_client.update_service(
        cluster=cluster_name,
        service=service_name,
        taskDefinition=target_task_definition,
        forceNewDeployment=True,
    )

    # Idempotency is enforced outside ECS because update_service does not expose
    # a client token. We record the Step Functions execution ID before the call
    # and mark it completed only after a successful rollback.
    complete_execution(execution_id, idempotency_token, cluster_name, service_name, target_task_definition)

    return {
        "status": "ROLLBACK_TRIGGERED",
        "execution_id": execution_id,
        "idempotency_token": idempotency_token,
        "cluster": cluster_name,
        "service": service_name,
        "target_task_definition": target_task_definition,
        "deployment_id": response["service"]["deployments"][0]["id"],
    }


def stable_token(execution_id: str) -> str:
    return hashlib.sha256(execution_id.encode("utf-8")).hexdigest()


def claim_execution(execution_id: str, idempotency_token: str, action: dict[str, Any]) -> dict[str, Any]:
    item = {
        "ExecutionId": execution_id,
        "IdempotencyToken": idempotency_token,
        "ActionType": action["action_type"],
        "Status": "IN_PROGRESS",
        "CreatedAt": datetime.now(timezone.utc).isoformat(),
        "TtlEpoch": int(datetime.now(timezone.utc).timestamp()) + 86400,
    }

    try:
        IDEMPOTENCY_TABLE.put_item(
            Item=item,
            ConditionExpression="attribute_not_exists(ExecutionId)",
        )
        return {}
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise

        return IDEMPOTENCY_TABLE.get_item(Key={"ExecutionId": execution_id}).get("Item", {})


def complete_execution(
    execution_id: str,
    idempotency_token: str,
    cluster_name: str,
    service_name: str,
    target_task_definition: str,
) -> None:
    IDEMPOTENCY_TABLE.update_item(
        Key={"ExecutionId": execution_id},
        UpdateExpression=(
            "SET IdempotencyToken = :token, "
            "#status = :status, "
            "ClusterName = :cluster, "
            "ServiceName = :service, "
            "TargetTaskDefinition = :taskdef, "
            "CompletedAt = :completed"
        ),
        ExpressionAttributeNames={"#status": "Status"},
        ExpressionAttributeValues={
            ":token": idempotency_token,
            ":status": "COMPLETED",
            ":cluster": cluster_name,
            ":service": service_name,
            ":taskdef": target_task_definition,
            ":completed": datetime.now(timezone.utc).isoformat(),
        },
    )


def resolve_previous_task_definition(cluster_name: str, service_name: str) -> str:
    response = ecs_client.describe_services(cluster=cluster_name, services=[service_name])
    services = response.get("services", [])
    if not services:
        raise ValueError(f"ECS service not found: {cluster_name}/{service_name}")

    deployments = services[0].get("deployments", [])
    active = [item for item in deployments if item["status"] == "PRIMARY"]
    previous = [item for item in deployments if item["status"] == "ACTIVE"]

    if previous:
        return previous[0]["taskDefinition"]
    if active:
        return active[0]["taskDefinition"]

    raise ValueError("Unable to resolve a rollback target task definition.")
