import os
from datetime import datetime, timedelta, timezone

import boto3


logs_client = boto3.client("logs")
cloudwatch_client = boto3.client("cloudwatch")


def lambda_handler(event, _context):
    log_group_name = event.get("log_group_name", os.environ["LOG_GROUP_NAME"])
    metric_namespace = event.get("metric_namespace", os.environ["METRIC_NAMESPACE"])
    metric_name = event.get("metric_name", os.environ["METRIC_NAME"])
    ecs_cluster = event.get("ecs_cluster", os.environ["ECS_CLUSTER_NAME"])
    ecs_service = event.get("ecs_service", os.environ["ECS_SERVICE_NAME"])
    lookback_minutes = int(event.get("lookback_minutes", os.environ.get("LOOKBACK_MINUTES", "15")))
    log_limit = int(event.get("log_limit", os.environ.get("LOG_LIMIT", "25")))

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(minutes=lookback_minutes)

    log_events = fetch_logs(log_group_name, start_time, end_time, log_limit)
    metrics = fetch_metrics(metric_namespace, metric_name, start_time, end_time)

    return {
        "incident_type": "application_latency",
        "context_window_minutes": lookback_minutes,
        "resource": {
            "service_type": "ecs",
            "cluster_name": ecs_cluster,
            "service_name": ecs_service,
        },
        "logs": log_events,
        "metrics": metrics,
        "prompt_hints": {
            "allowed_action_types": ["ecs_rollback"],
            "safety_requirements": [
                "Only propose ecs_rollback for the configured ECS service.",
                "Do not suggest deleting infrastructure.",
                "Return valid JSON only.",
            ],
        },
    }


def fetch_logs(log_group_name, start_time, end_time, limit):
    response = logs_client.filter_log_events(
        logGroupName=log_group_name,
        startTime=int(start_time.timestamp() * 1000),
        endTime=int(end_time.timestamp() * 1000),
        limit=limit,
        interleaved=True,
    )

    events = []
    for event in response.get("events", []):
        events.append(
            {
                "timestamp": event["timestamp"],
                "message": event["message"],
            }
        )
    return events


def fetch_metrics(namespace, metric_name, start_time, end_time):
    response = cloudwatch_client.get_metric_statistics(
        Namespace=namespace,
        MetricName=metric_name,
        StartTime=start_time,
        EndTime=end_time,
        Period=60,
        Statistics=["Average", "Maximum"],
    )

    datapoints = sorted(response.get("Datapoints", []), key=lambda item: item["Timestamp"])
    return {
        "namespace": namespace,
        "metric_name": metric_name,
        "datapoints": [
            {
                "timestamp": item["Timestamp"].isoformat(),
                "average": item.get("Average"),
                "maximum": item.get("Maximum"),
                "unit": item.get("Unit"),
            }
            for item in datapoints
        ],
    }
