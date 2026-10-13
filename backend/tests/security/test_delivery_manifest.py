"""Final evidence must fail closed on stale, partial or unrelated execution."""
import importlib.util
import json
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[3]


def module():
    spec = importlib.util.spec_from_file_location("delivery_mapping", ROOT / "data/evaluation/map_delivery_execution.py")
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


@pytest.mark.parametrize("mutation", ["wrong_head", "dirty", "failed", "report_hash", "wrong_report", "missing_artifact"])
def test_command_binding_refuses_unverifiable_reports(tmp_path, mutation):
    import hashlib
    report = tmp_path / "report.xml"
    report.write_text("<testsuites/>")
    record = {"head":"a"*40,"working_tree":[],"exit_code":0,"cwd":str(tmp_path),
        "arguments":["-m","pytest","--junitxml=report.xml"],"started_utc":"2026-10-12T00:00:00Z",
        "finished_utc":"2026-10-12T00:01:00Z", "artifacts":[{"path":str(report),"sha256":hashlib.sha256(report.read_bytes()).hexdigest()}]}
    if mutation == "wrong_head": record["head"] = "b"*40
    elif mutation == "dirty": record["working_tree"] = [" M product.py"]
    elif mutation == "failed": record["exit_code"] = 1
    elif mutation == "report_hash": record["artifacts"][0]["sha256"] = "0"*64
    elif mutation == "wrong_report": record["arguments"][-1] = "--junitxml=another.xml"
    else: record["artifacts"] = []
    with pytest.raises(ValueError): module().bind_command(report, record, "a"*40)


@pytest.mark.parametrize("mutation", ["missing", "skipped", "wrong_operation", "wrong_course", "old_policy"])
def test_per_case_mapping_refuses_wrong_or_unexecuted_operations(mutation):
    value = module()
    planned = json.loads((ROOT / "data/evaluation/security_cases.yaml").read_text(encoding="utf-8"))["cases"]
    executed = {}
    for case in planned:
        cid = case["case_id"]
        props = {"case_id":cid,"operation":case["input"]["operation"]}
        props.update(value.historical.COURSE_006_PRECONDITIONS)
        props["policy"] = "ADR 0007: server-generated correlation; inbound marker absent"
        node = value.expected_node(case)
        executed[node] = {"status":"automated_passed","properties":props,"timestamp":"2026-10-12T00:00:01Z","duration_seconds":.1}
    target = next(node for node in executed if node.endswith("[sec-sensitive-logging-008]"))
    if mutation == "missing": executed.pop(target)
    elif mutation == "skipped": executed[target]["status"] = "not_executed"
    elif mutation == "wrong_operation": executed[target]["properties"]["operation"] = "unrelated"
    elif mutation == "old_policy": executed[target]["properties"]["policy"] = "echo"
    else:
        node = next(n for n in executed if n.endswith("[sec-cross-course-006]"))
        executed[node]["properties"]["attack_course"] = "course-a"
    with pytest.raises(ValueError): value.map_cases(planned, executed)
