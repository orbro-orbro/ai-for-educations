from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.knowledge.models import TriggerKind, TriggerStrength
from app.knowledge.repository import KnowledgeRepository
from app.submissions.runner_contract import CompilerDiagnostic


@dataclass(frozen=True, slots=True)
class RuleMatch:
    course_id: str
    misconception_id: str
    root_concept_id: str
    related_concept_ids: tuple[str, ...]
    diagnostic_indices: tuple[int, ...]
    evidence_kind: str
    evidence_summary: str
    source_references: tuple[str, ...]
    match_strength: str


def match_rules(
    *,
    course_id: str,
    diagnostics: Iterable[CompilerDiagnostic],
    knowledge: KnowledgeRepository,
) -> list[RuleMatch]:
    """Match approved literal compiler evidence; never inspect or rewrite source."""

    diagnostic_list = tuple(diagnostics)
    matches: list[RuleMatch] = []
    for evidence in sorted(
        knowledge.approved_evidence(course_id), key=lambda item: item.misconception_id
    ):
        hits: list[tuple[int, str, TriggerStrength]] = []
        triggers = sorted(
            (
                trigger
                for trigger in evidence.trigger_evidence
                if trigger.kind is TriggerKind.compiler_diagnostic
            ),
            key=lambda trigger: (
                0 if trigger.strength is TriggerStrength.strong else 1,
                trigger.pattern.casefold(),
            ),
        )
        for index, diagnostic in enumerate(diagnostic_list):
            message = diagnostic.message.casefold()
            for trigger in triggers:
                if trigger.pattern.casefold() in message:
                    hits.append((index, trigger.pattern, trigger.strength))
                    break
        if not hits:
            continue
        strength = (
            TriggerStrength.strong
            if any(item[2] is TriggerStrength.strong for item in hits)
            else TriggerStrength.weak
        )
        summary = next(item[1] for item in hits if item[2] is strength)
        matches.append(
            RuleMatch(
                course_id=course_id,
                misconception_id=evidence.misconception_id,
                root_concept_id=evidence.root_concept_id,
                related_concept_ids=evidence.related_concept_ids,
                diagnostic_indices=tuple(dict.fromkeys(item[0] for item in hits)),
                evidence_kind=TriggerKind.compiler_diagnostic.value,
                evidence_summary=summary,
                source_references=tuple(evidence.source.references),
                match_strength=strength.value,
            )
        )
    return matches
