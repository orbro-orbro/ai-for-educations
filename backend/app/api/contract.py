"""Shared public error and authentication declarations; policy stays in services."""
from fastapi.openapi.utils import get_openapi
from fastapi.security import HTTPBearer
from app.api.errors import ErrorResponse

BEARER = HTTPBearer(auto_error=False, scheme_name="bearerAuth", bearerFormat="JWT")

def errors(*statuses):
    return {status: {"model": ErrorResponse} for status in statuses}

def install_generated_openapi(application):
    def generated():
        if application.openapi_schema is None:
            document = get_openapi(title=application.title, version=application.version, routes=application.routes)
            # FastAPI infers a validation response even for an unconstrained
            # string path. Such a parameter cannot fail Pydantic validation.
            # Keep explicit envelopes and every bounded/body validation response.
            for item in document["paths"].values():
                for operation in item.values():
                    if not isinstance(operation, dict) or "responses" not in operation:
                        continue
                    response = operation["responses"].get("422", {})
                    schema = response.get("content", {}).get("application/json", {}).get("schema", {})
                    plain_strings = all(
                        set(p.get("schema", {})) <= {"type", "title"}
                        and p.get("schema", {}).get("type") == "string"
                        for p in operation.get("parameters", [])
                    )
                    if schema.get("$ref", "").endswith("/HTTPValidationError") and "requestBody" not in operation and plain_strings:
                        del operation["responses"]["422"]
            application.openapi_schema = document
        return application.openapi_schema
    application.openapi = generated
