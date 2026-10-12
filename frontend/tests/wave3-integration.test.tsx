import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../src/App";
import { CourseDashboard } from "../src/teacher/CourseDashboard";
import { ExercisePage } from "../src/student/ExercisePage";
import { ReviewQueue } from "../src/teacher/ReviewQueue";
import { ApiClient } from "../src/api/client";

const filters = {concept_id:null, exercise_id:null, start_at:null, end_at:null};
const json = (body:unknown,status=200) => new Response(JSON.stringify(body),{status,headers:{"Content-Type":"application/json"}});
function session() { localStorage.setItem("knowbound.session",JSON.stringify({accessToken:"synthetic-old-token",actor:{user_id:"teacher-a",role:"teacher"}})); }
function install(logout:()=>Response|Promise<Response>) {
  const fetcher = vi.fn(async (input:RequestInfo|URL, init:RequestInit={}) => {
    const url = new URL(String(input));
    if(url.pathname==="/auth/logout") return logout();
    if(url.pathname==="/courses") return json([{course_id:"course-a",title:"仓颉语言设计"}]);
    if(url.pathname.endsWith("/analytics")) return json({status:"insufficient_sample",course_id:"course-a",filters,minimum_sample_size:5});
    if(url.pathname.endsWith("/review-queue")) return json({course_id:"course-a",filters,items:[]});
    throw new Error("Unexpected synthetic request "+init.method+url.pathname);
  });
  vi.stubGlobal("fetch",fetcher);return fetcher;
}
describe("Wave 3 integration UI",()=>{
  beforeEach(()=>localStorage.clear());
  afterEach(()=>{cleanup();localStorage.clear();vi.unstubAllGlobals();});
  it("revokes the old token once before clearing a busy logout",async()=>{
    session();let finish!:(value:Response)=>void;
    const calls=install(()=>new Promise<Response>(resolve=>{finish=resolve;}));
    render(<App/>);await screen.findByText("样本不足");
    fireEvent.click(screen.getByRole("button",{name:"退出"}));
    fireEvent.click(screen.getByRole("button",{name:/退出/}));
    expect(localStorage.getItem("knowbound.session")).not.toBeNull();
    await waitFor(()=>expect(calls.mock.calls.filter(([url])=>String(url).endsWith("/auth/logout"))).toHaveLength(1));
    const call=calls.mock.calls.find(([url])=>String(url).endsWith("/auth/logout"))!;
    expect(new Headers(call[1]?.headers).get("Authorization")).toBe("Bearer synthetic-old-token");
    finish(new Response(null,{status:204}));
    await screen.findByRole("button",{name:"登录"});expect(localStorage.getItem("knowbound.session")).toBeNull();
  });
  it("keeps the session retryable after logout storage failure",async()=>{
    session();let attempts=0;
    install(()=>++attempts===1?json({code:"STORAGE_UNAVAILABLE",message:"Unavailable",request_id:"logout-synthetic-id"},503):new Response(null,{status:204}));
    render(<App/>);await screen.findByText("样本不足");fireEvent.click(screen.getByRole("button",{name:"退出"}));
    expect(await screen.findByText(/logout-synthetic-id/)).toBeInTheDocument();expect(localStorage.getItem("knowbound.session")).not.toBeNull();
    fireEvent.click(screen.getByRole("button",{name:"退出"}));await screen.findByRole("button",{name:"登录"});expect(attempts).toBe(2);
  });
  it("clears a token already rejected with 401",async()=>{
    session();install(()=>json({code:"AUTHENTICATION_FAILED",message:"Failed",request_id:"synthetic-id"},401));
    render(<App/>);await screen.findByText("样本不足");fireEvent.click(screen.getByRole("button",{name:"退出"}));
    await screen.findByRole("button",{name:"登录"});expect(localStorage.getItem("knowbound.session")).toBeNull();
  });
  it("uses next local midnight and adjacent half-open time windows",async()=>{
    session();const calls=install(()=>new Response(null,{status:204}));
    render(<App/>);await screen.findByText("样本不足");
    fireEvent.change(screen.getByLabelText("开始日期"),{target:{value:"2026-10-07"}});
    fireEvent.change(screen.getByLabelText("结束日期"),{target:{value:"2026-10-07"}});
    fireEvent.click(screen.getByRole("button",{name:"应用筛选"}));
    await waitFor(()=>expect(calls.mock.calls.filter(([url])=>String(url).includes("start_at="))).toHaveLength(3));
    const urls=calls.mock.calls.map(([url])=>new URL(String(url))).filter(url=>url.pathname.endsWith("/analytics")&&url.searchParams.has("start_at"));
    const start=new Date("2026-10-07T00:00:00");const end=new Date("2026-10-08T00:00:00");
    expect(urls[0].searchParams.get("end_at")).toBe(end.toISOString());
    expect(urls[1].searchParams.get("end_at")).toBe(start.toISOString());
    expect(urls[1].searchParams.get("start_at")).toBe(new Date(start.getTime()-(end.getTime()-start.getTime())).toISOString());
  });
  it("ignores stale queue responses after switching courses",async()=>{
    let resolveFirst!:(value:Response)=>void;
    vi.stubGlobal("fetch",vi.fn(async(input:RequestInfo|URL)=>{
      const u=new URL(String(input));
      if(u.pathname==="/courses")return json([{course_id:"course-a",title:"Course A"},{course_id:"course-b",title:"Course B"}]);
      if(u.pathname.endsWith("/analytics"))return json({status:"insufficient_sample",course_id:"course-a",filters,minimum_sample_size:5});
      if(u.pathname.includes("course-a/review-queue"))return new Promise<Response>(r=>{resolveFirst=r;});
      return json({course_id:"course-b",filters,items:[]});
    }));
    render(<CourseDashboard api={new ApiClient("http://localhost:8198",()=>"synthetic-token")}/>);
    await screen.findByText("样本不足");await waitFor(()=>expect(resolveFirst).toBeDefined());
    fireEvent.change(screen.getByLabelText("课程"),{target:{value:"course-b"}});
    await screen.findByText("当前没有待复核诊断");
    resolveFirst(json({course_id:"course-a",filters,items:[{queue_event_id:"stale",diagnosis_id:"stale",root_cause:"STALE_RESPONSE",concept_ids:[],evidence_summaries:[],confidence:.5}]}));
    await new Promise(r=>setTimeout(r,20));expect(screen.queryByText("STALE_RESPONSE")).not.toBeInTheDocument();
  });
  it("finishes student loading after a course switch aborts the initial request",async()=>{
    let first!:(value:Response)=>void;
    vi.stubGlobal("fetch",vi.fn(async(input:RequestInfo|URL)=>{
      const u=new URL(String(input));
      if(u.pathname==="/courses")return json([{course_id:"course-a",title:"Course A"},{course_id:"course-b",title:"Course B"}]);
      if(u.pathname.includes("course-a/exercises"))return new Promise<Response>(r=>{first=r;});
      if(u.pathname.includes("course-b/exercises"))return json([{exercise_id:"exercise-b",course_id:"course-b",title:"Exercise B"}]);
      if(u.pathname.startsWith("/me/"))return json([]);
      throw new Error("Unexpected request "+u.pathname);
    }));
    render(<ExercisePage api={new ApiClient("http://localhost:8198",()=>"synthetic-token")}/>);
    await waitFor(()=>expect(first).toBeDefined());
    expect(screen.getByText("正在准备课程与练习…")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox",{name:"课程"}),{target:{value:"course-b"}});
    await screen.findByRole("option",{name:"Exercise B"});
    await waitFor(()=>expect(screen.queryByText("正在准备课程与练习…")).not.toBeInTheDocument());
    first(json([{exercise_id:"stale",course_id:"course-a",title:"Stale exercise"}]));
    await new Promise(r=>setTimeout(r,20));
    expect(screen.queryByRole("option",{name:"Stale exercise"})).not.toBeInTheDocument();
  });
  it.each(["课程", "练习"])("allows a new submission after switching %s during a run",async(selection)=>{
    const submissions:string[]=[];
    vi.stubGlobal("fetch",vi.fn(async(input:RequestInfo|URL,init:RequestInit={})=>{
      const u=new URL(String(input));
      if(u.pathname==="/courses")return json([{course_id:"course-a",title:"Course A"},{course_id:"course-b",title:"Course B"}]);
      if(u.pathname.includes("course-a/exercises"))return json([{exercise_id:"exercise-a",course_id:"course-a",title:"Exercise A"},{exercise_id:"exercise-next",course_id:"course-a",title:"Exercise Next"}]);
      if(u.pathname.includes("course-b/exercises"))return json([{exercise_id:"exercise-b",course_id:"course-b",title:"Exercise B"}]);
      if(u.pathname.startsWith("/me/"))return json([]);
      if(u.pathname.startsWith("/exercises/") && u.pathname.endsWith("/submissions")){
        submissions.push(decodeURIComponent(u.pathname.split("/")[2]));
        return new Promise<Response>((_,reject)=>init.signal!.addEventListener("abort",()=>reject(new DOMException("Cancelled","AbortError")),{once:true}));
      }
      throw new Error("Unexpected request "+u.pathname);
    }));
    render(<ExercisePage api={new ApiClient("http://localhost:8198",()=>"synthetic-token")}/>);
    await screen.findByRole("option",{name:"Exercise A"});
    fireEvent.click(screen.getByRole("button",{name:"提交并运行"}));
    await waitFor(()=>expect(submissions).toEqual(["exercise-a"]));
    expect(screen.getByRole("button",{name:"正在隔离执行…"})).toBeDisabled();
    fireEvent.change(screen.getByRole("combobox",{name:selection}),{target:{value:selection==="课程"?"course-b":"exercise-next"}});
    await screen.findByRole("option",{name:selection==="课程"?"Exercise B":"Exercise Next"});
    const next=await screen.findByRole("button",{name:"提交并运行"});
    expect(next).toBeEnabled();
    fireEvent.click(next);
    await waitFor(()=>expect(submissions).toEqual(["exercise-a",selection==="课程"?"exercise-b":"exercise-next"]));
  });
  it("labels multi-concept trend sums as associations rather than unique diagnosis totals",async()=>{
    vi.stubGlobal("fetch",vi.fn(async(input:RequestInfo|URL)=>{
      const u=new URL(String(input));
      if(u.pathname==="/courses")return json([{course_id:"course-a",title:"Course A"}]);
      if(u.pathname.endsWith("/review-queue"))return json({course_id:"course-a",filters,items:[]});
      return json({status:"available",course_id:"course-a",filters,sample_size:5,groups:["concept-a","concept-b"].map(concept_id=>({concept_id,exercise_id:"exercise-a",category:"conceptual",sample_size:5,diagnosis_count:5,independent_repair_count:1}))});
    }));
    render(<CourseDashboard api={new ApiClient("http://localhost:8198",()=>"synthetic-token")}/>);
    await screen.findByRole("table",{name:"匿名概念误区数据"});
    fireEvent.change(screen.getByLabelText("开始日期"),{target:{value:"2026-10-07"}});
    fireEvent.change(screen.getByLabelText("结束日期"),{target:{value:"2026-10-07"}});
    fireEvent.click(screen.getByRole("button",{name:"应用筛选"}));
    const table=await screen.findByRole("table",{name:"相邻时间窗口趋势数据"});
    expect(within(table).getByRole("columnheader",{name:"概念诊断关联次数"})).toBeInTheDocument();
    expect(within(table).getAllByRole("cell",{name:"10"})).toHaveLength(2);
    expect(screen.getByText("同一诊断涉及多个概念时会分别计入，关联次数不代表唯一诊断总数。" )).toBeInTheDocument();
  });
  it("hides the previously loaded review queue while the next course is loading",async()=>{
    let finish!:(value:Response)=>void;
    const item={queue_event_id:"queue-a",diagnosis_id:"diagnosis-a",submission_id:"submission-a",exercise_id:"exercise-a",category:"conceptual",concept_ids:[],root_cause:"OLD_COURSE_QUEUE",evidence_summaries:[],confidence:.4,review_reason:"low_confidence",queued_at:"2026-10-07T00:00:00Z"};
    vi.stubGlobal("fetch",vi.fn(async(input:RequestInfo|URL)=>String(input).includes("course-a")?json({course_id:"course-a",filters,items:[item]}):new Promise<Response>(resolve=>{finish=resolve;})));
    const api=new ApiClient("http://localhost:8198",()=>"synthetic-token");
    const view=render(<ReviewQueue api={api} courseId="course-a" filters={filters}/>);
    await screen.findByText("OLD_COURSE_QUEUE");
    view.rerender(<ReviewQueue api={api} courseId="course-b" filters={filters}/>);
    await waitFor(()=>expect(finish).toBeDefined());
    expect(screen.queryByText("OLD_COURSE_QUEUE")).not.toBeInTheDocument();
    expect(screen.queryByRole("button",{name:"提交复核"})).not.toBeInTheDocument();
    finish(json({course_id:"course-b",filters,items:[]}));
    await screen.findByText("当前没有待复核诊断");
  });
  it("ignores an old review failure after switching to another course",async()=>{
    let finish!:(value:Response)=>void;
    const item={queue_event_id:"queue-a",diagnosis_id:"diagnosis-a",submission_id:"submission-a",exercise_id:"exercise-a",category:"conceptual",concept_ids:[],root_cause:"OLD_REVIEW",evidence_summaries:[],confidence:.4,review_reason:"low_confidence",queued_at:"2026-10-07T00:00:00Z"};
    vi.stubGlobal("fetch",vi.fn(async(input:RequestInfo|URL)=>{
      const u=new URL(String(input));
      if(u.pathname.endsWith("/review"))return new Promise<Response>(resolve=>{finish=resolve;});
      return json({course_id:u.pathname.includes("course-a")?"course-a":"course-b",filters,items:u.pathname.includes("course-a")?[item]:[]});
    }));
    const api=new ApiClient("http://localhost:8198",()=>"synthetic-token");
    const view=render(<ReviewQueue api={api} courseId="course-a" filters={filters}/>);
    await screen.findByText("OLD_REVIEW");
    fireEvent.change(screen.getByLabelText("复核理由"),{target:{value:"Synthetic reasoning"}});
    fireEvent.click(screen.getByRole("button",{name:"提交复核"}));
    await waitFor(()=>expect(finish).toBeDefined());
    view.rerender(<ReviewQueue api={api} courseId="course-b" filters={filters}/>);
    await screen.findByText("当前没有待复核诊断");
    finish(json({code:"DIAGNOSIS_REVIEW_CONFLICT",message:"Conflict",request_id:"OLD_REVIEW_ID"},409));
    await new Promise(resolve=>setTimeout(resolve,20));
    expect(screen.queryByText(/OLD_REVIEW_ID/)).not.toBeInTheDocument();
  });
});
