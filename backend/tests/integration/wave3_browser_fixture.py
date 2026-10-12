"""Test-process-only official composition: synthetic PG + Mock + real Runner."""
import os
from contextvars import ContextVar
from sqlalchemy import event
from sqlalchemy.exc import OperationalError
from datetime import datetime, UTC
from itertools import repeat
from app.main import create_app
from app.model_gateway.mock import DeterministicMockProvider
from tests.integration.wave3_support import Wave3PG, postgres_url, runner_endpoint, browser_origins, SECRET, NOW

os.environ.pop("DATABASE_URL",None)
pg=Wave3PG("wave3_browser")
facts=[dict(diagnosis_id=f"browser-{course}-{i}",subject_key=f"synthetic-subject-{i}",course_id=course,
    concept_id="cj.pattern-match.exhaustiveness",exercise_id="exercise-a" if course=="course-a" else "exercise-b",
    category="conceptual",created_at=NOW.isoformat(),independently_repaired=False)
    for course,n in [("course-a",5),("course-b",4)] for i in range(n)]
pg.seed_vector_facts(facts)
os.environ.update(APP_ENV="test",DATABASE_URL=postgres_url("wave3_browser"),AUTH_TOKEN_SECRET=SECRET,
    RUNNER_ENDPOINT=runner_endpoint(),RUNNER_TIMEOUT_SECONDS="15",
    CORS_ALLOWED_ORIGINS=browser_origins())
output={"category":"conceptual","locations":[{"file":"main.cj","start_line":3,"end_line":3}],
    "concept_ids":["cj.pattern-match.exhaustiveness"],"root_cause":"合成诊断：match 应覆盖全部枚举分支。",
    "evidence":[{"kind":"approved_knowledge","summary":"synthetic model summary",
        "misconception_id":"cj.synthetic.pattern-match.exhaustiveness","source_reference":"fixture:course-a:match"}],
    "confidence":.92,"recommended_hint_level":1}
provider=DeterministicMockProvider(diagnoses=repeat(output,20),
    hints=repeat({"level":2,"content":"合成提示：逐项检查枚举构造器。"},20),
    explanations=repeat({"understands":True,"concept_ids":["cj.pattern-match.exhaustiveness"],
        "evidence_summary":"合成理解证据","confidence":.91,"feedback":"合成验证：解释覆盖了穷举要求。"},20))
app=create_app(model_provider=provider)
_failure = ContextVar("synthetic_browser_storage_failure", default=False)

@event.listens_for(app.state.memory_audit._uow.sessions.kw["bind"], "before_cursor_execute")
def fail_synthetic_revocation_write(connection, cursor, statement, parameters, context, many):
    if _failure.get() and statement.lstrip().upper().startswith("INSERT INTO TOKEN_REVOCATIONS"):
        raise OperationalError(statement, None, RuntimeError("SYNTHETIC_PRIVATE_STORAGE_DETAIL"))

@app.middleware("http")
async def synthetic_storage_fault(request, next_handler):
    # Fault injection is test-module-only. Core authorization and SQL stores
    # remain real; their normal storage-error handling generates the response.
    token = _failure.set(request.headers.get("X-Wave3-Synthetic-Fault") == "revocation-write")
    try:
        return await next_handler(request)
    finally:
        _failure.reset(token)
