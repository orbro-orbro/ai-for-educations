from app.diagnostics.rules import match_rules
from app.knowledge.models import (
    SourceKind,
    SourceMetadata,
    TriggerEvidence,
    TriggerKind,
    TriggerStrength,
    VerificationStatus,
)
from app.knowledge.repository import ApprovedEvidence
from app.knowledge.repository import InMemoryKnowledgeRepository
from app.knowledge.seed import load_seed
from app.submissions.runner_contract import CompilerDiagnostic


class ApprovedFixtureRepository:
    def approved_evidence(self, course_id, concept_ids=None, misconception_ids=None):
        assert course_id == "course-1"
        return [
            ApprovedEvidence(
                misconception_id="cj.misconception.match-non-exhaustive",
                root_concept_id="cj.pattern-match.exhaustiveness",
                related_concept_ids=(
                    "cj.pattern-match.match-expression",
                    "cj.pattern-match.wildcard",
                ),
                trigger_evidence=(
                    TriggerEvidence(
                        kind=TriggerKind.compiler_diagnostic,
                        pattern="non-exhaustive patterns",
                        strength=TriggerStrength.strong,
                    ),
                    TriggerEvidence(
                        kind=TriggerKind.code_pattern,
                        pattern="missing branch in source",
                        strength=TriggerStrength.strong,
                    ),
                ),
                explanation="approved explanation",
                hint_ladder=(),
                source=SourceMetadata(
                    kind=SourceKind.toolchain_experiment,
                    references=["exp:match_non_exhaustive"],
                    toolchain_version="cjc 1.2.0 (cjnative)",
                    verification_status=VerificationStatus.experiment_verified,
                ),
            )
        ]


def diagnostic(message):
    return CompilerDiagnostic(
        severity="error",
        message=message,
        code=None,
        file="main.cj",
        start_line=3,
        start_column=5,
        end_line=None,
        end_column=None,
    )


def test_rule_matching_uses_only_compiler_evidence_and_stably_deduplicates():
    matches = match_rules(
        course_id="course-1",
        diagnostics=[
            diagnostic("error: non-exhaustive patterns: B not covered"),
            diagnostic("NON-EXHAUSTIVE PATTERNS remain"),
        ],
        knowledge=ApprovedFixtureRepository(),
    )

    assert len(matches) == 1
    match = matches[0]
    assert match.misconception_id == "cj.misconception.match-non-exhaustive"
    assert match.root_concept_id == "cj.pattern-match.exhaustiveness"
    assert match.diagnostic_indices == (0, 1)
    assert match.evidence_kind == "compiler_diagnostic"
    assert match.evidence_summary == "non-exhaustive patterns"
    assert match.source_references == ("exp:match_non_exhaustive",)
    assert match.match_strength == "strong"


def test_pending_seed_and_unknown_diagnostic_produce_no_rule_matches():
    seed = load_seed()
    pending = InMemoryKnowledgeRepository()
    pending.load_course("course-1", seed.concepts, seed.edges, seed.misconceptions)

    assert match_rules(
        course_id="course-1",
        diagnostics=[diagnostic("non-exhaustive patterns")],
        knowledge=pending,
    ) == []
    assert match_rules(
        course_id="course-1",
        diagnostics=[diagnostic("an unknown compiler message")],
        knowledge=ApprovedFixtureRepository(),
    ) == []
