"use client";

import { useEffect, useState } from "react";
import AuthGuard from "@/components/auth-guard";
import type { BragDoc, LlmSettings, MasterCV } from "@/lib/api";
import {
  addMasterCV,
  clearBragDoc,
  getBragDoc,
  getLinks,
  getLlmSettings,
  listMasterCVs,
  removeMasterCV,
  setBragDoc,
  setGeminiKey,
  setLinks,
  setOpenRouterKey,
  setPreferredMasterCV,
} from "@/lib/api";

interface LinkRow {
  id: string;
  value: string;
}

export default function SettingsPage() {
  const [cvs, setCvs] = useState<MasterCV[]>([]);
  const [brag, setBrag] = useState<BragDoc | null>(null);
  const [llm, setLlm] = useState<LlmSettings | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [cvError, setCvError] = useState<string | null>(null);
  const [bragError, setBragError] = useState<string | null>(null);
  const [llmError, setLlmError] = useState<string | null>(null);
  const [llmSaved, setLlmSaved] = useState(false);
  const [keyInput, setKeyInput] = useState("");
  const [geminiInput, setGeminiInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [linkRows, setLinkRows] = useState<LinkRow[]>([]);
  const [linkError, setLinkError] = useState<string | null>(null);
  const [linksSaved, setLinksSaved] = useState(false);

  useEffect(() => {
    let alive = true;
    (async () => {
      const [c, b, l, links] = await Promise.all([
        listMasterCVs(),
        getBragDoc(),
        getLlmSettings(),
        getLinks(),
      ]);
      if (alive) {
        setCvs(c);
        setBrag(b);
        setLlm(l);
        setLinkRows(links.map((value) => ({ id: crypto.randomUUID(), value })));
        setLoaded(true);
      }
    })().catch(() => {
      if (alive) setLoaded(true);
    });
    return () => {
      alive = false;
    };
  }, []);

  function addLinkRow() {
    setLinkRows((r) => [...r, { id: crypto.randomUUID(), value: "" }]);
  }

  function updateLinkRow(id: string, value: string) {
    setLinkRows((r) => r.map((row) => (row.id === id ? { ...row, value } : row)));
    setLinksSaved(false);
  }

  function removeLinkRow(id: string) {
    setLinkRows((r) => r.filter((row) => row.id !== id));
    setLinksSaved(false);
  }

  async function onSaveLinks() {
    const links = linkRows.map((row) => row.value.trim()).filter(Boolean);
    setLinkError(null);
    setLinksSaved(false);
    setBusy(true);
    try {
      await setLinks(links);
      setLinkRows(links.map((value) => ({ id: crypto.randomUUID(), value })));
      setLinksSaved(true);
    } catch (err) {
      setLinkError(err instanceof Error ? err.message : "Save failed.");
    } finally {
      setBusy(false);
    }
  }

  async function onCvUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".tex")) {
      setCvError("Master CVs must be .tex (LaTeX) files.");
      return;
    }
    setCvError(null);
    setBusy(true);
    try {
      const cv = await addMasterCV(file);
      setCvs((prev) => [...prev, cv]);
    } catch (err) {
      setCvError(err instanceof Error ? err.message : "Upload failed.");
    } finally {
      setBusy(false);
      e.target.value = "";
    }
  }

  async function onBragUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".md")) {
      setBragError("The brag document must be a Markdown (.md) file.");
      return;
    }
    setBragError(null);
    setBusy(true);
    try {
      setBrag(await setBragDoc(file));
    } catch (err) {
      setBragError(err instanceof Error ? err.message : "Upload failed.");
    } finally {
      setBusy(false);
      e.target.value = "";
    }
  }

  async function onSaveKey() {
    if (!keyInput.trim()) return;
    setLlmError(null);
    setLlmSaved(false);
    setBusy(true);
    try {
      await setOpenRouterKey(keyInput.trim());
      setKeyInput("");
      setLlm(await getLlmSettings());
      setLlmSaved(true);
    } catch (err) {
      setLlmError(err instanceof Error ? err.message : "Save failed.");
    } finally {
      setBusy(false);
    }
  }

  async function onSaveGeminiKey() {
    if (!geminiInput.trim()) return;
    setLlmError(null);
    setLlmSaved(false);
    setBusy(true);
    try {
      await setGeminiKey(geminiInput.trim());
      setGeminiInput("");
      setLlm(await getLlmSettings());
      setLlmSaved(true);
    } catch (err) {
      setLlmError(err instanceof Error ? err.message : "Save failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthGuard>
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold text-uber-black">Settings</h1>
        <p className="mt-1 text-sm text-uber-gray">
          Manage the source materials the generator works from. Uploads live in Supabase Storage;
          the API compiles fine-tuned PDFs locally with tectonic.
        </p>
      </div>

      <section className="rounded-lg border border-uber-line bg-background p-5">
        <div>
          <h2 className="text-sm font-medium text-uber-black">AI provider</h2>
          <p className="mt-0.5 text-xs text-uber-gray">
            Generations run on the free Groq tier by default. Adding a free Google AI
            Studio (Gemini) key upgrades both generation and screenshot questions to
            Gemini with no credit costs; your OpenRouter key is the paid fallback. Keys
            are stored server-side and never shown again.
          </p>
        </div>

        <div className="mt-4 flex items-center gap-2">
          <input
            type="password"
            value={geminiInput}
            onChange={(e) => setGeminiInput(e.target.value)}
            placeholder={
              llm?.geminiKeySet ? "Replace saved Gemini key" : "Gemini API key (free, from AI Studio)"
            }
            className="w-full max-w-sm rounded-md border border-uber-line px-3 py-1.5 text-sm text-uber-black outline-none focus:border-uber-green"
          />
          <button
            type="button"
            onClick={onSaveGeminiKey}
            disabled={busy || !geminiInput.trim()}
            className="rounded-md bg-uber-black px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-uber-green disabled:opacity-50"
          >
            Save Gemini key
          </button>
        </div>

        <div className="mt-4 flex items-center gap-2">
          <input
            type="password"
            value={keyInput}
            onChange={(e) => setKeyInput(e.target.value)}
            placeholder={
              llm?.openrouterKeySet ? "Replace saved key (starts sk-or-…)" : "OpenRouter key (sk-or-…)"
            }
            className="w-full max-w-sm rounded-md border border-uber-line px-3 py-1.5 text-sm text-uber-black outline-none focus:border-uber-green"
          />
          <button
            type="button"
            onClick={onSaveKey}
            disabled={busy || !keyInput.trim()}
            className="rounded-md bg-uber-black px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-uber-green disabled:opacity-50"
          >
            Save OpenRouter key
          </button>
        </div>

        {llmError && <p className="mt-3 text-sm font-medium text-red-600">{llmError}</p>}
        {llmSaved && <p className="mt-3 text-sm font-medium text-uber-green-dark">Key saved.</p>}
        {loaded && llm && (
          <p className="mt-3 text-xs text-uber-gray">
            Active provider:{" "}
            {llm.provider === "gemini"
              ? "Gemini (free)"
              : llm.provider === "openrouter"
                ? "OpenRouter (your key)"
                : llm.provider === "ollama"
                  ? "Ollama (local)"
                  : "Groq (free fallback)"}
          </p>
        )}
      </section>

      <section className="rounded-lg border border-uber-line bg-background p-5">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-sm font-medium text-uber-black">Master CVs</h2>
            <p className="mt-0.5 text-xs text-uber-gray">
              LaTeX (.tex) versions of your CV. The generator auto-picks one from the job
              description; the preferred mark breaks ties.
            </p>
          </div>
          <label className="cursor-pointer rounded-md bg-uber-black px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-uber-green disabled:opacity-50">
            + Upload .tex
            <input type="file" accept=".tex" className="hidden" onChange={onCvUpload} disabled={busy} />
          </label>
        </div>

        {cvError && <p className="mt-3 text-sm font-medium text-red-600">{cvError}</p>}

        <ul className="mt-4 flex flex-col gap-2">
          {loaded && cvs.length === 0 && <li className="text-sm text-uber-gray">No master CVs yet.</li>}
          {cvs.map((cv) => (
            <li
              key={cv.id}
              className="flex items-center justify-between gap-3 rounded-md border border-uber-line px-3 py-2"
            >
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-uber-black">
                  {cv.name}
                  {cv.preferred && (
                    <span className="ml-2 rounded bg-uber-green-soft px-1.5 py-0.5 text-xs font-semibold text-uber-green-dark">
                      Preferred
                    </span>
                  )}
                </p>
                <p className="text-xs text-uber-gray">
                  Uploaded {new Date(cv.uploadedAt).toLocaleDateString()}
                </p>
              </div>
              <div className="flex shrink-0 gap-2">
                {!cv.preferred && (
                  <button
                    type="button"
                    onClick={async () => {
                      setBusy(true);
                      try {
                        await setPreferredMasterCV(cv.id);
                        setCvs(await listMasterCVs());
                      } catch (err) {
                        setCvError(err instanceof Error ? err.message : "Update failed.");
                      } finally {
                        setBusy(false);
                      }
                    }}
                    className="rounded-md border border-uber-line px-2 py-1 text-xs font-medium text-uber-black transition-colors hover:border-uber-green hover:text-uber-green-dark"
                  >
                    Preferred
                  </button>
                )}
                <button
                  type="button"
                  onClick={async () => {
                    setBusy(true);
                    try {
                      await removeMasterCV(cv.id);
                      setCvs((prev) => prev.filter((c) => c.id !== cv.id));
                    } catch (err) {
                      setCvError(err instanceof Error ? err.message : "Delete failed.");
                    } finally {
                      setBusy(false);
                    }
                  }}
                  className="rounded-md px-2 py-1 text-xs font-medium text-uber-gray transition-colors hover:bg-uber-green-soft hover:text-uber-green-dark"
                >
                  Remove
                </button>
              </div>
            </li>
          ))}
        </ul>
      </section>

      <section className="rounded-lg border border-uber-line bg-background p-5">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-sm font-medium text-uber-black">Brag document</h2>
            <p className="mt-0.5 text-xs text-uber-gray">
              Markdown notes of wins, metrics, and stories used to fine-tune the chosen CV. Optional.
            </p>
          </div>
          <label className="cursor-pointer rounded-md bg-uber-black px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-uber-green">
            + Upload .md
            <input type="file" accept=".md" className="hidden" onChange={onBragUpload} disabled={busy} />
          </label>
        </div>

        {bragError && <p className="mt-3 text-sm font-medium text-red-600">{bragError}</p>}

        {loaded && brag ? (
          <div className="mt-4 flex items-center justify-between gap-3 rounded-md border border-uber-line px-3 py-2">
            <div className="min-w-0">
              <p className="truncate text-sm font-medium text-uber-black">{brag.name}</p>
              <p className="text-xs text-uber-gray">
                Uploaded {new Date(brag.uploadedAt).toLocaleDateString()}
              </p>
            </div>
            <button
              type="button"
              onClick={async () => {
                setBusy(true);
                try {
                  await clearBragDoc();
                  setBrag(null);
                } catch (err) {
                  setBragError(err instanceof Error ? err.message : "Delete failed.");
                } finally {
                  setBusy(false);
                }
              }}
              className="shrink-0 rounded-md px-2 py-1 text-xs font-medium text-uber-gray transition-colors hover:bg-uber-green-soft hover:text-uber-green-dark"
            >
              Remove
            </button>
          </div>
        ) : (
          loaded && <p className="mt-4 text-sm text-uber-gray">No brag document yet — optional.</p>
        )}
      </section>

      <section className="rounded-lg border border-uber-line bg-background p-5">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-sm font-medium text-uber-black">Links</h2>
            <p className="mt-0.5 text-xs text-uber-gray">
              Any number of links you want the generator to know about — GitHub, LinkedIn, or
              portfolio. Saved to your profile.
            </p>
          </div>
          <button
            type="button"
            onClick={addLinkRow}
            className="rounded-md bg-uber-black px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-uber-green"
          >
            + Add link
          </button>
        </div>

        <div className="mt-3 flex flex-col gap-3">
          {loaded && linkRows.length === 0 && (
            <p className="text-sm text-uber-gray">No links yet — e.g. github.com/you, linkedin.com/in/you.</p>
          )}
          {linkRows.map((row) => (
            <div key={row.id} className="flex items-start gap-2">
              <input
                value={row.value}
                onChange={(e) => updateLinkRow(row.id, e.target.value)}
                placeholder="https://…"
                className="flex-1 rounded-md border border-uber-line bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-uber-green"
              />
              <button
                type="button"
                onClick={() => removeLinkRow(row.id)}
                aria-label="Remove link"
                className="rounded-md px-2 py-2 text-uber-gray transition-colors hover:bg-uber-green-soft hover:text-uber-green-dark"
              >
                ✕
              </button>
            </div>
          ))}
        </div>

        <div className="mt-4 flex items-center gap-3">
          <button
            type="button"
            onClick={onSaveLinks}
            disabled={busy}
            className="rounded-md bg-uber-black px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-uber-green disabled:opacity-50"
          >
            Save links
          </button>
          {linkError && <p className="text-sm font-medium text-red-600">{linkError}</p>}
          {linksSaved && <p className="text-sm font-medium text-uber-green-dark">Links saved.</p>}
        </div>
      </section>
    </div>
    </AuthGuard>
  );
}
