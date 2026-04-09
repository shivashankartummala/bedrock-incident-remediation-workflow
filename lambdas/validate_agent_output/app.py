import json
from typing import Any

from jsonschema import Draft202012Validator


ALLOWED_ACTIONS = {"ecs_rollback"}

RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["action_type", "resource_id", "reasoning"],
    "properties": {
        "action_type": {
            "type": "string",
            "enum": sorted(ALLOWED_ACTIONS),
        },
        "resource_id": {
            "type": "string",
            "minLength": 3,
            "maxLength": 512,
        },
        "reasoning": {
            "type": "string",
            "minLength": 10,
            "maxLength": 4000,
        },
        "target_task_definition": {
            "type": "string",
            "minLength": 3,
            "maxLength": 2048,
        },
    },
}

VALIDATOR = Draft202012Validator(RESPONSE_SCHEMA)


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    candidate = event.get("agent_response")

    if isinstance(candidate, str):
        try:
            candidate = json.loads(candidate)
        except json.JSONDecodeError as exc:
            return invalid_response(f"Malformed JSON: {exc.msg}")

    if not isinstance(candidate, dict):
        return invalid_response("Agent response must be a JSON object.")

    errors = sorted(VALIDATOR.iter_errors(candidate), key=lambda err: list(err.path))
    if errors:
        return invalid_response(errors[0].message)

    if candidate["action_type"] not in ALLOWED_ACTIONS:
        return unsafe_response(f"Unsupported remediation action: {candidate['action_type']}")

    return {
        "is_valid": True,
        "is_safe": True,
        "validation_error": None,
        "remediation_action": candidate,
    }


def invalid_response(message: str) -> dict[str, Any]:
    return {
        "is_valid": False,
        "is_safe": False,
        "validation_error": message,
        "remediation_action": None,
    }


def unsafe_response(message: str) -> dict[str, Any]:
    return {
        "is_valid": True,
        "is_safe": False,
        "validation_error": message,
        "remediation_action": None,
    }
