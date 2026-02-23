#!/usr/bin/env python3
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]

TYPE_MAP = {"object": dict, "array": list, "string": str, "integer": int, "number": (int, float), "boolean": bool}


def validate(instance, schema, path="$"):
    t = schema.get("type")
    if t and not isinstance(instance, TYPE_MAP[t]):
        raise ValueError(f"{path}: expected {t}")
    if t == "object":
        for req in schema.get("required", []):
            if req not in instance:
                raise ValueError(f"{path}: missing required key '{req}'")
        props = schema.get("properties", {})
        additional = schema.get("additionalProperties", True)
        for k, v in instance.items():
            if k in props:
                validate(v, props[k], f"{path}.{k}")
            elif additional is False:
                raise ValueError(f"{path}.{k}: additional property not allowed")
    if t == "array" and "items" in schema:
        for i, item in enumerate(instance):
            validate(item, schema["items"], f"{path}[{i}]")
    if "enum" in schema and instance not in schema["enum"]:
        raise ValueError(f"{path}: value {instance} not in enum")


def main() -> int:
    config_dir = ROOT / "config"
    schemas_dir = ROOT / "schemas"
    errors = []
    for cfg in sorted(config_dir.glob("*.json")):
        schema_path = schemas_dir / f"{cfg.stem}.schema.json"
        if not schema_path.exists():
            continue
        data = json.loads(cfg.read_text(encoding="utf-8"))
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        try:
            validate(data, schema)
            print(f"OK: {cfg.relative_to(ROOT)}")
        except Exception as e:
            errors.append(f"{cfg.relative_to(ROOT)}: {e}")
    if errors:
        print("validate_config failed")
        for e in errors:
            print("-", e)
        return 1
    print("validate_config ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
