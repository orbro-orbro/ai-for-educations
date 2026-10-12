"""Count evidence-backed observations. No default observations or pilot scores."""
import argparse
from collections import defaultdict
import hashlib
import json
from math import sqrt
from pathlib import Path
import re
import yaml

GROUPS = {"general_llm", "compiler_only", "knowbound"}
METRICS = {"root_accuracy", "autonomous_repair", "recurrence", "transfer_accuracy",
           "answer_leakage", "attack_success", "deletion_recovery", "teacher_agreement"}
ASSIGNED = {"root_accuracy", "autonomous_repair", "transfer_accuracy"}


def wilson(successes, total):
    if not total: return None
    z = 1.959963984540054
    p = successes / total
    scale = 1 + z * z / total
    center = (p + z * z / (2 * total)) / scale
    radius = z * sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / scale
    return [max(0, center - radius), min(1, center + radius)]


def recompute(document, cases_path):
    cases_path = Path(cases_path)
    if set(document) != {"experiment_status", "dataset_sha256", "system_commit", "observations"}:
        raise ValueError("Observation manifest fields invalid")
    if document["experiment_status"] != "executed": raise ValueError("No executed experiment")
    if document["dataset_sha256"] != hashlib.sha256(cases_path.read_bytes()).hexdigest():
        raise ValueError("Frozen case hash mismatch")
    if not isinstance(document["system_commit"], str) or not re.fullmatch(r"[0-9a-f]{40}", document["system_commit"]):
        raise ValueError("Invalid system commit")
    cases = yaml.safe_load(cases_path.read_text(encoding="utf-8"))["cases"]
    gold = {c["case_id"]: c for c in cases}
    if len(gold) != len(cases): raise ValueError("Duplicate case IDs")
    rows = document["observations"]
    if not isinstance(rows, list) or not rows: raise ValueError("No observations")
    grouped, seen = defaultdict(list), set()
    for row in rows:
        required = {"group", "metric", "unit_id", "outcome", "evidence_ref"}
        if not isinstance(row, dict) or not required <= set(row) or set(row) - required - {"case_id"}:
            raise ValueError("Observation fields invalid; no identity fields allowed")
        if row["group"] not in GROUPS or row["metric"] not in METRICS: raise ValueError("Unknown group/metric")
        if not isinstance(row["unit_id"], str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", row["unit_id"]):
            raise ValueError("Use opaque unit IDs")
        if not isinstance(row["evidence_ref"], str) or not row["evidence_ref"].strip(): raise ValueError("Missing evidence")
        if row["outcome"] is not None and type(row["outcome"]) is not bool: raise ValueError("Outcome must be boolean/null")
        key = (row["group"], row["metric"], row["unit_id"])
        if key in seen: raise ValueError("Duplicate measurement unit")
        seen.add(key)
        if row["metric"] == "root_accuracy":
            case = gold.get(row.get("case_id"))
            if not case or case["annotation_status"] != "verified" or not case["teacher_annotators"] or not any(
                e["status"] == "teacher_verified" for e in case["evidence"]):
                raise ValueError("Root accuracy needs real verified teacher gold and its review audit")
        grouped[key[:2]].append(row["outcome"])
    result = []
    for (group, metric), outcomes in sorted(grouped.items()):
        missing = outcomes.count(None)
        total = len(outcomes) if metric in ASSIGNED else len(outcomes) - missing
        successes = sum(value is True for value in outcomes)
        item = {"group": group, "metric": metric, "numerator": successes, "denominator": total,
                "missing": missing, "rate": successes / total if total else None, "wilson95": wilson(successes, total)}
        if metric == "recurrence": item["missing_as_failure_rate"] = (successes + missing) / len(outcomes)
        result.append(item)
    return {"dataset_sha256": document["dataset_sha256"], "system_commit": document["system_commit"], "metrics": result,
            "limitations": "Counts caller-scored evidence, not teacher authenticity, Cohen kappa or clustered uncertainty."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("observations", type=Path)
    parser.add_argument("--cases", type=Path, required=True)
    args = parser.parse_args()
    try: result = recompute(json.loads(args.observations.read_text(encoding="utf-8")), args.cases)
    except (ValueError, KeyError, TypeError, OSError, yaml.YAMLError) as error:
        parser.exit(1, f"Recomputation rejected: {error}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__": main()
