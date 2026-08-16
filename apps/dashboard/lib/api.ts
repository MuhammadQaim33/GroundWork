// API layer for the Day-1 Cover Letter + Resume Generator module.
// Talks to the FastAPI backend (apps/api). Mock bodies replaced; this is the
// real contract. Server records are snake_case; mapped to camelCase for the UI.

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

import { clearSession, getSession, setSession, type Session } from "@/lib/session";

export type CoverLetterFormat = "pdf" | "text";
export type GeneratePart = "resume" | "cover_letter" | "feedback";

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
  provider: "ollama" | "gemini" | "openrouter" | "groq";
  openrouterKeySet: boolean;
  geminiKeySet: boolean;
}

export interface JobAnswer {
  question: string;
  answer: string;
}

export interface GenerateRequest {
  jobDescription: string;
  answers: JobAnswer[];
  coverLetterFormats: CoverLetterFormat[];
  parts?: GeneratePart[];
}

export interface GeneratedFile {
  name: string;
  kind: "pdf" | "text";
  url?: string;
  text?: string;
}

export type GenerateEvent =
  | { event: "used_master_cv"; data: { usedMasterCv: string } }
  | { event: "resume"; data: GeneratedFile }
  | { event: "cover_letter_text"; data: { text: string } }
  | { event: "cover_letter_txt"; data: GeneratedFile }
  | { event: "cover_letter_pdf"; data: GeneratedFile }
  | { event: "feedback"; data: { rating: number | null; text: string } }
  | { event: "error"; data: { message: string; part?: string } }
  | { event: "done"; data: null };

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
  provider: "ollama" | "gemini" | "openrouter" | "groq";
  openrouter_key_set: boolean;
  gemini_key_set: boolean;
}

interface ServerFile {
  name: string;
  kind: "pdf" | "text";
  url: string | null;
  text?: string;
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
  return {
    provider: row.provider,
    openrouterKeySet: row.openrouter_key_set,
    geminiKeySet: row.gemini_key_set,
  };
}

export async function setOpenRouterKey(key: string): Promise<void> {
  await request("/api/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ openrouter_api_key: key }),
  });
}

export async function setGeminiKey(key: string): Promise<void> {
  await request("/api/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ gemini_api_key: key }),
  });
}

export async function getLinks(): Promise<string[]> {
  const res = await request<{ links: string[] }>("/api/links");
  return res.links;
}

export async function setLinks(links: string[]): Promise<void> {
  await request("/api/links", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ links }),
  });
}

export async function extractScreenshotQuestions(files: File[]): Promise<JobAnswer[]> {
  const form = new FormData();
  for (const f of files) form.append("files", f);
  return request<JobAnswer[]>("/api/screenshot-questions", {
    method: "POST",
    body: form,
  });
}

interface RawSseEvent {
  event: string;
  data: unknown;
}

function mapFile(f: ServerFile): GeneratedFile {
  return {
    name: f.name,
    kind: f.kind,
    url: f.url ? absolute(f.url) : undefined,
    text: f.text,
  };
}

function dispatchEvent(raw: RawSseEvent, onEvent: (ev: GenerateEvent) => void): void {
  switch (raw.event) {
    case "used_master_cv":
      onEvent({
        event: "used_master_cv",
        data: { usedMasterCv: (raw.data as { used_master_cv: string }).used_master_cv },
      });
      break;
    case "resume":
      onEvent({ event: "resume", data: mapFile(raw.data as ServerFile) });
      break;
    case "cover_letter_text":
      onEvent({ event: "cover_letter_text", data: { text: (raw.data as { text: string }).text } });
      break;
    case "cover_letter_txt":
      onEvent({ event: "cover_letter_txt", data: mapFile(raw.data as ServerFile) });
      break;
    case "cover_letter_pdf":
      onEvent({ event: "cover_letter_pdf", data: mapFile(raw.data as ServerFile) });
      break;
    case "feedback": {
      const f = raw.data as { rating?: number | null; text: string };
      onEvent({ event: "feedback", data: { rating: f.rating ?? null, text: f.text } });
      break;
    }
    case "error": {
      const e = raw.data as { message: string; part?: string };
      onEvent({ event: "error", data: { message: e.message, part: e.part } });
      break;
    }
    case "done":
      onEvent({ event: "done", data: null });
      break;
  }
}

async function readSSE(body: ReadableStream<Uint8Array>, onRaw: (ev: RawSseEvent) => void): Promise<void> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let sep = buffer.indexOf("\n\n");
    while (sep !== -1) {
      const block = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      let event = "message";
      const dataLines: string[] = [];
      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
      }
      if (dataLines.length > 0) {
        let data: unknown = null;
        try {
          data = JSON.parse(dataLines.join("\n"));
        } catch {
          // malformed payload — skip the event
        }
        onRaw({ event, data });
      }
      sep = buffer.indexOf("\n\n");
    }
  }
}

export async function generateApplication(
  req: GenerateRequest,
  onEvent: (ev: GenerateEvent) => void,
  retried = false
): Promise<void> {
  const session = getSession();
  const headers = new Headers({ "Content-Type": "application/json" });
  if (session) headers.set("Authorization", `Bearer ${session.accessToken}`);
  const res = await fetch(`${API_URL}/api/generate`, {
    method: "POST",
    headers,
    body: JSON.stringify({
      job_description: req.jobDescription,
      answers: req.answers,
      cover_letter_formats: req.coverLetterFormats,
      parts: req.parts ?? ["resume", "cover_letter"],
    }),
  });

  if (res.status === 401 && session && !retried) {
    const refreshed = await tryRefresh(session);
    if (refreshed) return generateApplication(req, onEvent, true);
    clearSession();
    if (typeof window !== "undefined") {
      window.dispatchEvent(new Event("groundwork:unauthorized"));
    }
    throw new Error("Session expired. Please sign in again.");
  }

  if (!res.ok || !res.body) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? JSON.stringify(body);
    } catch {
      // keep statusText
    }
    throw new Error(detail);
  }

  await readSSE(res.body, (raw) => dispatchEvent(raw, onEvent));
}
