"""Load, check and import the reviewed Cangjie course seed.

Usage (from ``backend``):
    python -m app.knowledge.seed check
    python -m app.knowledge.seed verify-snippets   # needs cjc/cjpm on PATH

``verify-snippets`` compiles only the repository's own seed snippets on the host.
Student or teacher-submitted code must never go through it; that belongs to the isolated runner.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from app.knowledge.models import (
    Concept,
    ConceptEdge,
    KnowledgeValidationError,
    MisconceptionPattern,
    ReviewStatus,
    Verification,
    VerificationMethod,
    parse_concept,
    parse_edge,
    parse_misconception,
)
from app.knowledge.repository import KnowledgeGraph, KnowledgeRepository

DEFAULT_SEED_DIR = Path(__file__).resolve().parents[3] / "data" / "course_seed"
CONCEPTS_FILE = "cangjie_concepts.yaml"
MISCONCEPTIONS_FILE = "cangjie_misconceptions.yaml"
_METADATA_REQUIRED = ("course_key", "seed_version", "toolchain", "knowledge_base", "data_nature")


@dataclass(frozen=True)
class SeedBundle:
    metadata: dict[str, Any]
    concepts: list[Concept]
    edges: list[ConceptEdge]
    misconceptions: list[MisconceptionPattern]


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ModuleNotFoundError as exc:  # PyYAML is only a dev dependency today
        raise RuntimeError("PyYAML is required to load the course seed") from exc
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise KnowledgeValidationError("VALIDATION_ERROR", f"{path.name} must be a mapping")
    return data


def _require_metadata(doc: dict[str, Any], name: str) -> dict[str, Any]:
    meta = doc.get("metadata")
    if not isinstance(meta, dict) or any(not meta.get(k) for k in _METADATA_REQUIRED):
        raise KnowledgeValidationError("MISSING_SOURCE", f"{name} lacks complete file metadata")
    return meta


def load_seed(seed_dir: Path = DEFAULT_SEED_DIR) -> SeedBundle:
    seed_dir = Path(seed_dir)
    concepts_doc = _read_yaml(seed_dir / CONCEPTS_FILE)
    mis_doc = _read_yaml(seed_dir / MISCONCEPTIONS_FILE)
    meta = _require_metadata(concepts_doc, CONCEPTS_FILE)
    mis_meta = _require_metadata(mis_doc, MISCONCEPTIONS_FILE)
    if mis_meta["course_key"] != meta["course_key"]:
        raise KnowledgeValidationError("VALIDATION_ERROR", "seed files describe different courses")

    concepts = [parse_concept(c) for c in concepts_doc.get("concepts") or []]
    edges = [parse_edge(e) for e in concepts_doc.get("edges") or []]
    misconceptions = [parse_misconception(m) for m in mis_doc.get("misconceptions") or []]
    KnowledgeGraph.build(concepts, edges, misconceptions)
    return SeedBundle(meta, concepts, edges, misconceptions)


@dataclass
class SeedReport:
    ok: bool
    prerequisite_acyclic: bool
    concept_count: int = 0
    misconception_count: int = 0
    approved_misconception_count: int = 0
    topic_coverage: dict[str, dict[str, int]] = field(default_factory=dict)
    edge_counts: dict[str, int] = field(default_factory=dict)
    review_counts: dict[str, int] = field(default_factory=dict)
    error: str | None = None


def check_seed(seed_dir: Path = DEFAULT_SEED_DIR) -> SeedReport:
    try:
        bundle = load_seed(seed_dir)
    except KnowledgeValidationError as exc:
        return SeedReport(ok=False, prerequisite_acyclic=exc.code != "PREREQUISITE_CYCLE", error=str(exc))
    approved = [m for m in bundle.misconceptions if m.review_status is ReviewStatus.approved]
    coverage: dict[str, dict[str, int]] = {}
    for c in bundle.concepts:
        coverage.setdefault(c.topic.value, {"concepts": 0, "approved_misconceptions": 0})["concepts"] += 1
    for m in approved:
        coverage.setdefault(m.topic.value, {"concepts": 0, "approved_misconceptions": 0})[
            "approved_misconceptions"
        ] += 1
    reviews = Counter(r.review_status.value for r in [*bundle.concepts, *bundle.misconceptions])
    return SeedReport(
        ok=True,
        prerequisite_acyclic=True,
        concept_count=len(bundle.concepts),
        misconception_count=len(bundle.misconceptions),
        approved_misconception_count=len(approved),
        topic_coverage=coverage,
        edge_counts=dict(Counter(e.edge_type.value for e in bundle.edges)),
        review_counts=dict(reviews),
    )


def import_seed(repository: KnowledgeRepository, course_id: str, bundle: SeedBundle) -> None:
    repository.load_course(course_id, bundle.concepts, bundle.edges, bundle.misconceptions)


# ---------------------------------------------------------------- snippet verification

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


@dataclass(frozen=True)
class SnippetResult:
    outcome: str
    output: str


@dataclass(frozen=True)
class SnippetMismatch:
    misconception_id: str
    expected: str
    observed: str
    detail: str


@dataclass
class SnippetReport:
    checked: int = 0
    mismatches: list[SnippetMismatch] = field(default_factory=list)


Runner = Callable[[Verification], SnippetResult]


def _run(cmd: list[str], cwd: Path, timeout: int) -> tuple[int, str]:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, timeout=timeout)
    text = proc.stdout.decode("utf-8", "replace") + proc.stderr.decode("utf-8", "replace")
    return proc.returncode, _ANSI.sub("", text)


def cjc_runner(verification: Verification, timeout: int = 60) -> SnippetResult:
    with tempfile.TemporaryDirectory(prefix="cj-seed-") as tmp:
        work = Path(tmp)
        if verification.method is VerificationMethod.cjpm_project_repro:
            _run(["cjpm", "init", "--name", "demo", "--type=executable"], work, timeout)
            for rel, content in (verification.project_files or {}).items():
                target = (work / rel).resolve()
                if work.resolve() not in target.parents:
                    raise ValueError(f"project file escapes work dir: {rel}")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
            code, out = _run(["cjpm", "build"], work, timeout * 3)
            if code != 0:
                return SnippetResult("compile_error", out)
            code, run_out = _run(["cjpm", "run"], work, timeout * 3)
            return SnippetResult("run_ok" if code == 0 else "runtime_error", out + run_out)

        (work / "main.cj").write_text(verification.snippet or "", encoding="utf-8")
        exe = work / ("main.exe" if sys.platform == "win32" else "main")
        code, out = _run(["cjc", "main.cj", "-o", exe.name], work, timeout)
        if code != 0:
            return SnippetResult("compile_error", out)
        try:
            code, run_out = _run([str(exe)], work, timeout)
        except subprocess.TimeoutExpired:
            return SnippetResult("timeout", "")
        return SnippetResult("run_ok" if code == 0 else "runtime_error", run_out)


def verify_snippets(bundle: SeedBundle, runner: Runner = cjc_runner) -> SnippetReport:
    report = SnippetReport()
    for m in bundle.misconceptions:
        v = m.verification
        if v.expected_outcome is None:
            continue
        report.checked += 1
        result = runner(v)
        problems = []
        if result.outcome != v.expected_outcome.value:
            problems.append(f"outcome {result.outcome}")
        for needle in (v.expected_output_contains, v.observed):
            if needle and needle not in result.output:
                problems.append(f"missing output {needle!r}")
        if problems:
            report.mismatches.append(
                SnippetMismatch(m.id, v.expected_outcome.value, result.outcome, "; ".join(problems))
            )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["check", "verify-snippets"])
    parser.add_argument("--seed-dir", type=Path, default=DEFAULT_SEED_DIR)
    args = parser.parse_args(argv)
    if args.command == "check":
        report = check_seed(args.seed_dir)
        print(json.dumps(report.__dict__, ensure_ascii=False, indent=2))
        return 0 if report.ok else 1
    for tool in ("cjc", "cjpm"):
        if shutil.which(tool) is None:
            print(f"{tool} not found on PATH", file=sys.stderr)
            return 2
    report = verify_snippets(load_seed(args.seed_dir))
    print(json.dumps({"checked": report.checked, "mismatches": [m.__dict__ for m in report.mismatches]}, indent=2))
    return 0 if not report.mismatches else 1


if __name__ == "__main__":
    raise SystemExit(main())
