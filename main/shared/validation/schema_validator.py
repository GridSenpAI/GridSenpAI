from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


class SchemaValidationError(Exception):
    """
    Raised when payload validation fails against a JSON schema.
    """

    def __init__(self, message: str, errors: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.errors = errors or []


def _read_json_file(schema_path: Path) -> dict[str, Any]:
    if not schema_path.exists():
        raise FileNotFoundError(f"Schema file not found: {schema_path}")

    with schema_path.open("r", encoding="utf-8") as file:
        return json.load(file)


def _format_error_path(error_path: Any) -> str:
    parts = [str(part) for part in list(error_path)]
    return ".".join(parts) if parts else "<root>"


def load_schema(schema_path: str | Path) -> dict[str, Any]:
    """
    Load a JSON schema from disk.
    """
    return _read_json_file(Path(schema_path))


def validate_payload(
    payload: dict[str, Any],
    schema_path: str | Path,
) -> tuple[bool, list[dict[str, Any]]]:
    """
    Validate a payload against a schema file.

    Returns:
        (is_valid, errors)
    """

    schema = load_schema(schema_path)
    validator = Draft202012Validator(schema)

    raw_errors = sorted(validator.iter_errors(payload), key=lambda err: list(err.path))

    errors: list[dict[str, Any]] = []
    for error in raw_errors:
        errors.append(
            {
                "path": _format_error_path(error.path),
                "message": error.message,
                "validator": error.validator,
                "validator_value": error.validator_value,
            }
        )

    return len(errors) == 0, errors


def validate_or_raise(
    payload: dict[str, Any],
    schema_path: str | Path,
    payload_name: str = "payload",
) -> None:
    """
    Validate a payload and raise SchemaValidationError if invalid.
    """

    is_valid, errors = validate_payload(payload, schema_path)

    if not is_valid:
        raise SchemaValidationError(
            message=f"{payload_name} failed schema validation against {schema_path}",
            errors=errors,
        )