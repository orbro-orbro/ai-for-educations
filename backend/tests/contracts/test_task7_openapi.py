from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "contracts/openapi.yaml"

TASK7_OPERATIONS = {
    ("/me/memory-proposals", "get"): "listMyMemoryProposals",
    ("/memory-proposals/{proposal_id}/accept", "post"): "acceptMemoryProposal",
    ("/memory-proposals/{proposal_id}/reject", "post"): "rejectMemoryProposal",
    ("/memory-proposals/{proposal_id}", "patch"): "correctMemoryProposal",
    ("/me/memories", "get"): "listMyLearningMemories",
    ("/memories/{memory_id}", "patch"): "correctLearningMemory",
    ("/memories/{memory_id}", "delete"): "deleteLearningMemory",
    ("/memory-deletions/{deletion_id}", "get"): "getMemoryDeletion",
    ("/memory-deletions/{deletion_id}/retry", "post"): "retryMemoryDeletion",
    ("/diagnoses/{diagnosis_id}/share-grants", "post"): "createDiagnosisShareGrant",
    ("/me/share-grants", "get"): "listMyShareGrants",
    ("/share-grants/{grant_id}", "get"): "getShareGrant",
    ("/share-grants/{grant_id}", "delete"): "revokeShareGrant",
    ("/share-grants/{grant_id}/diagnosis-summary", "get"): "getSharedDiagnosisSummary",
}

TASK7_MUTATIONS = {
    key
    for key in TASK7_OPERATIONS
    if key[1] in {"post", "patch", "delete"}
}

LEGACY_PATHS = {
    "/auth/login",
    "/courses",
    "/courses/{course_id}/enrollments",
    "/courses/{course_id}/exercises",
    "/diagnoses/{diagnosis_id}/explanation-check",
    "/diagnoses/{diagnosis_id}/hints/next",
    "/exercises/{exercise_id}/submissions",
    "/health",
    "/submissions/{submission_id}",
    "/submissions/{submission_id}/diagnosis",
    "/submissions/{submission_id}/execution-result",
    "/teacher/courses",
    "/teacher/courses/{course_id}/concept-edges",
    "/teacher/courses/{course_id}/concepts",
    "/teacher/courses/{course_id}/concepts/{concept_id}",
    "/teacher/courses/{course_id}/concepts/{concept_id}/review",
    "/teacher/courses/{course_id}/misconceptions",
    "/teacher/courses/{course_id}/misconceptions/{misconception_id}",
    "/teacher/courses/{course_id}/misconceptions/{misconception_id}/review",
}

LEGACY_SCHEMAS = {
    "Actor",
    "ApprovedKnowledgeEvidence",
    "CommandSummary",
    "CompilerDiagnostic",
    "CompilerDiagnosticEvidence",
    "Concept",
    "ConceptCreate",
    "ConceptEdge",
    "ConceptUpdate",
    "CourseSummary",
    "CreateCourseRequest",
    "Diagnosis",
    "DiagnosisLocation",
    "EdgeType",
    "Enrollment",
    "ErrorResponse",
    "EvidenceBinding",
    "ExecutionResult",
    "ExerciseSummary",
    "ExplanationCheck",
    "ExplanationCheckRequest",
    "HealthResponse",
    "HintEvent",
    "HintStep",
    "KnowledgeId",
    "LoginRequest",
    "LoginResponse",
    "MisconceptionCreate",
    "MisconceptionPattern",
    "MisconceptionUpdate",
    "NextHintRequest",
    "ReviewDecision",
    "ReviewStatus",
    "Role",
    "RuleMatch",
    "RuleMatchEvidence",
    "RunnerLimits",
    "SourceFileInput",
    "SourceMetadata",
    "Submission",
    "SubmissionCreateRequest",
    "SubmissionStatus",
    "ToolchainInfo",
    "Topic",
    "TriggerEvidence",
    "Verification",
}

LEGACY_RESPONSES = {
    "AuthenticationFailed",
    "Conflict",
    "DiagnosticConflict",
    "DiagnosticUnavailable",
    "Invalid",
    "InvalidRequest",
    "NotAvailable",
    "PersistenceUnavailable",
    "SubmissionConflict",
}


def _document():
    return yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))


def _operation_ids(document):
    return [
        operation["operationId"]
        for item in document["paths"].values()
        for method, operation in item.items()
        if method in {"get", "post", "put", "patch", "delete"}
    ]


def test_task7_paths_are_merged_without_reducing_existing_contract():
    document = _document()
    assert LEGACY_PATHS <= set(document["paths"])
    assert LEGACY_SCHEMAS <= set(document["components"]["schemas"])
    assert LEGACY_RESPONSES <= set(document["components"]["responses"])

    for (path, method), operation_id in TASK7_OPERATIONS.items():
        operation = document["paths"][path][method]
        assert operation["operationId"] == operation_id
        assert operation["security"] == [{"bearerAuth": []}]
        assert {"401", "404", "503"} <= set(operation["responses"])

    operation_ids = _operation_ids(document)
    assert len(operation_ids) == len(set(operation_ids))


def test_task7_mutations_require_scoped_idempotency_and_stable_errors():
    document = _document()
    parameter = document["components"]["parameters"]["IdempotencyKey"]
    assert parameter == {
        "name": "Idempotency-Key",
        "in": "header",
        "required": True,
        "schema": {"type": "string", "minLength": 1, "maxLength": 128},
    }

    for path, method in TASK7_MUTATIONS:
        operation = document["paths"][path][method]
        assert {"401", "404", "409", "422", "503"} <= set(
            operation["responses"]
        )
        assert "#/components/parameters/IdempotencyKey" in {
            item["$ref"] for item in operation["parameters"]
        }


def test_task7_request_and_response_field_directions_are_explicit():
    schemas = _document()["components"]["schemas"]

    for name in (
        "ProposalCorrectionRequest",
        "MemoryCorrectionRequest",
        "ShareGrantCreateRequest",
    ):
        schema = schemas[name]
        assert schema["additionalProperties"] is False
        assert all(value.get("writeOnly") is True for value in schema["properties"].values())

    expected_read_only = {
        "MemoryProposal": {
            "proposal_id",
            "root_proposal_id",
            "previous_proposal_id",
            "version",
            "owner_user_id",
            "course_id",
            "diagnosis_id",
            "explanation_check_id",
            "status",
            "created_at",
            "expires_at",
            "request_id",
        },
        "LearningMemory": {
            "memory_id",
            "logical_memory_id",
            "previous_version_id",
            "version",
            "owner_user_id",
            "course_id",
            "source_diagnosis_id",
            "status",
            "created_at",
            "updated_at",
            "request_id",
        },
        "ShareGrant": {
            "grant_id",
            "owner_user_id",
            "course_id",
            "resource_type",
            "resource_id",
            "status",
            "created_at",
            "revoked_at",
            "request_id",
        },
        "DeletionReceipt": set(schemas["DeletionReceipt"]["properties"]),
    }
    for name, fields in expected_read_only.items():
        assert all(
            schemas[name]["properties"][field].get("readOnly") is True
            for field in fields
        )


def test_deletion_receipt_cannot_expose_private_or_internal_material():
    properties = set(_document()["components"]["schemas"]["DeletionReceipt"]["properties"])
    forbidden = {
        "content",
        "memory_content",
        "proposal_content",
        "conversation",
        "source_code",
        "explanation",
        "prompt",
        "model_response",
        "vector",
        "embedding",
        "content_hash",
        "access_token",
        "api_key",
        "index_key",
        "stack_trace",
        "provider_request_id",
    }
    assert properties == {
        "deletion_id",
        "memory_id",
        "owner_user_id",
        "course_id",
        "status",
        "requested_at",
        "completed_at",
        "attempts",
        "index_cleared",
        "cache_cleared",
        "model_references_cleared",
        "reverse_lookup_absent",
        "error_code",
        "request_id",
    }
    assert forbidden.isdisjoint(properties)
