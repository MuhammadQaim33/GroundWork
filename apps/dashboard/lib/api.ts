// API layer for the Day-1 Cover Letter + Resume Generator module.
// Talks to the FastAPI backend (apps/api). Mock bodies replaced; this is the
// real contract. Server records are snake_case; mapped to camelCase for the UI.

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

import { clearSession, getSession, setSession, type Session } from "@/lib/session";

export type CoverLetterFormat = "pdf" | "text";

export interface MasterCV {
  id: number;
  name: string;
  uploadedAt: string;
  preferred: boolean;
}

export interface BragDoc {
  id: number;
  name: string;
  uploadedAt: string;
}

export interface LlmSettings {
  provider: "openrouter" | "groq" | "ollama";
  openrouterKeySet: boolean;
}

export interface JobAnswer {
  question: string;
  answer: string;
}

export interface GenerateRequest {
  jobDescription: string;
  answers: JobAnswer[];
  coverLetterFormat: CoverLetterFormat;
}

export interface GeneratedFile {
  name: string;
  kind: "pdf" | "text";
  url?: string;
  text?: string;
}

export interface GenerateResult {
  resume: GeneratedFile;
  coverLetter: GeneratedFile;
  coverLetterText: string | null;
  usedMasterCv: string | null;
}

interface ServerCV {
  id: number;
  file_name: string;
  uploaded_at: string;
  preferred: boolean;
}

interface ServerBrag {
  id: number;
  file_name: string;
  uploaded_at: string;
}

interface ServerLlmSettings {
  provider: "openrouter" | "groq" | "ollama";
  openrouter_key_set: boolean;
}

interface ServerFile {
  name: string;
  kind: "pdf" | "text";
  url: string | null;
}

interface ServerGenerateResult {
  resume: ServerFile;
  cover_letter: ServerFile;
  cover_letter_text: string | null;
  used_master_cv: string | null;
}

interface ServerAuthResult {
  access_token: string;
  refresh_token: string;
  expires_at: number;
  service_user_id: number;
}

export interface AuthResult {
  accessToken: string;
  refreshToken: string;
  expiresAt: number;
  serviceUserId: number;
}

async function request<T>(path: string, init?: RequestInit, retried = false): Promise<T> {
  const session = getSession();
  const headers = new Headers(init?.headers);
  if (session) headers.set("Authorization", `Bearer ${session.accessToken}`);
  const res = await fetch(`${API_URL}${path}`, { ...init, headers });

  if (res.status === 401 && session && !retried) {
    const refreshed = await tryRefresh(session);
    if (refreshed) return request<T>(path, init, true);
    clearSession();
    if (typeof window !== "undefined") {
      window.dispatchEvent(new Event("groundwork:unauthorized"));
    }
    throw new Error("Session expired. Please sign in again.");
  }

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? JSON.stringify(body);
    } catch {
      // keep statusText
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

async function tryRefresh(session: Session): Promise<boolean> {
  try {
    const res = await fetch(`${API_URL}/api/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: session.refreshToken }),
    });
    if (!res.ok) return false;
    const body = (await res.json()) as ServerAuthResult;
    setSession(body);
    return true;
  } catch {
    return false;
  }
}

async function auth(path: string, email: string, password: string): Promise<AuthResult> {
  const res = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? JSON.stringify(body);
    } catch {
      // keep statusText
    }
    throw new Error(detail);
  }
  const body = (await res.json()) as ServerAuthResult;
  setSession(body);
  return {
    accessToken: body.access_token,
    refreshToken: body.refresh_token,
    expiresAt: body.expires_at,
    serviceUserId: body.service_user_id,
  };
}

export async function signup(email: string, password: string): Promise<AuthResult> {
  return auth("/api/auth/signup", email, password);
}

export async function login(email: string, password: string): Promise<AuthResult> {
  return auth("/api/auth/login", email, password);
}

export async function logout(): Promise<void> {
  const session = getSession();
  if (session) {
    try {
      await fetch(`${API_URL}/api/auth/logout`, {
        method: "POST",
        headers: { Authorization: `Bearer ${session.accessToken}` },
      });
    } catch {
      // best-effort; always clear locally
    }
  }
  clearSession();
}

function absolute(url: string): string {
  return url.startsWith("http") ? url : `${API_URL}${url}`;
}

function toCV(row: ServerCV): MasterCV {
  return { id: row.id, name: row.file_name, uploadedAt: row.uploaded_at, preferred: row.preferred };
}

function toBrag(row: ServerBrag): BragDoc {
  return { id: row.id, name: row.file_name, uploadedAt: row.uploaded_at };
}

export async function listMasterCVs(): Promise<MasterCV[]> {
  const rows = await request<ServerCV[]>("/api/master-cvs");
  return rows.map(toCV);
}

export async function addMasterCV(file: File): Promise<MasterCV> {
  const form = new FormData();
  form.append("file", file);
  const row = await request<ServerCV>("/api/master-cvs", { method: "POST", body: form });
  return toCV(row);
}

export async function removeMasterCV(id: number): Promise<void> {
  await request(`/api/master-cvs/${id}`, { method: "DELETE" });
}

export async function setPreferredMasterCV(id: number): Promise<void> {
  await request(`/api/master-cvs/${id}/preferred`, { method: "PUT" });
}

export async function getBragDoc(): Promise<BragDoc | null> {
  const row = await request<ServerBrag | null>("/api/brag-doc");
  return row ? toBrag(row) : null;
}

export async function setBragDoc(file: File): Promise<BragDoc> {
  const form = new FormData();
  form.append("file", file);
  const row = await request<ServerBrag>("/api/brag-doc", { method: "POST", body: form });
  return toBrag(row);
}

export async function clearBragDoc(): Promise<void> {
  await request("/api/brag-doc", { method: "DELETE" });
}

export async function getLlmSettings(): Promise<LlmSettings> {
  const row = await request<ServerLlmSettings>("/api/settings");
  return { provider: row.provider, openrouterKeySet: row.openrouter_key_set };
}

export async function setOpenRouterKey(key: string): Promise<void> {
  await request("/api/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ openrouter_api_key: key }),
  });
}

export async function generateApplication(req: GenerateRequest): Promise<GenerateResult> {
  const res = await request<ServerGenerateResult>("/api/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      job_description: req.jobDescription,
      answers: req.answers,
      cover_letter_format: req.coverLetterFormat,
    }),
  });
  return {
    resume: {
      name: res.resume.name,
      kind: res.resume.kind,
      url: res.resume.url ? absolute(res.resume.url) : undefined,
    },
    coverLetter:
      res.cover_letter_text != null
        ? { name: "cover-letter.txt", kind: "text", text: res.cover_letter_text }
        : {
            name: res.cover_letter.name,
            kind: res.cover_letter.kind,
            url: res.cover_letter.url ? absolute(res.cover_letter.url) : undefined,
          },
    coverLetterText: res.cover_letter_text ?? null,
    usedMasterCv: res.used_master_cv ?? null,
  };
}
