// No page.route or response fulfilment: official API, PG, and isolated Runner.
import { expect, test, type Page } from "@playwright/test";
import { resolve } from "node:path";
const wave4 = process.env.WAVE4_TEST_MODE === "1";
const api=wave4 ? "http://127.0.0.1:8218" : "http://127.0.0.1:8198";
const snapshots=resolve(import.meta.dirname, wave4 ? `../../.superpowers/sdd/2026-10-12-wave4-task11-delivery/evidence/browser-${Date.now()}` : "../../docs/experiments/wave3-browser");
async function login(page:Page,user:string){
  await page.goto("/");await page.getByLabel("用户名").fill(user);await page.getByLabel("密码",{exact:true}).fill("synthetic-password");
  await page.getByRole("button",{name:"登录",exact:true}).click();
}
async function authenticated(page:Page,path:string,method="GET",body?:unknown){
  return page.evaluate(async({api,path,method,body})=>{
    const token=JSON.parse(localStorage.getItem("knowbound.session")!).accessToken;
    const response=await fetch(api+path,{method,headers:{Authorization:"Bearer "+token,"Content-Type":"application/json","Idempotency-Key":"synthetic-browser-key"},...(body===undefined?{}:{body:JSON.stringify(body)})});
    return {status:response.status,body:await response.json().catch(()=>null)};
  },{api,path,method,body});
}
test("real teacher SQL threshold, denial, authoritative review and logout",async({page})=>{
  await page.setViewportSize({width:1440,height:1000});await login(page,"teacher-a");
  await expect(page.getByRole("heading",{name:"课程诊断台"})).toBeVisible();
  await page.getByRole("combobox",{name:"课程",exact:true}).selectOption("course-b");await expect(page.getByText("样本不足",{exact:true})).toBeVisible();
  await expect(page.getByText("有效匿名样本",{exact:true})).toHaveCount(0);
  await page.getByRole("combobox",{name:"课程",exact:true}).selectOption("course-a");await expect(page.getByText("有效匿名样本",{exact:true})).toBeVisible();
  await expect(page.locator(".signal-summary strong")).toHaveText("5");
  expect((await authenticated(page,"/me/memories?course_id=course-a")).status).toBe(404);
  expect((await authenticated(page,"/submissions/sub-browser-course-a-0/diagnosis")).status).toBe(404);
  expect((await authenticated(page,"/teacher/courses/unknown/analytics")).status).toBe(404);
  expect((await authenticated(page,"/teacher/courses/course-a/analytics?start_at=invalid")).status).toBe(422);
  await expect(page.locator("main")).not.toContainText("PRIVATE_WAVE3_SENTINEL");
  let reviews=0;page.on("request",r=>{if(r.method()==="POST"&&r.url().endsWith("/review"))reviews++;});
  const first=page.locator(".review-item").first();await first.getByLabel("复核理由").fill("合成复核：已审核课程证据支持此概念。");
  const reviewResponse=page.waitForResponse(r=>r.request().method()==="POST"&&r.url().endsWith("/review"));
  await first.getByRole("button",{name:"提交复核"}).evaluate((b:HTMLButtonElement)=>{b.click();b.click();});
  const result=await reviewResponse;expect(result.status()).toBe(200);const reviewed=await result.json();
  await expect(first.getByText("已处理",{exact:true})).toBeVisible();expect(reviews).toBe(1);
  const queue=await authenticated(page,"/teacher/courses/course-a/review-queue");expect(queue.body.items.some((i:{diagnosis_id:string})=>i.diagnosis_id===reviewed.diagnosis_id)).toBe(false);
  expect((await authenticated(page,`/teacher/diagnoses/${reviewed.diagnosis_id}/review`,"POST",{decision:"overturned",reason:"合成不同复核"})).status).toBe(409);
  await page.screenshot({path:resolve(snapshots,"teacher-desktop.png"),fullPage:true});
  await page.setViewportSize({width:390,height:844});await expect(page.getByRole("button",{name:"退出",exact:true})).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
  await page.screenshot({path:resolve(snapshots,"teacher-mobile.png"),fullPage:true});
  const token=await page.evaluate(()=>JSON.parse(localStorage.getItem("knowbound.session")!).accessToken);
  await page.getByRole("button",{name:"退出",exact:true}).click();await expect(page.getByRole("button",{name:"登录",exact:true})).toBeVisible();
  expect(await page.evaluate(async({api,token})=>(await fetch(api+"/courses",{headers:{Authorization:"Bearer "+token}})).status,{api,token})).toBe(401);
});
test("real student learning, compiler, hints and owned memory lifecycle",async({page})=>{
  test.setTimeout(90_000);await page.setViewportSize({width:390,height:844});await login(page,"synthetic-student-0");
  await expect(page.getByRole("heading",{name:"学生工作台"})).toBeVisible();
  await page.goto("/teacher/courses/course-a");await expect(page.getByRole("heading",{name:"课程诊断台"})).toHaveCount(0);
  expect((await authenticated(page,"/teacher/courses/course-a/analytics")).status).toBe(404);
  await page.getByRole("combobox",{name:"课程",exact:true}).selectOption("course-a");
  await expect(page.getByText("正在准备课程与练习…",{exact:true})).toHaveCount(0);
  await page.getByLabel("仓颉源码").fill("enum Choice { A | B }\nmain() {\n  match (Choice.A) { case A => 1 }\n}");
  await page.getByRole("button",{name:"提交并运行"}).click();await expect(page.getByText("编译未通过",{exact:true})).toBeVisible({timeout:30_000});
  await expect(page.getByRole("heading",{name:"结构化误区诊断"})).toBeVisible();
  await page.getByRole("button",{name:"请求下一层提示"}).click();await expect(page.getByText(/第 .* 级提示/)).toBeVisible();
  await page.getByLabel("我对错误原因的解释").fill("合成解释：match 必须覆盖全部枚举构造器。");
  await page.getByRole("button",{name:"验证我的理解"}).click();await expect(page.getByText("理解验证通过",{exact:true})).toBeVisible();
  let accepts=0;page.on("request",r=>{if(r.method()==="POST"&&r.url().endsWith("/accept"))accepts++;});
  const button=page.getByRole("button",{name:"接受记忆建议",exact:true}).first();await expect(button).toBeVisible();
  await button.evaluate((b:HTMLButtonElement)=>{b.click();b.click();});await expect(page.getByText("已保存到个人记忆",{exact:true})).toBeVisible();expect(accepts).toBe(1);
  await page.getByRole("button",{name:"纠正记忆",exact:true}).first().click();await page.getByLabel("纠正后的记忆").fill("合成纠正：检查每一个枚举分支。");
  await page.getByRole("button",{name:"保存纠正"}).click();await expect(page.getByText("记忆已按你的表述更新",{exact:true})).toBeVisible();
  await page.screenshot({path:resolve(snapshots,"student-mobile.png"),fullPage:true});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
  await page.getByRole("button",{name:"删除记忆",exact:true}).first().click();await page.getByRole("button",{name:"确认删除",exact:true}).click();
  await expect(page.getByText("记忆已删除",{exact:true})).toBeVisible();
  await page.getByLabel("仓颉源码").fill("enum Choice { A | B }\nmain() {\n  match (Choice.A) { case A => println(\"A\")\n case B => println(\"B\") }\n}");
  await page.getByRole("button",{name:"提交并运行"}).click();await expect(page.getByText("执行成功",{exact:true})).toBeVisible({timeout:30_000});
  await page.getByLabel("我对错误原因的解释").fill("合成解释：两个构造器现在都得到处理。");
  await page.getByRole("button",{name:"验证我的理解"}).click();await expect(page.getByRole("button",{name:"拒绝记忆建议",exact:true}).first()).toBeVisible();
  await page.getByRole("button",{name:"拒绝记忆建议",exact:true}).first().click();await expect(page.getByText("已拒绝这条记忆建议",{exact:true})).toBeVisible();
  await page.getByRole("button",{name:"退出",exact:true}).click();await expect(page.getByRole("button",{name:"登录",exact:true})).toBeVisible();
});
test("real SQL logout failure is sanitized and remains retryable",async({page})=>{
  await login(page,"teacher-a");await expect(page.getByRole("heading",{name:"课程诊断台"})).toBeVisible();
  const token=await page.evaluate(()=>JSON.parse(localStorage.getItem("knowbound.session")!).accessToken);
  // Fixture-only fault header is sent by the API context; production CORS stays unchanged.
  const response=await page.request.post(api+"/auth/logout",{headers:{Authorization:"Bearer "+token,"X-Wave3-Synthetic-Fault":"revocation-write"}});
  const failed={status:response.status(),body:await response.json()};
  expect(failed.status).toBe(503);expect(failed.body.code).toBe("STORAGE_UNAVAILABLE");expect(failed.body.request_id).toBeTruthy();
  expect(JSON.stringify(failed.body)).not.toContain("SYNTHETIC_PRIVATE_STORAGE_DETAIL");
  expect((await authenticated(page,"/courses")).status).toBe(200);
  await page.getByRole("button",{name:"退出",exact:true}).click();await expect(page.getByRole("button",{name:"登录",exact:true})).toBeVisible();
});
