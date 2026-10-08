import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../src/App";
import { CourseDashboard } from "../src/teacher/CourseDashboard";
import { ExercisePage } from "../src/student/ExercisePage";
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
});
