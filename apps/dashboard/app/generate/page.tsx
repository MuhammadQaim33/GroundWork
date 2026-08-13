"use client";

import { useState } from "react";
import AuthGuard from "@/components/auth-guard";
import type { CoverLetterFormat, GeneratedFile, GenerateRequest, GenerateResult } from "@/lib/api";
import { generateApplication } from "@/lib/api";

interface QARow {
  id: string;
  question: string;
  answer: string;
}

export default function GeneratePage() {
  const [jobDescription, setJobDescription] = useState("");
  const [rows, setRows] = useState<QARow[]>([]);
  const [format, setFormat] = useState<CoverLetterFormat>("pdf");
  const [generating, setGenerating] = useState(false);
  const [result, setResult] = useState<GenerateResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [letterText, setLetterText] = useState<string | null>(null);

  function addRow() {
    setRows((r) => [...r, { id: crypto.randomUUID(), question: "", answer: "" }]);
  }

  function updateRow(id: string, patch: Partial<QARow>) {
    setRows((r) => r.map((row) => (row.id === id ? { ...row, ...patch } : row)));
  }

  function removeRow(id: string) {
    setRows((r) => r.filter((row) => row.id !== id));
  }

  async function onGenerate() {
    if (!jobDescription.trim()) {
      setError("Add a job description first.");
      return;
    }
    setError(null);
    setResult(null);
    setGenerating(true);
    try {
      const req: GenerateRequest = {
        jobDescription,
        answers: rows.map(({ question, answer }) => ({ question, answer })),
        coverLetterFormat: format,
      };
      const res = await generateApplication(req);
      setResult(res);
      setLetterText(res.coverLetterText);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Generation failed.");
    } finally {
      setGenerating(false);
    }
  }

  return (
    <AuthGuard>
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold text-uber-black">Generate application</h1>
        <p className="mt-1 text-sm text-uber-gray">
          Paste a job description, answer optional questions, and generate a tailored cover letter
          and resume. The resume is auto-matched from your master CVs.
        </p>
      </div>

      <section className="rounded-lg border border-uber-line bg-background p-5">
        <label htmlFor="job-description" className="block text-sm font-medium text-uber-black">
          Job description
        </label>
        <textarea
          id="job-description"
          value={jobDescription}
          onChange={(e) => setJobDescription(e.target.value)}
          placeholder="Paste the job posting here…"
          rows={8}
          className="mt-2 w-full resize-y rounded-md border border-uber-line bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-uber-green"
        />
      </section>

      <section className="rounded-lg border border-uber-line bg-background p-5">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-medium text-uber-black">Optional questions</h2>
          <button
            type="button"
            onClick={addRow}
            className="rounded-md bg-uber-black px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-uber-green"
          >
            + Add question
          </button>
        </div>
        <div className="mt-3 flex flex-col gap-3">
          {rows.length === 0 && <p className="text-sm text-uber-gray">No questions yet — e.g. “Why do you want to work here?”</p>}
          {rows.map((row) => (
            <div key={row.id} className="flex items-start gap-2">
              <input
                value={row.question}
                onChange={(e) => updateRow(row.id, { question: e.target.value })}
                placeholder="Question"
                className="w-2/5 rounded-md border border-uber-line bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-uber-green"
              />
              <input
                value={row.answer}
                onChange={(e) => updateRow(row.id, { answer: e.target.value })}
                placeholder="Answer"
                className="flex-1 rounded-md border border-uber-line bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-uber-green"
              />
              <button
                type="button"
                onClick={() => removeRow(row.id)}
                aria-label="Remove question"
                className="rounded-md px-2 py-2 text-uber-gray transition-colors hover:bg-uber-green-soft hover:text-uber-green-dark"
              >
                ✕
              </button>
            </div>
          ))}
        </div>
      </section>

      <section className="rounded-lg border border-uber-line bg-background p-5">
        <h2 className="text-sm font-medium text-uber-black">Cover letter format</h2>
        <div className="mt-2 inline-flex rounded-md border border-uber-line bg-uber-bg p-0.5">
          {(["pdf", "text"] as const).map((f) => (
            <button
              key={f}
              type="button"
              onClick={() => setFormat(f)}
              className={`rounded px-4 py-1.5 text-sm font-medium transition-colors ${
                format === f ? "bg-uber-black text-white" : "text-uber-gray hover:text-uber-black"
              }`}
            >
              {f === "pdf" ? "PDF" : "Plain text"}
            </button>
          ))}
        </div>
      </section>

      {error && <p className="text-sm font-medium text-red-600">{error}</p>}

      <button
        type="button"
        onClick={onGenerate}
        disabled={generating}
        className="rounded-md bg-uber-black px-6 py-3 text-sm font-semibold text-white transition-colors hover:bg-uber-green disabled:cursor-not-allowed disabled:opacity-50"
      >
        {generating ? "Generating…" : "Generate"}
      </button>

      {result && (
        <section className="rounded-lg border border-uber-green bg-uber-green-soft p-5">
          <div className="flex items-center gap-2">
            <span className="inline-block h-2.5 w-2.5 rounded-full bg-uber-green" />
            <h2 className="text-sm font-semibold text-uber-green-dark">Ready — review and download</h2>
          </div>
          {result.usedMasterCv && (
            <p className="mt-1 text-xs text-uber-gray">Master CV matched: {result.usedMasterCv}</p>
          )}
          <div className="mt-4 flex flex-wrap gap-3">
            <DownloadButton file={result.resume} label="Custom resume" />
            <DownloadButton file={result.coverLetter} label="Cover letter" />
          </div>
          {letterText !== null && (
            <pre className="mt-4 whitespace-pre-wrap rounded-md border border-uber-line bg-white p-4 text-sm">
              {letterText}
            </pre>
          )}
        </section>
      )}
    </div>
    </AuthGuard>
  );
}

function DownloadButton({ file, label }: { file: GeneratedFile; label: string }) {
  const [busy, setBusy] = useState(false);

  async function handleClick() {
    if (busy) return;
    setBusy(true);
    try {
      let blob: Blob;
      if (file.url) {
        const res = await fetch(file.url);
        if (!res.ok) throw new Error("Download failed");
        blob = await res.blob();
      } else if (file.text != null) {
        blob = new Blob([file.text], { type: "text/plain;charset=utf-8" });
      } else {
        return;
      }
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = file.name;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch {
      // silent: the results panel still offers the file
    } finally {
      setBusy(false);
    }
  }

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={busy}
      className="rounded-md bg-uber-green px-4 py-2 text-sm font-semibold text-uber-black transition-colors hover:bg-uber-green-dark hover:text-white disabled:opacity-50"
    >
      {busy ? "Fetching…" : `${label} · ${file.kind.toUpperCase()}`}
    </button>
  );
}
