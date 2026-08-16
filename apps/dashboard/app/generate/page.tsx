"use client";

import { useState } from "react";
import AuthGuard from "@/components/auth-guard";
import type { CoverLetterFormat, GeneratePart, GeneratedFile, GenerateRequest } from "@/lib/api";
import { extractScreenshotQuestions, generateApplication } from "@/lib/api";

interface QARow {
  id: string;
  question: string;
  answer: string;
}

interface ToggleState {
  resume: boolean;
  letterPdf: boolean;
  letterText: boolean;
}

const TOGGLES: { key: keyof ToggleState; label: string }[] = [
  { key: "resume", label: "Resume" },
  { key: "letterPdf", label: "Cover letter · PDF" },
  { key: "letterText", label: "Cover letter · text" },
];

export default function GeneratePage() {
  const [jobDescription, setJobDescription] = useState("");
  const [rows, setRows] = useState<QARow[]>([]);
  const [toggles, setToggles] = useState<ToggleState>({
    resume: true,
    letterPdf: true,
    letterText: false,
  });
  const [generating, setGenerating] = useState(false);
  const [resume, setResume] = useState<GeneratedFile | null>(null);
  const [coverLetterPdf, setCoverLetterPdf] = useState<GeneratedFile | null>(null);
  const [coverLetterTxt, setCoverLetterTxt] = useState<GeneratedFile | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [letterText, setLetterText] = useState<string | null>(null);
  const [rating, setRating] = useState<number | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [usedMasterCv, setUsedMasterCv] = useState<string | null>(null);
  const [screenshotFiles, setScreenshotFiles] = useState<File[]>([]);
  const [extracting, setExtracting] = useState(false);
  const [screenshotError, setScreenshotError] = useState<string | null>(null);

  function toggle(key: keyof ToggleState) {
    setToggles((t) => ({ ...t, [key]: !t[key] }));
  }

  function addRow() {
    setRows((r) => [...r, { id: crypto.randomUUID(), question: "", answer: "" }]);
  }

  function updateRow(id: string, patch: Partial<QARow>) {
    setRows((r) => r.map((row) => (row.id === id ? { ...row, ...patch } : row)));
  }

  function removeRow(id: string) {
    setRows((r) => r.filter((row) => row.id !== id));
  }

  async function extractFromScreenshots() {
    if (screenshotFiles.length === 0) return;
    setExtracting(true);
    setScreenshotError(null);
    try {
      const qas = await extractScreenshotQuestions(screenshotFiles);
      const additions: QARow[] = qas
        .filter((qa) => qa.question.trim())
        .map((qa) => ({ id: crypto.randomUUID(), question: qa.question, answer: qa.answer }));
      if (additions.length === 0) {
        setScreenshotError("No questions were extracted. Try clearer screenshots.");
        return;
      }
      setRows((r) => {
        const existing = new Set(r.map((row) => row.question.trim().toLowerCase()));
        return [
          ...r,
          ...additions.filter((a) => !existing.has(a.question.trim().toLowerCase())),
        ];
      });
      setScreenshotFiles([]);
    } catch (e) {
      setScreenshotError(e instanceof Error ? e.message : "Extraction failed.");
    } finally {
      setExtracting(false);
    }
  }

  async function onGenerate() {
    if (!jobDescription.trim()) {
      setError("Add a job description first.");
      return;
    }
    const formats: CoverLetterFormat[] = [];
    if (toggles.letterPdf) formats.push("pdf");
    if (toggles.letterText) formats.push("text");
    const parts: GeneratePart[] = ["feedback"];
    if (toggles.resume) parts.push("resume");
    if (formats.length > 0) parts.push("cover_letter");
    setError(null);
    setGenerating(true);
    setResume(null);
    setCoverLetterPdf(null);
    setCoverLetterTxt(null);
    setLetterText(null);
    setRating(null);
    setFeedback(null);
    setUsedMasterCv(null);
    try {
      const req: GenerateRequest = {
        jobDescription,
        answers: rows.map(({ question, answer }) => ({ question, answer })),
        coverLetterFormats: formats,
        parts,
      };
      await generateApplication(req, (ev) => {
        switch (ev.event) {
          case "used_master_cv":
            setUsedMasterCv(ev.data.usedMasterCv);
            break;
          case "resume":
            setResume(ev.data);
            break;
          case "cover_letter_text":
            setLetterText(ev.data.text);
            break;
          case "cover_letter_txt":
            setCoverLetterTxt(ev.data);
            break;
          case "cover_letter_pdf":
            setCoverLetterPdf(ev.data);
            break;
          case "feedback":
            setRating(ev.data.rating);
            setFeedback(ev.data.text);
            break;
          case "error":
            setError(ev.data.message);
            break;
        }
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Generation failed.");
    } finally {
      setGenerating(false);
    }
  }

  const hasResults = resume || coverLetterPdf || coverLetterTxt;
  const showResults = hasResults || rating !== null;

  return (
    <AuthGuard>
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold text-uber-black">Generate application</h1>
        <p className="mt-1 text-sm text-uber-gray">
          Paste a job description, add optional answers, then generate a tailored resume, cover
          letter, and fit feedback. The resume is auto-matched from your master CVs.
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

      <section className="rounded-lg border border-uber-line bg-background p-5 lg:sticky lg:top-4">
        <h2 className="text-sm font-medium text-uber-black">Generate</h2>
        <div className="mt-3 flex flex-wrap gap-2">
          {TOGGLES.map((t) => (
            <button
              key={t.key}
              type="button"
              onClick={() => toggle(t.key)}
              aria-pressed={toggles[t.key]}
              className={`rounded-md border px-3 py-1.5 text-sm font-medium transition-colors ${
                toggles[t.key]
                  ? "border-uber-black bg-uber-black text-white"
                  : "border-uber-line bg-uber-bg text-uber-gray hover:text-uber-black"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>

        <button
          type="button"
          onClick={onGenerate}
          disabled={generating}
          className="mt-4 w-full rounded-md bg-uber-black px-4 py-3 text-sm font-semibold text-white transition-colors hover:bg-uber-green disabled:cursor-not-allowed disabled:opacity-50"
        >
          {generating ? "Generating…" : "Generate"}
        </button>

        {error && <p className="mt-3 text-sm font-medium text-red-600">{error}</p>}

        {showResults && (
          <div className="mt-4 flex flex-col gap-3">
            {rating !== null && <MatchRating rating={rating} />}
            {hasResults && (
              <div className="rounded-md border border-uber-green bg-uber-green-soft p-4">
                <div className="flex items-center gap-2">
                  <span className="inline-block h-2.5 w-2.5 rounded-full bg-uber-green" />
                  <h3 className="text-sm font-semibold text-uber-green-dark">Ready — review and download</h3>
                </div>
                {usedMasterCv && (
                  <p className="mt-1 text-xs text-uber-gray">Master CV matched: {usedMasterCv}</p>
                )}
                <div className="mt-3 flex flex-wrap gap-2">
                  {resume && <DownloadButton file={resume} label="Custom resume" />}
                  {coverLetterPdf && <DownloadButton file={coverLetterPdf} label="Cover letter" />}
                  {coverLetterTxt && <DownloadButton file={coverLetterTxt} label="Cover letter" />}
                </div>
              </div>
            )}
          </div>
        )}
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
        <div className="mt-4 border-t border-uber-line pt-4">
          <p className="text-xs text-uber-gray">
            Got the questions as a screenshot? Upload the image(s) and the model will answer
            each question into the list above (uses your OpenRouter key; images are not saved).
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <input
              type="file"
              accept="image/*"
              multiple
              onChange={(e) => setScreenshotFiles(Array.from(e.target.files ?? []))}
              className="text-sm text-uber-gray"
            />
            <button
              type="button"
              onClick={extractFromScreenshots}
              disabled={extracting || screenshotFiles.length === 0}
              className="rounded-md bg-uber-black px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-uber-green disabled:cursor-not-allowed disabled:opacity-50"
            >
              {extracting ? "Extracting…" : "Extract questions & answers"}
            </button>
          </div>
          {screenshotError && (
            <p className="mt-2 text-sm font-medium text-red-600">{screenshotError}</p>
          )}
        </div>
      </section>

      {letterText !== null && (
        <section className="rounded-lg border border-uber-line bg-background p-5">
          <h2 className="text-sm font-medium text-uber-black">Cover letter preview</h2>
          <pre className="mt-3 whitespace-pre-wrap rounded-md border border-uber-line bg-white p-4 text-sm">
            {letterText}
          </pre>
        </section>
      )}

      {feedback !== null && (
        <section className="rounded-lg border border-uber-line bg-background p-5">
          <h2 className="text-sm font-medium text-uber-black">Feedback</h2>
          <div className="mt-3 rounded-md border border-uber-line bg-white p-4">
            <ul className="space-y-2.5 text-sm text-uber-black">
              {feedback
                .split("\n")
                .map((l) => l.trim())
                .filter(Boolean)
                .map((line, i) => (
                  <li key={i} className="flex items-start gap-2.5">
                    <span className="mt-1.5 inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-uber-green" />
                    <span className="flex-1">{line.replace(/^[-•*]\s*/, "")}</span>
                  </li>
                ))}
            </ul>
          </div>
        </section>
      )}
    </div>
    </AuthGuard>
  );
}

function MatchRating({ rating }: { rating: number }) {
  const score = Math.max(0, Math.min(10, rating));
  const tone =
    score >= 8
      ? {
          badge: "bg-uber-green",
          bar: "bg-uber-green",
          border: "border-uber-green",
          soft: "bg-uber-green-soft",
          text: "text-uber-green-dark",
          label: "Strong match",
        }
      : score >= 5
        ? {
            badge: "bg-amber-500",
            bar: "bg-amber-500",
            border: "border-amber-400",
            soft: "bg-amber-50",
            text: "text-amber-700",
            label: "Partial match",
          }
        : {
            badge: "bg-red-500",
            bar: "bg-red-500",
            border: "border-red-400",
            soft: "bg-red-50",
            text: "text-red-700",
            label: "Weak match",
          };
  return (
    <div className={`flex items-center gap-4 rounded-xl border-2 p-5 ${tone.border} ${tone.soft}`}>
      <div
        className={`flex h-14 w-14 shrink-0 items-center justify-center rounded-full text-white ${tone.badge} shadow-lg ring-4 ring-white`}
      >
        <svg
          viewBox="0 0 24 24"
          className="h-7 w-7"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <circle cx="12" cy="12" r="10" />
          <circle cx="12" cy="12" r="6" />
          <circle cx="12" cy="12" r="2" />
        </svg>
      </div>
      <div className="min-w-0 flex-1">
        <p className={`text-xs font-semibold uppercase tracking-wider ${tone.text}`}>
          Job match · {tone.label}
        </p>
        <div className="mt-1 flex items-baseline gap-1.5">
          <span className={`text-5xl font-bold leading-none ${tone.text}`}>{score}</span>
          <span className="text-base font-medium text-uber-gray">/ 10</span>
        </div>
        <div className="mt-3 h-2 w-full overflow-hidden rounded-full bg-black/10">
          <div
            className={`h-full rounded-full ${tone.bar}`}
            style={{ width: `${score * 10}%` }}
          />
        </div>
      </div>
    </div>
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
