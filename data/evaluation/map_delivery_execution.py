"""Task 11 manifest from a clean final HEAD and its complete actual JUnit run.

Historical Wave 3 manifests are deliberately never rewritten.
"""
import argparse
from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("historical_mapping", Path(__file__).with_name("map_security_execution.py"))
historical = importlib.util.module_from_spec(spec)
spec.loader.exec_module(historical)


def bind_command(report, record, head, allow_dirty=False):
    report = Path(report).resolve()
    if record["head"] != head or (record["working_tree"] and not allow_dirty) or record["exit_code"] != 0:
        raise ValueError("Evidence requires successful execution at the selected clean HEAD")
    if not record.get("started_utc") or not record.get("finished_utc"):
        raise ValueError("Actual command timing required")
    paths = [Path(record["cwd"]) / arg.split("=",1)[1] for arg in record["arguments"] if arg.startswith("--junitxml=")]
    if report not in [path.resolve() for path in paths]:
        raise ValueError("Command did not produce this JUnit report")
    artifacts = [a for a in record.get("artifacts",[]) if Path(a["path"]).resolve() == report]
    if len(artifacts) != 1 or artifacts[0]["sha256"] != historical.digest(report):
        raise ValueError("Report is missing from hashed command artifacts or has changed")


def expected_node(case):
    cid = case["case_id"]
    if case["input"]["attack_category"] == "small_sample":
        return "backend/tests/integration/test_wave3_analytics_vectors_postgres.py::test_vector_through_official_router_sql_postgres[analytics-" + cid.removeprefix("sec-small-sample-") + "]"
    if cid in {"sec-cross-role-002","sec-cross-role-008","sec-deletion-recovery-005"}:
        return f"backend/tests/integration/test_wave3_security_cases_postgres.py::test_concrete_postgres_operation[{cid}]"
    if cid in {"sec-executor-abuse-006","sec-executor-abuse-007","sec-executor-abuse-008"}:
        return f"backend/tests/security/test_wave3_container_attacks.py::test_concrete_container_attack[{cid}]"
    return f"backend/tests/security/test_wave3_case_execution.py::test_planned_operation[{cid}]"


def map_cases(planned, executed):
    if len(planned) != 164 or len({c["case_id"] for c in planned}) != 164:
        raise ValueError("Exactly the original 164 cases required")
    rows = []
    for case in planned:
        cid = case["case_id"]
        node = expected_node(case)
        actual = executed.get(node)
        if not actual or actual["status"] != "automated_passed":
            raise ValueError("Required operation absent or unsuccessful: " + cid)
        props = actual["properties"]
        local = "/security/test_wave3_case_execution.py" in node
        if local and (props.get("case_id") != cid or props.get("operation") != case["input"]["operation"]):
            raise ValueError("Wrong actual attack operation: " + cid)
        if cid == "sec-cross-course-006" and not historical.correct_course_006(props):
            raise ValueError("Wrong course/proposal preconditions")
        if cid == "sec-sensitive-logging-008" and props.get("policy") != "ADR 0007: server-generated correlation; inbound marker absent":
            raise ValueError("Approved request correlation policy not executed")
        rows.append({"case_id":cid,"case_sha256":historical.case_hash(case),"operation":case["input"]["operation"],
            "status":actual["status"],"node":node,"executed_at":actual["timestamp"],
            "duration_seconds":actual["duration_seconds"],"properties":props})
    return rows


def build(report, command_path, head, allow_dirty=False):
    record = json.loads(Path(command_path).read_text(encoding="utf-8-sig"))
    bind_command(report, record, head, allow_dirty)
    executed = historical.junit(report)
    if not executed or any(a["status"] != "automated_passed" for a in executed.values()):
        raise ValueError("Complete backend report contains failed or unexecuted tests")
    start = datetime.fromisoformat(record["started_utc"].replace("Z","+00:00"))
    end = datetime.fromisoformat(record["finished_utc"].replace("Z","+00:00"))
    for actual in executed.values():
        timestamp = datetime.fromisoformat(actual["timestamp"])
        if timestamp.tzinfo is None: timestamp = timestamp.replace(tzinfo=start.tzinfo)
        if not start <= timestamp <= end: raise ValueError("Report timestamp outside recorded command")
    files = ["security_cases.yaml","analytics_vectors.yaml","diagnosis_cases.yaml"]
    planned = json.loads((ROOT/"data/evaluation/security_cases.yaml").read_text(encoding="utf-8"))["cases"]
    return {"version":"wave4-task11-executed-v1","head":head,"final_clean_evidence":not bool(record["working_tree"]),
        "data_nature":"synthetic software verification; no teacher gold, real model comparison or student pilot",
        "command_record":str(Path(command_path).resolve()),"command_sha256":historical.digest(Path(command_path)),
        "report":str(Path(report).resolve()),"report_sha256":historical.digest(Path(report)),
        "backend_test_count":len(executed),"datasets":{name:{"raw_sha256":historical.digest(ROOT/"data/evaluation"/name),
            "lf_sha256":hashlib.sha256((ROOT/"data/evaluation"/name).read_bytes().replace(b"\r\n",b"\n")).hexdigest()} for name in files},
        "external_erasure":"not_verified; persistent vector/cache/model-reference adapters not implemented",
        "cases":map_cases(planned, executed)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("report","command","head","output"): parser.add_argument("--"+name,required=True)
    parser.add_argument("--allow-dirty-candidate",action="store_true")
    args = parser.parse_args()
    manifest = build(args.report,args.command,args.head,args.allow_dirty_candidate)
    Path(args.output).write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"head":args.head,"cases":len(manifest["cases"]),"automated_passed":len(manifest["cases"]),"final_clean_evidence":manifest["final_clean_evidence"]}))
