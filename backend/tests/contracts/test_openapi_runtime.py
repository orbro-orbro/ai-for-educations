from __future__ import annotations

from pathlib import Path

import yaml
from fastapi import FastAPI

from app.api.memories import create_memories_router
from app.main import create_app


ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "contracts/openapi.yaml"


def _document():
    return yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))


def _operations(document):
    for path, item in document["paths"].items():
        for method, operation in item.items():
            if method.lower() in {"get", "post", "put", "patch", "delete"}:
                yield path, method.lower(), operation


def _without_generated_titles(value):
    if isinstance(value, dict):
        return {
            key: _without_generated_titles(item)
            for key, item in value.items()
            if key != "title"
        }
    if isinstance(value, list):
        return [_without_generated_titles(item) for item in value]
    return value


def test_contract_contains_every_runtime_route_and_unique_operation_ids():
    document = _document()
    contract_operations = {(path, method) for path, method, _ in _operations(document)}
    runtime = create_app().openapi()
    assert runtime["info"]["version"] == document["info"]["version"]
    runtime_operations = {(path, method) for path, item in runtime["paths"].items() for method in item if method != "parameters"}
    assert runtime_operations <= contract_operations
    operation_ids = [operation["operationId"] for _, _, operation in _operations(document)]
    assert len(operation_ids) == len(set(operation_ids))


def test_all_local_references_resolve():
    document = _document()

    def walk(value):
        if isinstance(value, dict):
            reference = value.get("$ref")
            if reference:
                assert reference.startswith("#/components/")
                target = document
                for part in reference[2:].split("/"):
                    assert part in target, reference
                    target = target[part]
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(document)


def test_every_protected_operation_declares_bearer_and_authentication_error():
    document = _document()
    for path, _method, operation in _operations(document):
        if path in {"/health", "/auth/login"}:
            continue
        assert operation.get("security") == [{"bearerAuth": []}], path
        assert "401" in operation["responses"], path


def test_all_request_objects_forbid_unknown_properties():
    document = _document()
    for name, schema in document["components"]["schemas"].items():
        if name.endswith(("Request", "Create", "Update", "Decision")):
            assert schema.get("additionalProperties") is False, name


def test_task5_paths_and_bounded_identifiers_are_in_shared_contract():
    document = _document()

    for path in (
        "/exercises/{exercise_id}/submissions",
        "/submissions/{submission_id}",
        "/submissions/{submission_id}/execution-result",
    ):
        assert path in document["paths"]
    assert document["components"]["parameters"]["ExerciseId"]["schema"]["maxLength"] == 128
    assert document["components"]["parameters"]["SubmissionId"]["schema"]["maxLength"] == 128
    assert document["components"]["schemas"]["SubmissionCreateRequest"]["additionalProperties"] is False


def test_task6_runtime_documents_stable_error_statuses() -> None:
    runtime = create_app().openapi()

    for path in (
        "/submissions/{submission_id}/diagnosis",
        "/diagnoses/{diagnosis_id}/hints/next",
        "/diagnoses/{diagnosis_id}/explanation-check",
    ):
        operation = next(iter(runtime["paths"][path].values()))
        assert {"401", "404", "409", "422", "503"} <= set(operation["responses"])


def test_task7_runtime_operations_match_the_shared_contract() -> None:
    shared = _document()
    runtime_app = FastAPI()
    runtime_app.include_router(create_memories_router(object(), object(), object()))
    runtime = runtime_app.openapi()

    for path, path_item in runtime["paths"].items():
        assert path in shared["paths"]
        for method, operation in path_item.items():
            contract = shared["paths"][path][method]
            assert operation["operationId"] == contract["operationId"]
            assert set(operation["responses"]) == set(contract["responses"])
            assert operation.get("security") == contract["security"]

            runtime_parameters = {
                (item["name"], item["in"], item.get("required", False))
                for item in operation.get("parameters", [])
            }
            contract_parameters = set()
            for item in contract.get("parameters", []):
                if "$ref" in item:
                    item = shared["components"]["parameters"][item["$ref"].rsplit("/", 1)[1]]
                contract_parameters.add(
                    (item["name"], item["in"], item.get("required", False))
                )
            assert runtime_parameters == contract_parameters

            if "requestBody" in operation:
                runtime_schema = operation["requestBody"]["content"]["application/json"]["schema"]
                contract_schema = contract["requestBody"]["content"]["application/json"]["schema"]
                assert runtime_schema == contract_schema

            success = "202" if method == "delete" and path == "/memories/{memory_id}" else (
                "201" if path == "/diagnoses/{diagnosis_id}/share-grants" else "200"
            )
            runtime_schema = operation["responses"][success]["content"]["application/json"]["schema"]
            contract_schema = contract["responses"][success]["content"]["application/json"]["schema"]
            assert _without_generated_titles(runtime_schema) == contract_schema

    assert "/teacher/courses/{course_id}/analytics" not in runtime["paths"]
    assert "/teacher/courses/{course_id}/review-queue" not in runtime["paths"]
    assert "/teacher/diagnoses/{diagnosis_id}/review" not in runtime["paths"]
