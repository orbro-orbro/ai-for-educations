from __future__ import annotations

import json
from datetime import timedelta

import pytest

from app.analytics.schemas import AnalyticsFilters, TeacherAnalyticsAvailable
from app.analytics.service import InvalidAnalyticsFilters

from .conftest import (
    BASE_TIME,
    CONCEPT_A,
    CONCEPT_B,
    COURSE_A,
    COURSE_B,
    EXERCISE_A,
    OWNER,
    fact,
)


FILTER_COMBINATIONS = [
    AnalyticsFilters(),
    AnalyticsFilters(concept_id=CONCEPT_A),
    AnalyticsFilters(exercise_id=EXERCISE_A),
    AnalyticsFilters(start_at=BASE_TIME + timedelta(hours=1)),
    AnalyticsFilters(end_at=BASE_TIME + timedelta(hours=6)),
    AnalyticsFilters(concept_id=CONCEPT_A, exercise_id=EXERCISE_A),
    AnalyticsFilters(
        concept_id=CONCEPT_A,
        start_at=BASE_TIME + timedelta(hours=1),
        end_at=BASE_TIME + timedelta(hours=6),
    ),
    AnalyticsFilters(
        exercise_id=EXERCISE_A,
        start_at=BASE_TIME + timedelta(hours=1),
        end_at=BASE_TIME + timedelta(hours=6),
    ),
    AnalyticsFilters(
        concept_id=CONCEPT_A,
        exercise_id=EXERCISE_A,
        start_at=BASE_TIME + timedelta(hours=1),
        end_at=BASE_TIME + timedelta(hours=6),
    ),
]


@pytest.mark.parametrize(
    "filters",
    FILTER_COMBINATIONS,
)
def test_every_filter_combination_uses_the_same_five_student_floor(
    service, repository, filters
) -> None:
    repository.add_facts([fact(number) for number in range(1, 6)])
    repository.add_fact(fact(99, course_id=COURSE_B))

    result = service.course_analytics(OWNER, COURSE_A, filters)

    assert isinstance(result, TeacherAnalyticsAvailable)
    assert result.sample_size == 5
    assert result.minimum_sample_size == 5
    assert len(result.groups) == 1
    assert result.groups[0].sample_size == 5


@pytest.mark.parametrize("filters", FILTER_COMBINATIONS)
def test_every_filter_combination_suppresses_four_distinct_students(
    service, repository, filters
) -> None:
    repository.add_facts([fact(number) for number in range(1, 5)])
    repository.add_fact(fact(99, course_id=COURSE_B))

    result = service.course_analytics(OWNER, COURSE_A, filters)

    assert result.model_dump(mode="json") == {
        "status": "insufficient_sample",
        "course_id": COURSE_A,
        "filters": filters.model_dump(mode="json"),
        "minimum_sample_size": 5,
    }


def test_four_students_suppresses_the_entire_response_without_an_exact_count(
    service, repository
) -> None:
    repository.add_facts([fact(number) for number in range(1, 5)])

    result = service.course_analytics(OWNER, COURSE_A, AnalyticsFilters())

    assert result.model_dump(mode="json") == {
        "status": "insufficient_sample",
        "course_id": COURSE_A,
        "filters": {
            "concept_id": None,
            "exercise_id": None,
            "start_at": None,
            "end_at": None,
        },
        "minimum_sample_size": 5,
    }


def test_exactly_five_distinct_students_is_available(service, repository) -> None:
    repository.add_facts([fact(number) for number in range(1, 6)])

    result = service.course_analytics(OWNER, COURSE_A, AnalyticsFilters())

    assert result.status == "available"
    assert result.sample_size == 5


def test_multiple_diagnoses_from_one_student_do_not_inflate_sample_size(
    service, repository
) -> None:
    repository.add_facts(
        [
            fact(1, subject_key="subject-1"),
            fact(2, subject_key="subject-1"),
            fact(3, subject_key="subject-2"),
            fact(4, subject_key="subject-3"),
            fact(5, subject_key="subject-4"),
        ]
    )

    result = service.course_analytics(OWNER, COURSE_A, AnalyticsFilters())

    assert result.status == "insufficient_sample"
    assert "sample_size" not in result.model_dump()


def test_group_counts_distinct_students_but_counts_unique_diagnoses(
    service, repository
) -> None:
    repository.add_facts(
        [
            fact(1, subject_key="subject-1", independent_repaired=True),
            fact(2, subject_key="subject-1", independent_repaired=True),
            *[fact(number) for number in range(3, 7)],
        ]
    )

    result = service.course_analytics(OWNER, COURSE_A, AnalyticsFilters())

    group = result.groups[0]
    assert group.sample_size == 5
    assert group.diagnosis_count == 6
    assert group.independent_repair_count == 2


def test_groups_below_five_students_are_omitted_even_when_overall_is_available(
    service, repository
) -> None:
    repository.add_facts([fact(number) for number in range(1, 6)])
    repository.add_facts(
        [
            fact(
                10 + number,
                subject_key=f"small-{number}",
                concept_ids=(CONCEPT_B,),
                exercise_id="exercise-small",
            )
            for number in range(1, 5)
        ]
    )

    result = service.course_analytics(OWNER, COURSE_A, AnalyticsFilters())

    assert result.sample_size == 9
    assert [(group.concept_id, group.sample_size) for group in result.groups] == [
        (CONCEPT_A, 5)
    ]


def test_multi_concept_diagnosis_enters_each_group_once(service, repository) -> None:
    repository.add_facts(
        [
            fact(number, concept_ids=(CONCEPT_A, CONCEPT_B, CONCEPT_A))
            for number in range(1, 6)
        ]
    )

    result = service.course_analytics(OWNER, COURSE_A, AnalyticsFilters())

    assert [(group.concept_id, group.diagnosis_count) for group in result.groups] == [
        (CONCEPT_A, 5),
        (CONCEPT_B, 5),
    ]


def test_duplicate_source_rows_do_not_double_count_one_diagnosis(service, repository) -> None:
    records = [fact(number, independent_repaired=True) for number in range(1, 6)]
    repository.add_facts([*records, records[0]])

    result = service.course_analytics(OWNER, COURSE_A, AnalyticsFilters())

    assert result.groups[0].diagnosis_count == 5
    assert result.groups[0].independent_repair_count == 5


def test_time_range_is_start_inclusive_and_end_exclusive(service, repository) -> None:
    repository.add_facts([fact(number) for number in range(0, 7)])
    filters = AnalyticsFilters(
        start_at=BASE_TIME + timedelta(hours=1),
        end_at=BASE_TIME + timedelta(hours=6),
    )

    result = service.course_analytics(OWNER, COURSE_A, filters)

    assert result.sample_size == 5
    assert result.groups[0].diagnosis_count == 5


@pytest.mark.parametrize(
    "filters",
    [
        AnalyticsFilters(start_at=BASE_TIME, end_at=BASE_TIME),
        AnalyticsFilters(
            start_at=BASE_TIME + timedelta(seconds=1), end_at=BASE_TIME
        ),
    ],
)
def test_invalid_time_order_is_rejected(service, filters) -> None:
    with pytest.raises(InvalidAnalyticsFilters):
        service.course_analytics(OWNER, COURSE_A, filters)


def test_public_analytics_never_serializes_subject_keys(service, repository) -> None:
    repository.add_facts(
        [fact(number, subject_key=f"private-student-{number}") for number in range(1, 6)]
    )

    payload = json.dumps(
        service.course_analytics(OWNER, COURSE_A, AnalyticsFilters()).model_dump(
            mode="json"
        )
    )

    assert "private-student" not in payload
    assert "subject_key" not in payload
