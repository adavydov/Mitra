#!/usr/bin/env python3
"""Validate config/*.json against schemas/config.schema.json (subset JSON Schema)."""

from __future__ import annotations

import json
import pathlib
import sys
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "schemas" / "config.schema.json"
CONFIG_DIR = ROOT / "config"


class ValidationError(Exception):
    pass


def validate(instance: Any, schema: dict[str, Any], path: str = "$") -> None:
    schema_type = schema.get("type")
    if schema_type == "object":
        if not isinstance(instance, dict):
            raise ValidationError(f"{path}: expected object")
        required = schema.get("required", [])
        for key in required:
            if key not in instance:
                raise ValidationError(f"{path}: missing required key '{key}'")
        properties = schema.get("properties", {})
        additional_allowed = schema.get("additionalProperties", True)
        for key, value in instance.items():
            child_path = f"{path}.{key}"
            if key in properties:
                validate(value, properties[key], child_path)
            elif not additional_allowed:
                raise ValidationError(f"{child_path}: additional properties are not allowed")

    elif schema_type == "array":
        if not isinstance(instance, list):
            raise ValidationError(f"{path}: expected array")
        item_schema = schema.get("items")
        if item_schema:
            for index, item in enumerate(instance):
                validate(item, item_schema, f"{path}[{index}]")

    elif schema_type == "string":
        if not isinstance(instance, str):
            raise ValidationError(f"{path}: expected string")
        enum = schema.get("enum")
        if enum and instance not in enum:
            raise ValidationError(f"{path}: value '{instance}' not in enum {enum}")

    elif schema_type == "number":
        if not isinstance(instance, (int, float)) or isinstance(instance, bool):
            raise ValidationError(f"{path}: expected number")

    elif schema_type == "integer":
        if not isinstance(instance, int) or isinstance(instance, bool):
            raise ValidationError(f"{path}: expected integer")

    elif schema_type == "boolean":
        if not isinstance(instance, bool):
            raise ValidationError(f"{path}: expected boolean")


def main() -> int:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    files = sorted(CONFIG_DIR.glob("*.json"))

    if not files:
        print("No files found in config/*.json; nothing to validate.")
        return 0

    errors: list[str] = []
    for file_path in files:
        try:
            payload = json.loads(file_path.read_text(encoding="utf-8"))
            validate(payload, schema)
            print(f"OK: {file_path.relative_to(ROOT)}")
        except (json.JSONDecodeError, ValidationError) as exc:
            errors.append(f"{file_path.relative_to(ROOT)}: {exc}")

    if errors:
        print("Schema validation failed:")
        for err in errors:
            print(f" - {err}")
        return 1

    print(f"Schema validation passed for {len(files)} file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
