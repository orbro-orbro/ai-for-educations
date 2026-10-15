// Real Docker API + PostgreSQL + per-job Runner; no response interception.
import { test, expect, type Page, type APIRequestContext } from "@playwright/test";
import { readFileSync, mkdirSync, writeFileSync } from "node:fs";
import { resolve, dirname } from "node:path";

const root = resolve(import.meta.dirname, "../..");
const api = "http://127.0.0.1:8208";
const ui = "http://127.0.0.1:5209";
const course = "cangjie-language-design";
const password = readFileSync(resolve(root, ".delivery/demo.env"), "utf8").split(/\r?\n/).find(line => line.startsWith("DEMO_PASSWORD="))!.slice(14);
const badSource = readFileSync(resolve(root, "data/demo/match-error.cj"), "utf8");
const fixedSource = readFileSync(resolve(root, "data/demo/match-fixed.cj"), "utf8");

async function login(page: Page, user: string) {
  await page.goto(ui);
  await page.getByLabel("用户名").fill(user);
  await page.getByLabel("密码", { exact:true }).fill(password);
  await page.getByRole("button", { name:"登录", exact:true }).click();
}
async function tokenFor(request: APIRequestContext, username: string) {
  const response = await request.post(api + "/auth/login", { data:{ username, password } });
  expect(response.status()).toBe(200);
  return (await response.json()).access_token as string;
}
async function call(request: APIRequestContext, token: string, method: string, path: string, data?: unknown) {
  return request.fetch(api + path, { method, headers:{ Authorization:"Bearer " + token, "Idempotency-Key":"synthetic-delivery-" + crypto.randomUUID() }, ...(data === undefined ? {} : {data}) });
}

test("all 15 synthetic competition steps through the deployed real system", async ({ page, browser, request }, info) => {
  const windowStart = new Date().toISOString();
  const timings: Array<{step:string;start:string;end:string;duration_ms:number;status:string}> = [];
  const observations: Record<string, unknown> = { data_nature:"synthetic; deterministic Mock model; real SQL and isolated Runner", window_start:windowStart };
  async function step(name: string, action: () => Promise<void>) {
    await test.step(name, async () => {
      const start = new Date(); let status="failed";
      try { await action(); status="passed"; }
      finally { const end=new Date(); timings.push({step:name,start:start.toISOString(),end:end.toISOString(),duration_ms:end.getTime()-start.getTime(),status}); }
    });
  }
  let token="", original="", diagnosis="", retry="", memory="";
  let teacherContext: Awaited<ReturnType<typeof browser.newContext>> | undefined;
  try {
    // Repeatable synthetic-fixture cleanup uses its owner's real API, preserving
    // source deletion receipts and all previous rehearsal evidence.
    const fixtureToken=await tokenFor(request,"demo-student-1");
    const existing=await call(request,fixtureToken,"GET",`/me/memories?course_id=${course}&purpose=learning_support`);
    expect(existing.status()).toBe(200);
    for(const item of await existing.json()) {
      expect(item.owner_user_id).toBe("demo-student-1"); expect(item.course_id).toBe(course);
      expect((await call(request,fixtureToken,"DELETE",`/memories/${item.memory_id}`)).status()).toBe(202);
    }
    await step("01 学生登录课程", async () => {
      await login(page, "demo-student-1");
      await expect(page.getByRole("heading",{name:"学生工作台"})).toBeVisible();
      await expect(page.getByRole("option",{name:"仓颉语言设计",exact:true})).toBeAttached();
      await expect(page.getByRole("note")).toContainText("确定性 Mock");
      token=await page.evaluate(()=>JSON.parse(localStorage.getItem("knowbound.session")!).accessToken);
    });
    await step("02 提交典型误区代码", async () => {
      await page.getByLabel("仓颉源码").fill(badSource);
      const response=page.waitForResponse(r=>r.request().method()==="POST" && r.url().endsWith("/exercises/demo-match/submissions"));
      await page.getByRole("button",{name:"提交并运行",exact:true}).click();
      const submitted=await response; expect(submitted.status()).toBe(201); original=(await submitted.json()).submission_id;
    });
    await step("03 真实隔离编译反馈", async () => {
      await expect(page.getByText("编译未通过",{exact:true})).toBeVisible({timeout:30_000});
      const response=await call(request,token,"GET",`/submissions/${original}/execution-result`);
      expect(response.status()).toBe(200); const result=await response.json();
      expect(result.status).toBe("compile_failed"); expect(result.toolchain.cjc).toBe("1.2.0");
      expect(result.diagnostics.some((d:{message:string})=>d.message.includes("non-exhaustive"))).toBe(true);
      observations.compiler_failure=result;
    });
    await step("04 结构化概念诊断", async () => {
      await expect(page.getByRole("heading",{name:"结构化误区诊断"})).toBeVisible();
      const response=await call(request,token,"GET",`/submissions/${original}/diagnosis`);
      expect(response.status()).toBe(200); const value=await response.json(); diagnosis=value.diagnosis_id;
      expect(value.concept_ids).toContain("cj.pattern-match.exhaustiveness");
      observations.original_submission_id=original; observations.diagnosis_id=diagnosis;
    });
    await step("05 逐级提示", async () => {
      for(const level of [1,2]) { await page.getByRole("button",{name:"请求下一层提示"}).click(); await expect(page.getByText(`第 ${level} 级提示`,{exact:true})).toBeVisible(); }
    });
    await step("06 修改并重新隔离执行", async () => {
      await page.getByLabel("仓颉源码").fill(fixedSource);
      const response=page.waitForResponse(r=>r.request().method()==="POST" && r.url().endsWith("/exercises/demo-match/submissions"));
      await page.getByRole("button",{name:"提交并运行",exact:true}).click();
      const submitted=await response; expect(submitted.status()).toBe(201); retry=(await submitted.json()).submission_id;
      await expect(page.getByText("执行成功",{exact:true})).toBeVisible({timeout:30_000});
    });
    await step("07 验证修复执行与正式关联", async () => {
      await expect(page.getByText("修复提交已关联原诊断",{exact:true})).toBeVisible();
      const response=await call(request,token,"GET",`/submissions/${retry}/execution-result`);
      expect(response.status()).toBe(200); const result=await response.json();
      expect(result.status).toBe("succeeded"); expect(result.stdout.trim()).toBe("2");
      observations.compiler_success=result; observations.retry_submission_id=retry;
    });
    await step("08 解释理解", async () => {
      await page.getByLabel("我对错误原因的解释").fill("合成解释：match 是表达式，必须覆盖 A 和 B 两个构造器，分支返回类型保持一致。");
      await page.getByRole("button",{name:"验证我的理解"}).click(); await expect(page.getByText("理解验证通过",{exact:true})).toBeVisible();
    });
    await step("09 本人确认前仅建议", async () => {
      await expect(page.getByRole("button",{name:"接受记忆建议",exact:true})).toBeVisible();
      const response=await call(request,token,"GET",`/me/memories?course_id=${course}&purpose=learning_support`);
      expect(response.status()).toBe(200); expect(await response.json()).toEqual([]);
    });
    await step("10 接受、纠正并拒绝另一建议", async () => {
      const accepted=page.waitForResponse(r=>r.request().method()==="POST" && r.url().endsWith("/accept"));
      await page.getByRole("button",{name:"接受记忆建议",exact:true}).click(); memory=(await (await accepted).json()).memory_id;
      await expect(page.getByText("已保存到个人记忆",{exact:true})).toBeVisible();
      await page.getByRole("button",{name:"纠正记忆",exact:true}).click();
      await page.getByLabel("纠正后的记忆").fill("合成私人记忆：先列出枚举的全部构造器，再逐项核对 match 分支。");
      const corrected=page.waitForResponse(r=>r.request().method()==="PATCH" && r.url().includes("/memories/"));
      await page.getByRole("button",{name:"保存纠正",exact:true}).click(); memory=(await (await corrected).json()).memory_id;
      await expect(page.getByText("记忆已按你的表述更新",{exact:true})).toBeVisible();
      await page.getByRole("button",{name:"验证我的理解"}).click();
      await expect(page.getByRole("button",{name:"拒绝记忆建议",exact:true})).toBeVisible();
      await page.getByRole("button",{name:"拒绝记忆建议",exact:true}).click();
      await expect(page.getByText("已拒绝这条记忆建议",{exact:true})).toBeVisible();
      observations.corrected_memory_id=memory;
      await page.screenshot({path:info.outputPath("student-synthetic.png"),fullPage:true});
    });
    await step("11 跨学生访问拒绝", async () => {
      const other=await tokenFor(request,"demo-student-2");
      expect((await call(request,other,"PATCH",`/memories/${memory}`,{content:"synthetic unauthorized correction"})).status()).toBe(404);
      const response=await call(request,other,"GET",`/me/memories?course_id=${course}&purpose=learning_support`);
      expect(response.status()).toBe(200); expect(await response.json()).toEqual([]);
    });
    const teacher=await tokenFor(request,"demo-teacher");
    await step("12 教师私人数据拒绝", async () => {
      expect((await call(request,teacher,"GET",`/me/memories?course_id=${course}`)).status()).toBe(404);
      expect((await call(request,teacher,"GET",`/submissions/${original}/diagnosis`)).status()).toBe(404);
      expect((await call(request,teacher,"PATCH",`/memories/${memory}`,{content:"synthetic unauthorized teacher correction"})).status()).toBe(404);
    });
    await step("13 五人阈值与自主修复权威计数", async () => {
      const path=`/teacher/courses/${course}/analytics?start_at=${encodeURIComponent(windowStart)}`;
      const suppressed=await call(request,teacher,"GET",path); expect(suppressed.status()).toBe(200);
      const low=await suppressed.json(); expect(low.status).toBe("insufficient_sample"); expect(low).not.toHaveProperty("sample_size");
      for(const index of [2,3,4,5]) {
        const actor=await tokenFor(request,`demo-student-${index}`);
        const submitted=await call(request,actor,"POST","/exercises/demo-match/submissions",{source_files:[{path:"main.cj",content:badSource}],entrypoint:"main.cj",is_formal:true});
        expect(submitted.status()).toBe(201);
        const result=await call(request,actor,"GET",`/submissions/${(await submitted.json()).submission_id}/execution-result`);
        expect((await result.json()).status).toBe("compile_failed");
      }
      const response=await call(request,teacher,"GET",path); expect(response.status()).toBe(200);
      const aggregate=await response.json(); expect(aggregate.status).toBe("available"); expect(aggregate.sample_size).toBe(5);
      expect(aggregate.groups.reduce((n:number,g:{independent_repair_count:number})=>n+g.independent_repair_count,0)).toBe(1);
      observations.analytics=aggregate;
      teacherContext=await browser.newContext(); const teacherPage=await teacherContext.newPage(); await login(teacherPage,"demo-teacher");
      await expect(teacherPage.getByRole("heading",{name:"课程诊断台"})).toBeVisible();
      await expect(teacherPage.locator(".signal-summary strong")).toHaveText("5");
      await expect(teacherPage.locator("main")).not.toContainText("合成私人记忆");
      await teacherPage.screenshot({path:info.outputPath("teacher-synthetic.png"),fullPage:true});
    });
    await step("14 删除后相同查询反查", async () => {
      const path=`/me/memories?course_id=${course}&purpose=learning_support&query=match`;
      const before=await call(request,token,"GET",path); expect((await before.json()).some((m:{memory_id:string})=>m.memory_id===memory)).toBe(true);
      await page.getByRole("button",{name:"删除记忆",exact:true}).click(); await page.getByRole("button",{name:"确认删除",exact:true}).click();
      await expect(page.getByText("记忆已删除",{exact:true})).toBeVisible();
      const after=await call(request,token,"GET",path); expect(after.status()).toBe(200); expect(await after.json()).toEqual([]);
      observations.reverse_query=path; observations.reverse_lookup_absent=true;
      await page.screenshot({path:info.outputPath("deleted-synthetic.png"),fullPage:true});
    });
    await step("15 退出后旧令牌拒绝", async () => {
      await page.getByRole("button",{name:"退出",exact:true}).click(); await expect(page.getByRole("button",{name:"登录",exact:true})).toBeVisible();
      expect((await call(request,token,"GET","/courses")).status()).toBe(401);
      expect(await page.evaluate(()=>localStorage.getItem("knowbound.session"))).toBeNull(); observations.logout_replay_status=401;
    });
  } finally {
    await teacherContext?.close();
    const path=info.outputPath("rehearsal.json"); mkdirSync(dirname(path),{recursive:true});
    writeFileSync(path,JSON.stringify({observations,timings},null,2));
  }
});
