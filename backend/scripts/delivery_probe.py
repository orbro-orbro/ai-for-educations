"""Read-only authority probe for completed synthetic browser rehearsals."""
import json
import os
import sys
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session
from app.persistence.models import (
    DiagnosisRow, DiagnosisAttemptRow, ExecutionResultRow, HintEventRow,
    ExplanationCheckRow, LearningMemoryRow, MemoryProposalRow, MemoryDeletionRow,
    MemoryTombstoneRow, TokenRevocationRow,
)
from scripts.delivery_demo import validate_demo_target


def probe(observations):
    url = os.environ["DATABASE_URL"]
    validate_demo_target(url, os.environ["APP_ENV"], os.environ["KNOWBOUND_SYNTHETIC_DEMO"])
    engine = create_engine(url)
    try:
        with Session(engine) as session:
            session.execute(text("SET TRANSACTION READ ONLY"))
            diagnosis = session.get(DiagnosisRow, observations["diagnosis_id"])
            assert diagnosis and diagnosis.owner_user_id == "demo-student-1"
            assert diagnosis.course_id == "cangjie-language-design"
            assert diagnosis.submission_id == observations["original_submission_id"]
            original = session.get(ExecutionResultRow, diagnosis.submission_id)
            retry = session.get(ExecutionResultRow, observations["retry_submission_id"])
            assert original.status == "compile_failed" and retry.status == "succeeded"
            attempts = session.scalars(select(DiagnosisAttemptRow).where(DiagnosisAttemptRow.diagnosis_id == diagnosis.id)).all()
            assert len([a for a in attempts if a.submission_id == retry.submission_id]) == 1
            levels = session.scalars(select(HintEventRow.current_level).where(HintEventRow.diagnosis_id == diagnosis.id).order_by(HintEventRow.current_level)).all()
            assert levels == [1, 2]
            checks = session.scalars(select(ExplanationCheckRow).where(ExplanationCheckRow.diagnosis_id == diagnosis.id)).all()
            assert len(checks) == 2 and all(c.understands for c in checks)
            memory = session.get(LearningMemoryRow, observations["corrected_memory_id"])
            assert memory and memory.source_diagnosis_id == diagnosis.id and memory.version == 2
            lineage = session.scalars(select(LearningMemoryRow).where(LearningMemoryRow.logical_memory_id == memory.logical_memory_id)).all()
            assert len(lineage) == 2 and all(m.status == "deleted" and m.content is None for m in lineage)
            proposals = session.scalars(select(MemoryProposalRow).where(MemoryProposalRow.diagnosis_id == diagnosis.id)).all()
            assert sorted(p.status for p in proposals) == ["accepted", "rejected"]
            assert all(p.content == "[Deleted by student]" for p in proposals)
            assert diagnosis.root_cause == "[Deleted by student]"
            assert all(c.evidence_summary == "[Deleted by student]" and c.feedback == "[Deleted by student]" and not c.memory_proposal_eligible for c in checks)
            receipt = session.scalar(select(MemoryDeletionRow).where(MemoryDeletionRow.logical_memory_id == memory.logical_memory_id))
            assert receipt and receipt.status == "deleted" and receipt.completed_at and receipt.reverse_lookup_absent
            assert session.get(MemoryTombstoneRow, memory.logical_memory_id).deletion_id == receipt.id
            assert session.scalar(select(TokenRevocationRow.token_digest).limit(1))
            return {"synthetic_only": True, "read_only_transaction": True,
                "compiler_failure_to_success": True, "unique_retry_association": True,
                "hint_levels": levels, "mock_understanding_checks": len(checks),
                "deleted_versions": len(lineage), "proposal_statuses": sorted(p.status for p in proposals),
                "source_context_cleared": True, "tombstone_present": True,
                "browser_same_query_absent": observations["reverse_lookup_absent"],
                "external_physical_erasure": "not_verified; external adapters are not implemented"}
    finally:
        engine.dispose()


if __name__ == "__main__":
    print(json.dumps(probe(json.load(sys.stdin)["observations"]), ensure_ascii=False))
