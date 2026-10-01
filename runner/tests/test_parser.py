from runner.worker.parser import CompilerDiagnostic, parse_compiler_diagnostics


def test_parse_json_compiler_diagnostic_into_stable_shape() -> None:
    raw = """{
  "severity": "error",
  "message": "expected expression",
  "code": "E1001",
  "file": "main.cj",
  "start": {"line": 3, "column": 7},
  "end": {"line": 3, "column": 8}
}"""

    assert parse_compiler_diagnostics(raw) == [
        CompilerDiagnostic(
            severity="error",
            message="expected expression",
            code="E1001",
            file="main.cj",
            start_line=3,
            start_column=7,
            end_line=3,
            end_column=8,
        )
    ]


def test_parse_line_delimited_json_and_ignores_non_diagnostic_records() -> None:
    raw = """{"kind":"progress","message":"compiling"}
{"level":"warning","message":"unused variable","path":"src/main.cj","line":2,"column":9}
"""

    assert parse_compiler_diagnostics(raw) == [
        CompilerDiagnostic(
            severity="warning",
            message="unused variable",
            code=None,
            file="src/main.cj",
            start_line=2,
            start_column=9,
            end_line=None,
            end_column=None,
        )
    ]


def test_parse_plain_compiler_diagnostic_as_compatibility_fallback() -> None:
    raw = "main.cj:4:12: error: unknown identifier 'value'"

    assert parse_compiler_diagnostics(raw) == [
        CompilerDiagnostic(
            severity="error",
            message="unknown identifier 'value'",
            code=None,
            file="main.cj",
            start_line=4,
            start_column=12,
            end_line=None,
            end_column=None,
        )
    ]


def test_parse_empty_output_returns_no_diagnostics() -> None:
    assert parse_compiler_diagnostics("") == []


def test_parse_cjc_1_2_json_diagnostic() -> None:
    raw = """{
  "Diags": [{
    "DiagKind": "parse_expected_expression",
    "Severity": "error",
    "Message": "expected expression after '=', found '}'",
    "Location": {"File": "main.cj", "Line": 1, "Column": 18},
    "MainHint": {"Range": {
      "Begin": {"File": "main.cj", "Line": 1, "Column": 18},
      "End": {"File": "main.cj", "Line": 1, "Column": 19}
    }}
  }],
  "Num": {"Errors": 1, "Warnings": 0}
}"""

    assert parse_compiler_diagnostics(raw) == [
        CompilerDiagnostic(
            severity="error",
            message="expected expression after '=', found '}'",
            code="parse_expected_expression",
            file="main.cj",
            start_line=1,
            start_column=18,
            end_line=1,
            end_column=19,
        )
    ]
