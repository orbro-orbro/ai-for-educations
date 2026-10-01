from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True, slots=True)
class CompilerDiagnostic:
    """Version-independent compiler diagnostic consumed by Task 5."""

    severity: str
    message: str
    code: str | None
    file: str | None
    start_line: int | None
    start_column: int | None
    end_line: int | None
    end_column: int | None


_PLAIN_DIAGNOSTIC = re.compile(
    r"^(?P<file>.+?):(?P<line>\d+):(?P<column>\d+):\s*"
    r"(?P<severity>error|warning|note|info):\s*(?P<message>.+)$",
    re.IGNORECASE,
)
_SEVERITIES = {"error", "warning", "note", "info"}


def parse_compiler_diagnostics(output: str) -> list[CompilerDiagnostic]:
    """Parse cjc JSON diagnostics with a no-color text compatibility fallback."""

    if not output.strip():
        return []

    records = _load_json_records(output)
    diagnostics = [item for record in records for item in _diagnostics_from_json(record)]
    if diagnostics:
        return diagnostics

    parsed: list[CompilerDiagnostic] = []
    for line in output.splitlines():
        match = _PLAIN_DIAGNOSTIC.match(line.strip())
        if match is None:
            continue
        parsed.append(
            CompilerDiagnostic(
                severity=match.group("severity").lower(),
                message=match.group("message").strip(),
                code=None,
                file=match.group("file"),
                start_line=int(match.group("line")),
                start_column=int(match.group("column")),
                end_line=None,
                end_column=None,
            )
        )
    return parsed


def _load_json_records(output: str) -> list[Any]:
    try:
        return [json.loads(output)]
    except json.JSONDecodeError:
        records: list[Any] = []
        for line in output.splitlines():
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return records


def _diagnostics_from_json(value: Any) -> Iterable[CompilerDiagnostic]:
    if isinstance(value, list):
        for item in value:
            yield from _diagnostics_from_json(item)
        return
    if not isinstance(value, dict):
        return

    nested = _get(value, "diagnostics", "Diags")
    if isinstance(nested, (list, dict)):
        yield from _diagnostics_from_json(nested)

    severity = _first_text(value, "severity", "Severity", "level", "Level")
    kind = _get(value, "kind", "Kind")
    if severity is None and str(kind or "").lower() in _SEVERITIES:
        severity = str(kind)
    if severity is None or severity.lower() not in _SEVERITIES:
        return

    message = _message_text(_get(value, "message", "Message"))
    if not message:
        message = _first_text(value, "description", "text")
    if not message:
        return

    location_value = _get(value, "location", "Location")
    location = location_value if isinstance(location_value, dict) else {}
    hint_value = _get(value, "mainHint", "MainHint")
    hint = hint_value if isinstance(hint_value, dict) else {}
    range_value = _get(hint, "range", "Range") or _get(location, "range", "Range")
    source_range = range_value if isinstance(range_value, dict) else {}
    start_value = _get(value, "start", "Start") or _get(source_range, "start", "Start", "begin", "Begin")
    end_value = _get(value, "end", "End") or _get(source_range, "end", "End")
    start = start_value if isinstance(start_value, dict) else location
    end = end_value if isinstance(end_value, dict) else {}
    if not isinstance(start, dict):
        start = {}
    if not isinstance(end, dict):
        end = {}

    yield CompilerDiagnostic(
        severity=severity.lower(),
        message=message,
        code=_optional_text(_get(value, "code", "Code", "diagKind", "DiagKind")),
        file=_first_text(value, "file", "File", "path", "Path")
        or _first_text(location, "file", "File", "path", "Path")
        or _first_text(start, "file", "File"),
        start_line=_optional_int(_get(start, "line", "Line") or _get(value, "line", "Line")),
        start_column=_optional_int(_get(start, "column", "Column") or _get(value, "column", "Column")),
        end_line=_optional_int(_get(end, "line", "Line")),
        end_column=_optional_int(_get(end, "column", "Column")),
    )


def _message_text(value: Any) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        return _first_text(value, "text", "message", "content")
    return None


def _first_text(value: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None


def _get(value: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in value:
            return value[key]
    return None


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
