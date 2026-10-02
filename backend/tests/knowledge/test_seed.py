from collections import Counter
from pathlib import Path

import pytest
import yaml

from app.knowledge.models import KnowledgeValidationError, ReviewStatus, Topic
from app.knowledge.repository import InMemoryKnowledgeRepository
from app.knowledge.seed import (
    DEFAULT_SEED_DIR,
    SnippetResult,
    check_seed,
    import_seed,
    load_seed,
    verify_snippets,
)

SEED_DIR = Path(__file__).resolve().parents[3] / "data" / "course_seed"
CONCEPTS = "cangjie_concepts.yaml"
MISCONCEPTIONS = "cangjie_misconceptions.yaml"


@pytest.fixture(scope="module")
def bundle():
    return load_seed(SEED_DIR)


def test_default_seed_dir_points_at_repository_data():
    assert DEFAULT_SEED_DIR.resolve() == SEED_DIR.resolve()


def test_seed_meets_minimum_size(bundle):
    approved = [m for m in bundle.misconceptions if m.review_status is ReviewStatus.approved]
    assert len(bundle.concepts) >= 30
    assert len(approved) >= 20


def test_seed_covers_all_nine_topics(bundle):
    approved = [m for m in bundle.misconceptions if m.review_status is ReviewStatus.approved]
    assert {c.topic for c in bundle.concepts} == set(Topic)
    assert {m.topic for m in approved} == set(Topic)


def test_seed_covers_spec_named_misconceptions(bundle):
    ids = {m.id for m in bundle.misconceptions if m.review_status is ReviewStatus.approved}
    for required in [
        "cj.misconception.struct-copied-as-reference",
        "cj.misconception.array-assignment-deep-copy",
        "cj.misconception.match-non-exhaustive",
        "cj.misconception.option-as-null",
        "cj.misconception.direct-extension-implies-interface",
        "cj.misconception.generic-operator-without-constraint",
        "cj.misconception.spawn-get-immediately-serializes",
        "cj.misconception.enum-default-equality",
        "cj.misconception.for-in-variable-reassign",
    ]:
        assert required in ids


def test_seed_metadata_records_toolchain_and_data_nature(bundle):
    meta = bundle.metadata
    assert meta["toolchain"]["cjc"] == "1.2.0 (cjnative)"
    assert meta["toolchain"]["cjpm"] == "1.2.0"
    assert "cangjie-coding" in meta["knowledge_base"]
    assert "not pilot results" in meta["data_nature"]


def test_every_record_has_source_and_toolchain(bundle):
    for record in [*bundle.concepts, *bundle.misconceptions]:
        assert record.source.references
        assert "1.2.0" in record.source.toolchain_version


def test_approved_misconceptions_are_complete_and_experiment_verified(bundle):
    for m in bundle.misconceptions:
        if m.review_status is not ReviewStatus.approved:
            continue
        assert m.trigger_evidence and m.explanation and m.root_concept_id
        assert [h.level for h in m.hint_ladder] == [1, 2, 3, 4]
        assert m.reviewed_by and m.review_note
        assert m.source.verification_status.value == "experiment_verified"
        assert m.verification.method.value in {"cjc_minimal_repro", "cjpm_project_repro"}
        assert m.verification.expected_outcome is not None
        assert m.verification.snippet or m.verification.project_files
        assert "1.2.0" in m.verification.toolchain_version


def test_unverified_records_are_not_approved(bundle):
    for record in [*bundle.concepts, *bundle.misconceptions]:
        if record.source.verification_status.value != "experiment_verified":
            assert record.review_status is not ReviewStatus.approved, record.id


def test_check_seed_reports_consistency_and_acyclic_prerequisites():
    report = check_seed(SEED_DIR)
    assert report.ok
    assert report.prerequisite_acyclic
    assert report.concept_count >= 30
    assert report.approved_misconception_count >= 20
    assert set(report.topic_coverage) == {t.value for t in Topic}
    edge_counts = Counter(report.edge_counts)
    for edge_type in ("prerequisite", "confusable_with", "used_by", "explains_error"):
        assert edge_counts[edge_type] > 0


def test_import_seed_serves_only_approved_evidence(bundle):
    repo = InMemoryKnowledgeRepository()
    import_seed(repo, "course-cj", bundle)
    evidence = repo.approved_evidence("course-cj", concept_ids=["cj.pattern-match.exhaustiveness"])
    assert "cj.misconception.match-non-exhaustive" in {e.misconception_id for e in evidence}
    all_ids = {e.misconception_id for e in repo.approved_evidence("course-cj")}
    pending = {m.id for m in bundle.misconceptions if m.review_status is not ReviewStatus.approved}
    assert pending and not (pending & all_ids)
    with pytest.raises(KnowledgeValidationError):
        import_seed(repo, "course-cj", bundle)


# ------------------------------------------------ loader rejection cases


def write_seed(tmp_path, concepts_doc, misconceptions_doc):
    (tmp_path / CONCEPTS).write_text(yaml.safe_dump(concepts_doc, allow_unicode=True), encoding="utf-8")
    (tmp_path / MISCONCEPTIONS).write_text(
        yaml.safe_dump(misconceptions_doc, allow_unicode=True), encoding="utf-8"
    )
    return tmp_path


@pytest.fixture
def raw_docs():
    concepts_doc = yaml.safe_load((SEED_DIR / CONCEPTS).read_text(encoding="utf-8"))
    mis_doc = yaml.safe_load((SEED_DIR / MISCONCEPTIONS).read_text(encoding="utf-8"))
    return concepts_doc, mis_doc


def expect_code(tmp_path, concepts_doc, mis_doc, code):
    write_seed(tmp_path, concepts_doc, mis_doc)
    with pytest.raises(KnowledgeValidationError) as exc:
        load_seed(tmp_path)
    assert exc.value.code == code, exc.value


def test_loader_rejects_concept_without_source(tmp_path, raw_docs):
    concepts_doc, mis_doc = raw_docs
    del concepts_doc["concepts"][0]["source"]
    expect_code(tmp_path, concepts_doc, mis_doc, "MISSING_SOURCE")


def test_loader_rejects_misconception_without_toolchain(tmp_path, raw_docs):
    concepts_doc, mis_doc = raw_docs
    del mis_doc["misconceptions"][0]["source"]["toolchain_version"]
    expect_code(tmp_path, concepts_doc, mis_doc, "MISSING_SOURCE")


def test_loader_rejects_missing_file_metadata(tmp_path, raw_docs):
    concepts_doc, mis_doc = raw_docs
    del concepts_doc["metadata"]
    expect_code(tmp_path, concepts_doc, mis_doc, "MISSING_SOURCE")


def test_loader_rejects_duplicate_concept(tmp_path, raw_docs):
    concepts_doc, mis_doc = raw_docs
    concepts_doc["concepts"].append(dict(concepts_doc["concepts"][0]))
    expect_code(tmp_path, concepts_doc, mis_doc, "DUPLICATE_ID")


def test_loader_rejects_duplicate_misconception(tmp_path, raw_docs):
    concepts_doc, mis_doc = raw_docs
    mis_doc["misconceptions"].append(dict(mis_doc["misconceptions"][0]))
    expect_code(tmp_path, concepts_doc, mis_doc, "DUPLICATE_ID")


def test_loader_rejects_edge_to_missing_node(tmp_path, raw_docs):
    concepts_doc, mis_doc = raw_docs
    concepts_doc["edges"].append(
        {"source_id": "cj.type.struct-value-semantics", "target_id": "cj.nowhere.node", "edge_type": "used_by"}
    )
    expect_code(tmp_path, concepts_doc, mis_doc, "UNKNOWN_NODE")


def test_loader_rejects_prerequisite_cycle(tmp_path, raw_docs):
    concepts_doc, mis_doc = raw_docs
    first = next(e for e in concepts_doc["edges"] if e["edge_type"] == "prerequisite")
    concepts_doc["edges"].append(
        {"source_id": first["target_id"], "target_id": first["source_id"], "edge_type": "prerequisite"}
    )
    expect_code(tmp_path, concepts_doc, mis_doc, "PREREQUISITE_CYCLE")


def test_loader_rejects_unknown_review_status(tmp_path, raw_docs):
    concepts_doc, mis_doc = raw_docs
    mis_doc["misconceptions"][0]["review_status"] = "reviewed"
    expect_code(tmp_path, concepts_doc, mis_doc, "UNKNOWN_REVIEW_STATUS")


def test_loader_rejects_unknown_edge_type(tmp_path, raw_docs):
    concepts_doc, mis_doc = raw_docs
    concepts_doc["edges"][0]["edge_type"] = "depends_on"
    expect_code(tmp_path, concepts_doc, mis_doc, "UNKNOWN_EDGE_TYPE")


# ------------------------------------------------ snippet verification


def test_verify_snippets_reports_outcome_mismatch(bundle):
    def fake_runner(verification):
        if verification.expected_outcome.value == "compile_error":
            return SnippetResult(outcome="run_ok", output="")
        return SnippetResult(
            outcome=verification.expected_outcome.value,
            output=(verification.expected_output_contains or "") + (verification.observed or ""),
        )

    report = verify_snippets(bundle, runner=fake_runner)
    assert report.checked >= 20
    assert report.mismatches
    assert all(item.expected == "compile_error" for item in report.mismatches)


def test_verify_snippets_passes_when_runner_agrees(bundle):
    def agreeing_runner(verification):
        return SnippetResult(
            outcome=verification.expected_outcome.value,
            output=(verification.expected_output_contains or "") + (verification.observed or ""),
        )

    report = verify_snippets(bundle, runner=agreeing_runner)
    assert report.mismatches == []
