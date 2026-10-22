"""Explicit synthetic demo composition; SQL and Runner remain the real adapters."""
import os
from sqlalchemy.engine import make_url
from app.auth.models import Role, User
from app.courses.models import Course, Enrollment, Exercise
from app.knowledge.models import Concept, MisconceptionPattern
from app.model_gateway.base import DiagnosisModelOutput, HintModelOutput, ExplanationModelOutput, ProviderFailure
from app.persistence.repositories import create_sql_repositories

COURSE = "cangjie-language-design"
CONCEPT = "cj.pattern-match.exhaustiveness"
MISCONCEPTION = "cj.synthetic.match-non-exhaustive"
REFERENCE = "synthetic-demo:match-coverage"
OUTLINES = ["列出选择器的所有可能值。", "将所有枚举构造器与现有分支逐项对照。", "检查遗漏分支的返回类型与其他分支是否一致。", "逐个说明每个构造器如何被分支覆盖。"]


def validate_demo_target(database_url, environment, enabled):
    url = make_url(database_url)
    demo = environment == "development" and url.host == "postgres" and url.port == 5432 and url.database == "wave4_demo"
    test = environment == "test" and url.host == "127.0.0.1" and url.port == 55440 and url.database == "wave4_browser"
    if enabled != "1" or not url.drivername.startswith("postgresql") or not (demo or test):
        raise ValueError("Synthetic demo refuses production and foreign database targets")


def seed(database_url, *, environment, enabled, password):
    validate_demo_target(database_url, environment, enabled)
    if not password:
        raise ValueError("Explicit synthetic actor password required")
    repos = create_sql_repositories(database_url)
    actors = [("demo-teacher", Role.TEACHER)] + [(f"demo-student-{i}", Role.STUDENT) for i in range(1, 7)]
    for uid, role in actors:
        existing = repos.users.find_by_username(uid)
        if existing is None:
            repos.users.add(User.with_password(uid, uid, password, role))
        elif existing.user_id != uid or existing.role is not role:
            raise ValueError("Synthetic identity conflicts with existing state")
    course = repos.courses.get(COURSE)
    if course is None:
        repos.courses.add(Course(COURSE, "仓颉语言设计", "demo-teacher"))
    elif course.owner_teacher_id != "demo-teacher":
        raise ValueError("Synthetic course conflicts with existing owner")
    exercise = next((item for item in repos.courses.list_exercises(COURSE) if item.exercise_id == "demo-match"), None)
    if exercise is None:
        repos.courses.add_exercise(Exercise("demo-match", COURSE, "合成演示：match 分支穷举", True))
    elif exercise.course_id != COURSE or not exercise.is_published:
        raise ValueError("Synthetic exercise conflicts with existing state")
    for uid, role in actors:
        if role is Role.STUDENT:
            repos.enrollments.add(Enrollment(COURSE, uid, role))
    if not repos.knowledge.list_concepts(COURSE):
        source = {"kind":"course_material", "references":[REFERENCE], "toolchain_version":"cjc 1.2.0 synthetic demo fixture",
            "verification_status":"unverified", "note":"Synthetic approval fixture; not teacher gold, real review or model evidence."}
        concept = Concept.model_validate({"id":CONCEPT, "topic":"enum_match", "title":"合成课程知识：match 穷举",
            "summary":"match 应覆盖选择器的所有可能值。", "review_status":"approved", "reviewed_by":"demo-teacher",
            "review_note":"Synthetic fixture approval only.", "source":source})
        misconception = MisconceptionPattern.model_validate({"id":MISCONCEPTION, "topic":"enum_match", "title":"合成误区：遗漏枚举分支",
            "root_concept_id":CONCEPT, "trigger_evidence":[{"kind":"compiler_diagnostic", "pattern":"non-exhaustive patterns", "strength":"strong"}],
            "explanation":"match 应覆盖选择器的所有可能值。", "hint_ladder":[{"level":i+1,"outline":text} for i,text in enumerate(OUTLINES)],
            "review_status":"approved", "reviewed_by":"demo-teacher", "source":source,
            "verification":{"method":"knowledge_base_summary", "toolchain_version":"1.2.0", "note":"Synthetic fixture; actual compiler rehearsal recorded separately."}})
        repos.knowledge.load_course(COURSE, [concept], [], [misconception])
    elif {item.id for item in repos.knowledge.list_concepts(COURSE)} != {CONCEPT}:
        raise ValueError("Refuse to replace existing course knowledge")
    return repos


class DeliveryMockProvider:
    """Repeatable fixtures, no model/network calls and no prompt retention."""
    fixed_mock = True

    def generate_diagnosis(self, request):
        knowledge = next((item for item in request.knowledge if item.misconception_id == MISCONCEPTION), None)
        if knowledge is None:
            raise ProviderFailure("Synthetic demo knowledge unavailable")
        evidence = [{"kind":"approved_knowledge", "summary":"合成课程证据：match 应覆盖全部可能值。",
            "misconception_id":MISCONCEPTION, "source_reference":REFERENCE}]
        if request.execution.diagnostics:
            evidence.append({"kind":"compiler_diagnostic", "summary":"真实编译器反馈", "diagnostic_index":0})
        return DiagnosisModelOutput.model_validate({"category":"conceptual", "locations":[{"file":"main.cj","start_line":3,"end_line":3}],
            "concept_ids":[CONCEPT], "root_cause":"合成 Mock 诊断：请核对 match 是否覆盖全部枚举分支。", "evidence":evidence,
            "confidence":.92, "recommended_hint_level":1})

    def generate_hint(self, request):
        return HintModelOutput(level=request.level, content="合成 Mock 提示：" + OUTLINES[request.level-1])

    def check_explanation(self, request):
        return ExplanationModelOutput(understands=True, concept_ids=(CONCEPT,), confidence=.91,
            evidence_summary="合成 Mock 理解检查固定通过；不代表模型能力。", feedback="合成 Mock 验证通过；正式教学须独立评测。")


def create_demo_app():
    validate_demo_target(os.environ.get("DATABASE_URL", ""), os.environ.get("APP_ENV"), os.environ.get("KNOWBOUND_SYNTHETIC_DEMO"))
    from app.main import create_app
    return create_app(model_provider=DeliveryMockProvider())


if __name__ == "__main__":
    repositories = seed(os.environ.get("DATABASE_URL", ""), environment=os.environ.get("APP_ENV"),
        enabled=os.environ.get("KNOWBOUND_SYNTHETIC_DEMO"), password=os.environ.get("DEMO_PASSWORD"))
    repositories.memory_uow.sessions.kw["bind"].dispose()
    print("Synthetic actors, enrollment, exercise and fixture knowledge ready; no diagnoses or repair facts prefilled.")
