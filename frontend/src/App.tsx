import { useMemo, useRef, useState } from "react";

import { ApiClient, ApiError, type SessionData } from "./api/client";
import { clearSession, readSession, saveSession } from "./auth/session";
import { RequestState } from "./components/RequestState";
import { StudentPage } from "./student/StudentPage";
import { CourseDashboard } from "./teacher/CourseDashboard";

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

function Login({ onLogin }: { onLogin: (session: SessionData) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const api = useMemo(() => new ApiClient(apiBaseUrl, () => null), []);

  async function login() {
    if (!username.trim() || !password) return;
    setBusy(true); setError(null);
    try {
      const response = await api.login(username.trim(), password);
      const session = { accessToken: response.access_token, actor: response.actor };
      saveSession(session);
      onLogin(session);
    } catch (nextError) { setError(nextError); }
    finally { setBusy(false); }
  }

  return (
    <main className="login-page">
      {import.meta.env.VITE_SYNTHETIC_DEMO === "true" && <p role="note">比赛合成演示 · 模型响应为确定性 Mock · 编译反馈来自真实隔离 Runner · 非教学试点结果</p>}
      <section className="login-intro"><p className="brand-mark">KNOWBOUND · CJ</p><h1>知界·仓颉学伴</h1><p>面向《仓颉语言设计》的可信概念误区诊断智能体。</p><div className="role-statement"><span>学生端</span><i aria-hidden="true" /><span>教师端</span></div><p className="privacy-promise">学习证据各归其位：学生掌控私人记忆，教师只看匿名课程信号。</p></section>
      <section className="login-panel" aria-labelledby="login-title"><p className="section-kicker">COURSE ACCESS</p><h2 id="login-title">进入课程空间</h2><label>用户名<input autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} /></label><label>密码<input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void login(); }} /></label><button type="button" onClick={() => void login()} disabled={busy || !username.trim() || !password}>{busy ? "正在验证…" : "登录"}</button>{error !== null && <RequestState error={error} />}</section>
    </main>
  );
}

export function App() {
  const [session, setSession] = useState<SessionData | null>(() => readSession());
  const api = useMemo(() => new ApiClient(apiBaseUrl, () => session?.accessToken ?? null), [session?.accessToken]);
  const logoutLock = useRef(false);
  const [logoutBusy, setLogoutBusy] = useState(false);
  const [logoutError, setLogoutError] = useState<unknown>(null);

  async function logout() {
    if (logoutLock.current) return;
    logoutLock.current = true; setLogoutBusy(true); setLogoutError(null);
    try {
      await api.logout(); clearSession(); setSession(null);
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) { clearSession(); setSession(null); }
      else setLogoutError(error);
    } finally { logoutLock.current = false; setLogoutBusy(false); }
  }

  if (!session) return <Login onLogin={setSession} />;

  return (
    <div className="app-shell">
      <header className="site-header"><a className="brand" href="#top" aria-label="知界·仓颉学伴首页"><span aria-hidden="true">知界</span><strong>仓颉学伴</strong></a><div className="session-meta"><span>{session.actor.role === "student" ? "学生端" : "教师端"}</span><button type="button" className="text-button" disabled={logoutBusy} onClick={() => void logout()}>{logoutBusy ? "正在退出…" : "退出"}</button></div></header>
      {logoutError !== null && <RequestState error={logoutError} />}
      {import.meta.env.VITE_SYNTHETIC_DEMO === "true" && <p role="note">比赛合成演示 · 模型响应为确定性 Mock · 编译反馈来自真实隔离 Runner · 非教学试点结果</p>}
      <main id="top">{session.actor.role === "student" ? <StudentPage key={session.actor.user_id} api={api} ownerId={session.actor.user_id} /> : <CourseDashboard api={api} />}</main>
    </div>
  );
}
