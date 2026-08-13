// Client-side token store for the server-issued Supabase session.
// Tokens come from POST /api/auth/{signup,login,refresh} on the FastAPI backend.

const ACCESS_KEY = "gw_access_token";
const REFRESH_KEY = "gw_refresh_token";
const EXPIRES_KEY = "gw_expires_at";

export interface Session {
  accessToken: string;
  refreshToken: string;
  expiresAt: number;
}

// Module-level cache so getSession returns the SAME object reference until
// localStorage actually changes. useSyncExternalStore (see use-session.ts)
// requires a referentially-stable getSnapshot result; a fresh object per call
// triggers an infinite re-render loop ("Maximum update depth exceeded").
let cachedSession: Session | null = null;
let cachedRaw = "";

function rawSession(): string {
  if (typeof window === "undefined") return "";
  return [
    window.localStorage.getItem(ACCESS_KEY) ?? "",
    window.localStorage.getItem(REFRESH_KEY) ?? "",
    window.localStorage.getItem(EXPIRES_KEY) ?? "",
  ].join("|");
}

export function getSession(): Session | null {
  const raw = rawSession();
  if (raw === cachedRaw) return cachedSession;
  const [accessToken, refreshToken, expiresAtRaw] = raw.split("|");
  const expiresAt = Number(expiresAtRaw);
  cachedRaw = raw;
  cachedSession =
    accessToken && refreshToken && expiresAt ? { accessToken, refreshToken, expiresAt } : null;
  return cachedSession;
}

export function setSession(tokens: {
  access_token: string;
  refresh_token: string;
  expires_at: number;
}): void {
  window.localStorage.setItem(ACCESS_KEY, tokens.access_token);
  window.localStorage.setItem(REFRESH_KEY, tokens.refresh_token);
  window.localStorage.setItem(EXPIRES_KEY, String(tokens.expires_at));
  notifySessionChange();
}

export function clearSession(): void {
  window.localStorage.removeItem(ACCESS_KEY);
  window.localStorage.removeItem(REFRESH_KEY);
  window.localStorage.removeItem(EXPIRES_KEY);
  notifySessionChange();
}

export function notifySessionChange(): void {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event("groundwork:session-changed"));
  }
}


