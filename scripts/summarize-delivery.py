"""Verify final evidence integrity and emit a portable hash index."""
import hashlib
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

directory = Path(sys.argv[1]).resolve()
head, mode = sys.argv[2:4]
records = []
for path in sorted(directory.glob("*/command.json")):
    record = json.loads(path.read_text(encoding="utf-8-sig"))
    assert record["head"] == head and record["exit_code"] == 0, path
    assert mode == "candidate" or not record["working_tree"], path
    assert hashlib.sha256((path.parent / record["log"]).read_bytes()).hexdigest() == record["sha256"], path
    for artifact in record["artifacts"]:
        assert hashlib.sha256(Path(artifact["path"]).read_bytes()).hexdigest() == artifact["sha256"], artifact["path"]
    records.append({"name":record["name"],"command_record":str(path.relative_to(directory)),"exit_code":record["exit_code"]})
required = {"demo-cold-build-start","demo-idempotent-restart","runtime-versions-health","frontend-lock-install",
    "delivery-browser-15-steps","delivery-readonly-sql","test-sandbox-image","test-compose-config","test-services",
    "test-environment-prepare","backend-full","runtime-openapi","frontend-components","frontend-types-build",
    "default-browser","gate-browser","gate-readonly-sql","runner-test-tools","runner-worker-test-build",
    "runner-controller-test-build","worker-31-isolated","controller-12-isolated","runner-topology-and-stability",
    "evaluation-structure","historical-manifest-preserved","task11-security-manifest","git-diff-check","git-unresolved-check"}
assert {r["name"] for r in records} == required
backend = list(ET.parse(directory / "backend.xml").getroot().iter("testcase"))
assert backend and all(c.find("failure") is None and c.find("error") is None and c.find("skipped") is None for c in backend)
root = Path(__file__).resolve().parents[1]
original_files = {"test_cross_course_memory","test_evaluation_datasets","test_idor","test_isolated_runner",
    "test_prompt_injection","test_recompute","test_security_repairs","test_small_sample_contract"}
historical = ET.parse(root / "docs/experiments/wave3-evidence/backend-after-review.xml").getroot()
original_nodes = {(c.attrib["classname"],c.attrib["name"]) for c in historical.iter("testcase")
    if c.attrib["classname"].startswith("tests.security.") and c.attrib["classname"].split(".")[-1] in original_files}
assert len(original_nodes) == 220
assert original_nodes <= {(c.attrib["classname"],c.attrib["name"]) for c in backend}
manifest = json.loads((directory / "security-execution-manifest.json").read_text(encoding="utf-8"))
assert manifest["head"] == head and len(manifest["cases"]) == 164
assert mode == "candidate" or manifest["final_clean_evidence"]
assert len([c for c in backend if c.attrib["name"].startswith("test_vector_through_official_router_sql_postgres[")]) == 54
stability_paths = list(directory.glob("runner-stability-*/stability.json"))
assert len(stability_paths) == 1
stability = json.loads(stability_paths[0].read_text(encoding="utf-8"))
assert stability["head"] == head and len(stability["results"]) == 45 and all(r["passed"] for r in stability["results"])
assert len(stability["created"]) == 45 and stability["created"] == stability["destroyed"] and not stability["containers_after"]
assert stability["limits_verified"] and not stability["monitor_errors"]
files = {str(path.relative_to(directory)).replace("\\","/"):hashlib.sha256(path.read_bytes()).hexdigest()
    for path in sorted(directory.rglob("*")) if path.is_file() and path.name not in {"evidence-index.json"}}
summary = {"head":head,"mode":mode,"synthetic_only":True,"commands":records,"backend_passed":len(backend),
    "original_security_regressions_passed":220,"security_cases_passed":164,"original_sql_vectors_passed":54,"runner_jobs_passed":45,
    "runner_latency_seconds":stability["latency_seconds"],"files_sha256":files,
    "teacher_gold":"尚未执行","real_model_comparison":"尚未执行","student_pilot":"尚未执行",
    "external_physical_erasure":"未验证：持久向量、缓存、模型引用适配器尚未实现"}
(directory / "evidence-index.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print(json.dumps({k:v for k,v in summary.items() if k not in {"commands","files_sha256"}},ensure_ascii=False,indent=2))
