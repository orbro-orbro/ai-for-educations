"""Real sandbox checks require an explicitly selected local image.

No untrusted source is ever executed by the API process or test host.
"""
import json
import os
from pathlib import Path
import subprocess
from uuid import uuid4
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]


def isolated_execute(source, timeout_ms=5000):
    image = os.environ.get("TASK10_RUNNER_IMAGE")
    if not image: pytest.skip("TASK10_RUNNER_IMAGE must explicitly select an authorized local sandbox image")
    request = {"protocol_version": "2", "submission_id": "task10-isolated-test", "source_files": [{"path": "main.cj", "content": source}], "entrypoint": "main.cj", "timeout_ms": timeout_ms}
    name = "knowbound-task10-sandbox-" + uuid4().hex
    try:
        completed = subprocess.run(["docker", "run", "--rm", "--name", name, "--label", "knowbound.task=wave3-task10", "-i", "--network", "none", "--read-only", "--user", "10001:10001",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true", "--pids-limit", "64", "--memory", "512m", "--cpus", "1",
        "--tmpfs", "/work:rw,nosuid,nodev,exec,size=64m,mode=0700,uid=10001,gid=10001", "--entrypoint", "python", image, "-m", "runner.worker.cli"],
            input=json.dumps(request) + "\n", text=True, capture_output=True, timeout=35, check=True)
        return json.loads(completed.stdout)
    finally:
        # Only this test's freshly named container is targeted, including timeout.
        subprocess.run(["docker", "rm", "--force", name], capture_output=True, timeout=10)


def test_current_toolchain_reports_real_non_exhaustive_match_in_isolation():
    source = "enum Choice { A | B }\nfunc value(choice: Choice): Int64 {\n match (choice) { case A => 1 }\n}\nmain(): Int64 { value(B) }"
    result = isolated_execute(source)
    assert result["status"] == "compile_failed"
    assert any("non-exhaustive patterns" in d["message"] for d in result["diagnostics"])
    assert result["toolchain"]["cjc"] == "1.2.0"
    assert result["toolchain"]["cjpm"] == "1.2.0"


def test_infinite_loop_is_bounded_by_actual_sandbox_deadline():
    source = (ROOT / "runner/tests/fixtures/infinite_loop.cj").read_text(encoding="utf-8")
    result = isolated_execute(source, timeout_ms=2000)
    assert result["status"] == "timed_out"
    assert result["retryable"] is False


@pytest.mark.parametrize("index", range(4))
def test_draft_diagnosis_sources_have_recorded_compiler_outcome(index):
    cases = yaml.safe_load((ROOT / "data/evaluation/diagnosis_cases.yaml").read_text(encoding="utf-8"))["cases"]
    case = cases[index]
    result = isolated_execute(case["input"]["source_code"])
    assert result["status"] == case["input"]["expected_execution_status"]
    assert result["toolchain"]["cjc"] == "1.2.0"
    # A compiler observation is not a real teacher root-cause annotation.
    assert case["annotation_status"] == "draft" and case["teacher_annotators"] == []
