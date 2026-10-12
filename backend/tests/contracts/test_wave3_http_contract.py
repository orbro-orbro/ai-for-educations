from tests.security.security_support import build_harness, STUDENT_A, TEACHER


def test_deleted_diagnosis_keeps_valid_sanitized_public_tombstone():
    h = build_harness()
    old = h.memories["a"]
    h.state.deletion_service.delete_memory(STUDENT_A, old.memory_id, request_id="delete", idempotency_key="delete")
    response = h.request("GET", "/submissions/submission-a/diagnosis")
    assert response.status_code == 200
    data = response.json()
    assert data["root_cause"] and data["locations"] and data["concept_ids"] and data["evidence"]
    assert old.content not in response.text


def test_knowledge_omits_absent_nonnullable_note_and_rejects_explicit_null():
    h = build_harness()
    result = h.request("GET", "/teacher/courses/course-a/concepts", actor=TEACHER)
    assert result.status_code == 200
    assert all("note" not in item["source"] for item in result.json())
    body = {"id":"cj.synthetic.null-note", "topic":"enum_match", "title":"Synthetic", "summary":"Synthetic", "source":{
        "kind":"teacher_authored", "references":["synthetic evidence"], "toolchain_version":"1.2.0", "verification_status":"teacher_asserted", "note":None}}
    response = h.request("POST", "/teacher/courses/course-a/concepts", actor=TEACHER, body=body)
    assert response.status_code == 422
    assert set(response.json()) == {"code", "message", "request_id"}
