import type { SessionData } from "../api/client";

export const SESSION_KEY = "knowbound.session";

export function readSession(): SessionData | null {
  try {
    const raw = localStorage.getItem(SESSION_KEY);
    if (!raw) return null;
    const value = JSON.parse(raw) as Partial<SessionData>;
    if (!value.accessToken || !value.actor || (value.actor.role !== "student" && value.actor.role !== "teacher")) return null;
    return value as SessionData;
  } catch {
    return null;
  }
}

export function saveSession(session: SessionData) {
  localStorage.setItem(SESSION_KEY, JSON.stringify(session));
}

export function clearSession() {
  localStorage.removeItem(SESSION_KEY);
}
