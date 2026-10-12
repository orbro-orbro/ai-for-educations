"""Validate planned cases; never manufacture experiment observations.

Implements only the JSON Schema keywords used by cases.schema.json. Cross-case
uniqueness and identity checks are explicit. Teacher authenticity still requires
the protocol's external roster/review-record audit; syntax cannot prove a person.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re

import yaml


def check_schema(value, schema, path="case"):
    kinds = {"object": lambda v: isinstance(v, dict), "array": lambda v: isinstance(v, list),
             "string": lambda v: isinstance(v, str), "integer": lambda v: type(v) is int,
             "number": lambda v: type(v) in (int, float), "null": lambda v: v is None,
             "boolean": lambda v: type(v) is bool}
    expected = schema.get("type")
    if expected and not any(kinds[k](value) for k in ([expected] if isinstance(expected, str) else expected)):
        raise ValueError(f"{path}: invalid type")
    if "const" in schema and value != schema["const"]: raise ValueError(f"{path}: invalid constant")
    if "enum" in schema and value not in schema["enum"]: raise ValueError(f"{path}: invalid enum")
    if isinstance(value, dict):
        if not set(schema.get("required", [])) <= set(value): raise ValueError(f"{path}: required field missing")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False and set(value) - set(properties): raise ValueError(f"{path}: unknown field")
        if len(value) < schema.get("minProperties", 0): raise ValueError(f"{path}: empty object")
        for key in set(value) & set(properties): check_schema(value[key], properties[key], f"{path}.{key}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0): raise ValueError(f"{path}: not enough items")
        if "maxItems" in schema and len(value) > schema["maxItems"]: raise ValueError(f"{path}: too many items")
        if schema.get("uniqueItems") and len({json.dumps(v, sort_keys=True) for v in value}) != len(value): raise ValueError(f"{path}: repeated items")
        if "items" in schema:
            for i, item in enumerate(value): check_schema(item, schema["items"], f"{path}[{i}]")
        if "contains" in schema:
            found = False
            for item in value:
                try: check_schema(item, schema["contains"], path)
                except ValueError: continue
                found = True
                break
            if not found: raise ValueError(f"{path}: required evidence absent")
    if isinstance(value, str):
        if len(value.strip()) < schema.get("minLength", 0): raise ValueError(f"{path}: empty or too short")
        if "pattern" in schema and not re.search(schema["pattern"], value): raise ValueError(f"{path}: invalid pattern")
        if schema.get("format") == "date-time":
            try: stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as error: raise ValueError(f"{path}: invalid timestamp") from error
            if stamp.tzinfo is None or "T" not in value: raise ValueError(f"{path}: timezone required")
    if type(value) in (int, float):
        if "minimum" in schema and value < schema["minimum"]: raise ValueError(f"{path}: below minimum")
        if "maximum" in schema and value > schema["maximum"]: raise ValueError(f"{path}: above maximum")
    for rule in schema.get("allOf", []): check_schema(value, rule, path)
    if "if" in schema:
        try: check_schema(value, schema["if"], path)
        except ValueError: check_schema(value, schema.get("else", {}), path)
        else: check_schema(value, schema.get("then", {}), path)


def check_identity(value):
    forbidden = {"real_name", "student_name", "student_number", "student_id", "student_email", "email", "phone", "mobile", "id_card"}
    if isinstance(value, dict):
        if forbidden & {str(k).casefold() for k in value}: raise ValueError("Student identity field forbidden")
        for child in value.values(): check_identity(child)
    elif isinstance(value, list):
        for child in value: check_identity(child)
    elif isinstance(value, str):
        if re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|(?<!\d)1[3-9]\d{9}(?!\d)", value):
            raise ValueError("Potential email or mobile identifier forbidden")


def validate_cases(cases, schema):
    if not isinstance(cases, list) or not cases: raise ValueError("Cases must be a nonempty list")
    ids = set()
    for case in cases:
        check_schema(case, schema)
        check_identity(case)
        if case["case_id"] in ids: raise ValueError("Duplicate stable case ID")
        ids.add(case["case_id"])
        annotators = case["teacher_annotators"]
        if len({a["annotator_id"] for a in annotators}) != len(annotators): raise ValueError("Duplicate annotator ID")
        if case["annotation_status"] == "draft" and any(e["status"] == "teacher_verified" for e in case["evidence"]):
            raise ValueError("Draft cannot claim teacher verification")
    return cases


def validate_datasets(directory):
    directory = Path(directory)
    schema = json.loads((directory / "cases.schema.json").read_text(encoding="utf-8"))
    combined, manifest = [], {}
    for name, kind in [("security_cases.yaml", "security"), ("diagnosis_cases.yaml", "diagnosis")]:
        path = directory / name
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        if set(document) != {"dataset_version", "status", "cases"} or not document["dataset_version"]:
            raise ValueError("Dataset manifest malformed")
        cases = validate_cases(document["cases"], schema)
        if any(c["case_type"] != kind for c in cases): raise ValueError("Wrong case type in dataset")
        if kind == "security" and len(cases) < 100: raise ValueError("At least 100 planned security cases required")
        combined += cases
        manifest[name] = {"version": document["dataset_version"], "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                          "cases": len(cases), "draft": sum(c["annotation_status"] == "draft" for c in cases),
                          "verified": sum(c["annotation_status"] == "verified" for c in cases)}
    validate_cases(combined, schema)
    return {"purpose": "structure_and_provenance_validation_only", "experiment_status": "not_executed", "datasets": manifest}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    try: result = validate_datasets(args.directory)
    except (ValueError, OSError, yaml.YAMLError, json.JSONDecodeError) as error:
        parser.exit(1, f"Validation failed: {error}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__": main()
