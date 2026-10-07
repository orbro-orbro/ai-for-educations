// Real local HTTP router/auth/policy; in-memory authority + deterministic mocks.
// These tests do not represent PostgreSQL, Task 8 analytics, or browser UI.
import { expect, test, type APIRequestContext, type APIResponse } from "@playwright/test";

async function login(request: APIRequestContext, user: string) {
  const response = await request.post("/auth/login", { data: { username: user, password: "synthetic-password" } });
  expect(response.status()).toBe(200);
  const body = await response.json();
  expect(body.actor.user_id).toBe(user);
  return { Authorization: `Bearer ${body.access_token}`, "Idempotency-Key": "security-e2e" };
}

async function denial(response: APIResponse) {
  expect(response.status()).toBe(404);
  const body = await response.json();
  expect(Object.keys(body).sort()).toEqual(["code", "message", "request_id"]);
  expect(body.code).toBe("RESOURCE_NOT_AVAILABLE");
  expect(body.message).toBe("Resource is not available.");
  expect(typeof body.request_id).toBe("string");
  return { code: body.code, message: body.message };
}

test("student directly accessing a teacher entry receives uniform denial", async ({ request }) => {
  const headers = await login(request, "student-a");
  expect(await denial(await request.get("/teacher/courses/course-a/concepts", { headers })))
    .toEqual(await denial(await request.get("/teacher/courses/unknown/concepts", { headers })));
});

test("teacher cannot list private student memories", async ({ request }) => {
  const headers = await login(request, "teacher-a");
  await denial(await request.get("/me/memories?course_id=course-a", { headers }));
});

for (const suffix of ["", "/execution-result", "/diagnosis"]) {
  test(`student A cannot enumerate student B submissions${suffix}`, async ({ request }) => {
    const headers = await login(request, "student-a");
    expect(await denial(await request.get(`/submissions/submission-b${suffix}`, { headers })))
      .toEqual(await denial(await request.get(`/submissions/unknown${suffix}`, { headers })));
  });
}

test("direct protected URL without a token returns authentication failure", async ({ request }) => {
  const response = await request.get("/submissions/submission-a");
  expect(response.status()).toBe(401);
  expect((await response.json()).code).toBe("AUTHENTICATION_FAILED");
});

for (const role of ["student-b", "teacher-a"]) {
  for (const method of ["PATCH", "DELETE"]) {
    test(`${role} cannot ${method} another student's memory`, async ({ request }) => {
      const owner = await login(request, "student-a");
      const memories = await (await request.get("/me/memories?course_id=course-a", { headers: owner })).json();
      const headers = await login(request, role);
      const options = { method, headers, ...(method === "PATCH" ? { data: { content: "unauthorized replacement" } } : {}) };
      expect(await denial(await request.fetch(`/memories/${memories[0].memory_id}`, options)))
        .toEqual(await denial(await request.fetch("/memories/unknown", options)));
    });
  }
}

test("malformed sensitive input never appears in the public error", async ({ request }) => {
  const headers = await login(request, "student-a");
  const marker = "PRIVATE_ERROR_MARKER_e2e";
  const response = await request.post("/exercises/exercise-a/submissions", {
    headers, data: { owner_user_id: "student-b", source_files: [{ path: "../main.cj", content: marker }], entrypoint: "main.cj" },
  });
  expect(response.status()).toBe(422);
  const body = await response.json();
  expect(Object.keys(body).sort()).toEqual(["code", "message", "request_id"]);
  expect(JSON.stringify(body)).not.toContain(marker);
  expect(JSON.stringify(body)).not.toMatch(/Traceback|psycopg|SQLAlchemy|password_hash/);
});

test("repeated concurrent acceptance produces one state change", async ({ request }) => {
  const headers = await login(request, "student-a");
  const proposals = await (await request.get("/me/memory-proposals?course_id=course-a", { headers })).json();
  const proposal = proposals.find((p: { status: string }) => p.status === "pending");
  expect(proposal).toBeDefined();
  const responses = await Promise.all([1, 2].map(() => request.post(`/memory-proposals/${proposal.proposal_id}/accept`, { headers })));
  expect(responses.map(r => r.status())).toEqual([200, 200]);
  const [first, second] = await Promise.all(responses.map(r => r.json()));
  expect(first.memory_id).toBe(second.memory_id);
  const memories = await (await request.get("/me/memories?course_id=course-a", { headers })).json();
  expect(memories.filter((m: { memory_id: string }) => m.memory_id === first.memory_id)).toHaveLength(1);
});

test("sharing grants only one summary and revocation immediately stops access", async ({ request }) => {
  const student = await login(request, "student-a");
  const teacher = await login(request, "teacher-a");
  const created = await request.post("/diagnoses/diagnosis-a/share-grants", { headers: student, data: { grantee_user_id: "teacher-a", purpose: "synthetic-e2e-review" } });
  expect(created.status()).toBe(201);
  const grant = await created.json();
  const path = `/share-grants/${grant.grant_id}/diagnosis-summary`;
  const shared = await request.get(path, { headers: teacher });
  expect(shared.status()).toBe(200);
  expect(Object.keys(await shared.json()).sort()).toEqual(["category", "concept_ids", "confidence", "course_id", "diagnosis_id", "owner_user_id", "root_cause"]);
  await denial(await request.get("/me/memories?course_id=course-a", { headers: teacher }));
  const revoked = await request.delete(`/share-grants/${grant.grant_id}`, { headers: student });
  expect(revoked.status()).toBe(200);
  expect((await revoked.json()).status).toBe("revoked");
  await denial(await request.get(path, { headers: teacher }));
});

test("logout makes a captured old bearer token unusable", async ({ request }) => {
  const headers = await login(request, "student-a");
  await request.post("/auth/logout", { headers });
  const replay = await request.get("/courses", { headers });
  expect(replay.status(), "Current main has no server-side logout/revocation contract; preserve this failure").toBe(401);
});
