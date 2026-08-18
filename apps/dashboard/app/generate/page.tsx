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
  const [partErrors, setPartErrors] = useState<string[]>([]);
  const [letterText, setLetterText] = useState<string | null>(null);
  const [letterTextProvider, setLetterTextProvider] = useState<string | undefined>(undefined);
  const [rating, setRating] = useState<number | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [feedbackProvider, setFeedbackProvider] = useState<string | undefined>(undefined);
  const [questionsProvider, setQuestionsProvider] = useState<string | undefined>(undefined);
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
    setPartErrors([]);
    setGenerating(true);
    setResume(null);
    setCoverLetterPdf(null);
    setCoverLetterTxt(null);
    setLetterText(null);
    setLetterTextProvider(undefined);
    setRating(null);
    setFeedback(null);
    setFeedbackProvider(undefined);
    setQuestionsProvider(undefined);
    setUsedMasterCv(null);
    try {
      const req: GenerateRequest = {
        jobDescription,
        questions: rows.map(({ question }) => question.trim()).filter(Boolean),
        coverLetterFormats: formats,
        parts,
      };
      await generateApplication(req, (ev) => {
        switch (ev.event) {
          case "used_master_cv":
            setUsedMasterCv(ev.data.usedMasterCv);
            break;
          case "questions_answered": {
            // Backend answered the form questions from the CV + brag doc; fill
            // them into the matching rows (read-only display).
            const byQuestion = new Map(
              ev.data.answers.map((a) => [a.question.trim().toLowerCase(), a.answer])
            );
            setQuestionsProvider(ev.data.provider);
            setRows((r) =>
              r.map((row) =>
                byQuestion.has(row.question.trim().toLowerCase())
                  ? { ...row, answer: byQuestion.get(row.question.trim().toLowerCase())! }
                  : row
              )
            );
            break;
          }
          case "resume":
            setResume(ev.data);
            break;
          case "cover_letter_text":
            setLetterText(ev.data.text);
            setLetterTextProvider(ev.data.provider);
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
            setFeedbackProvider(ev.data.provider);
            break;
          case "error":
            // A part-specific failure (resume/letter/feedback) shouldn't be
            // mistaken for a whole-run failure — collect it separately.
            if (ev.data.part) {
              setPartErrors((prev) => [...prev, ev.data.message]);
            } else {
              setError(ev.data.message);
            }
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
        <div className="inline-flex items-center gap-2 rounded-full border border-black/10 bg-black/5 px-3 py-1 text-sm font-bold uppercase tracking-widest">
          <span className="h-2 w-2 rounded-full bg-brand animate-pulse" />
          Generate
        </div>
        <h1 className="mt-4 font-jura text-3xl font-bold tracking-tighter sm:text-4xl">
          Build your application
        </h1>
        <p className="mt-2 text-sm text-black/60">
          Paste a job description, add optional questions (the app answers them from your CV
          and brag doc), then generate a tailored resume, cover letter, and fit feedback. The
          resume is auto-matched from your master CVs.
        </p>
      </div>

      <section className="rounded-2xl border border-black/10 bg-white p-5 shadow-sm sm:p-6">
        <label htmlFor="job-description" className="block text-[11px] font-bold uppercase tracking-widest text-black/45">
          Job description
        </label>
        <textarea
          id="job-description"
          value={jobDescription}
          onChange={(e) => setJobDescription(e.target.value)}
          placeholder="Paste the job posting here…"
          rows={8}
          className="mt-2 w-full resize-y rounded-lg border border-black/10 bg-white px-3 py-2.5 text-sm placeholder:text-black/35 focus:border-black/40 focus:outline-none"
        />
      </section>

      <section className="rounded-2xl border border-black/10 bg-white p-5 shadow-sm sm:p-6 lg:sticky lg:top-4">
        <h2 className="font-jura text-sm font-bold uppercase tracking-widest">Generate</h2>
        <div className="mt-3 flex flex-wrap gap-2">
          {TOGGLES.map((t) => (
            <button
              key={t.key}
              type="button"
              onClick={() => toggle(t.key)}
              aria-pressed={toggles[t.key]}
              className={`rounded-lg px-3 py-1.5 text-xs font-bold uppercase tracking-widest transition-all ${
                toggles[t.key]
                  ? "bg-black text-white"
                  : "border border-black/10 text-black/55 hover:bg-black/5 hover:text-black"
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
          className="mt-4 w-full rounded-lg bg-black px-4 py-3 text-sm font-bold uppercase tracking-widest text-white transition-all hover:bg-black/80 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50"
        >
          {generating ? "Generating…" : "Generate"}
        </button>

        {error && <p className="mt-3 text-sm font-medium text-red-600">{error}</p>}

        {partErrors.length > 0 && (
          <div className="mt-3 flex flex-col gap-2">
            {partErrors.map((msg, i) => (
              <p key={i} className="text-sm font-medium text-red-600">
                Part failed — {msg}
              </p>
            ))}
          </div>
        )}

        {showResults && (
          <div className="mt-4 flex flex-col gap-3">
            {rating !== null && <MatchRating rating={rating} />}
            {hasResults && (
              <div className="rounded-xl border border-emerald-500/30 bg-emerald-50 p-4">
                <div className="flex items-center gap-2">
                  <span className="inline-block h-2.5 w-2.5 rounded-full bg-brand" />
                  <h3 className="text-sm font-semibold text-emerald-700">Ready — review and download</h3>
                </div>
                {usedMasterCv && (
                  <p className="mt-1 text-xs text-black/50">Master CV matched: {usedMasterCv}</p>
                )}
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  {resume && <Artifact file={resume} label="Custom resume" />}
                  {coverLetterPdf && <Artifact file={coverLetterPdf} label="Cover letter" />}
                  {coverLetterTxt && <Artifact file={coverLetterTxt} label="Cover letter" />}
                </div>
              </div>
            )}
          </div>
        )}
      </section>

      <section className="rounded-2xl border border-black/10 bg-white p-5 shadow-sm sm:p-6">
        <div className="flex items-center justify-between">
          <h2 className="font-jura text-sm font-bold uppercase tracking-widest">Optional questions</h2>
          <div className="flex items-center gap-2">
            {questionsProvider && <ProviderBadge provider={questionsProvider} />}
            <button
              type="button"
              onClick={addRow}
              className="rounded-lg bg-black px-3 py-1.5 text-xs font-bold uppercase tracking-widest text-white transition-all hover:bg-black/80 active:scale-[0.98]"
            >
              + Add question
            </button>
          </div>
        </div>
        <div className="mt-3 flex flex-col gap-3">
          {rows.length === 0 && <p className="text-sm text-black/50">No questions yet — e.g. “Why do you want to work here?”</p>}
          {rows.map((row) => (
            <div key={row.id} className="flex flex-col gap-2">
              <div className="flex items-start gap-2">
                <input
                  value={row.question}
                  onChange={(e) => updateRow(row.id, { question: e.target.value })}
                  placeholder="Question"
                  className="w-full rounded-lg border border-black/10 bg-white px-3 py-2.5 text-sm placeholder:text-black/35 focus:border-black/40 focus:outline-none"
                />
                <button
                  type="button"
                  onClick={() => removeRow(row.id)}
                  aria-label="Remove question"
                  className="grid h-8 w-8 shrink-0 place-items-center rounded-full border border-black/10 text-black/50 transition-all hover:border-black hover:text-black"
                >
                  ✕
                </button>
              </div>
              {row.answer && (
                <p className="rounded-lg border border-black/5 bg-black/[0.02] px-3 py-2 text-sm text-black/80">
                  {row.answer}
                </p>
              )}
            </div>
          ))}
        </div>
        <div className="mt-4 border-t border-black/10 pt-4">
          <p className="text-xs text-black/50">
            Got the questions as a screenshot? Upload the image(s) and the model will answer
            each question into the list above (uses your OpenRouter key; images are not saved).
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <input
              type="file"
              accept="image/*"
              multiple
              onChange={(e) => setScreenshotFiles(Array.from(e.target.files ?? []))}
              className="text-sm text-black/50"
            />
            <button
              type="button"
              onClick={extractFromScreenshots}
              disabled={extracting || screenshotFiles.length === 0}
              className="rounded-lg bg-black px-3 py-1.5 text-xs font-bold uppercase tracking-widest text-white transition-all hover:bg-black/80 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50"
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
        <section className="rounded-2xl border border-black/10 bg-white p-5 shadow-sm sm:p-6">
          <div className="flex items-center gap-2">
            <h2 className="font-jura text-sm font-bold uppercase tracking-widest">Cover letter preview</h2>
            <ProviderBadge provider={letterTextProvider} />
            <CopyButton text={letterText} />
          </div>
          <pre className="mt-3 whitespace-pre-wrap rounded-xl border border-black/10 bg-white p-4 text-sm">
            {letterText}
          </pre>
        </section>
      )}

      {feedback !== null && (
        <section className="rounded-2xl border border-black/10 bg-white p-5 shadow-sm sm:p-6">
          <div className="flex items-center gap-2">
            <h2 className="font-jura text-sm font-bold uppercase tracking-widest">Feedback</h2>
            <ProviderBadge provider={feedbackProvider} />
          </div>
          <div className="mt-3 rounded-xl border border-black/10 bg-white p-4">
            <ul className="space-y-2.5 text-sm text-black/80">
              {feedback
                .split("\n")
                .map((l) => l.trim())
                .filter(Boolean)
                .map((line, i) => (
                  <li key={i} className="flex items-start gap-2.5">
                    <span className="mt-1.5 inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-brand" />
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

// Copy-to-clipboard button with a clipboard icon; flips to a checkmark when copied.
function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  async function handleClick() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // silent: copy is a convenience, not critical
    }
  }

  return (
    <button
      type="button"
      onClick={handleClick}
      aria-label="Copy to clipboard"
      title={copied ? "Copied" : "Copy to clipboard"}
      className="ml-auto grid h-9 w-9 place-items-center rounded-full border border-black/10 text-black/60 transition-all hover:border-black hover:text-black"
    >
      <svg
        viewBox="0 0 24 24"
        className="h-4 w-4"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        {copied ? (
          <>
            <polyline points="20 6 9 17 4 12" />
          </>
        ) : (
          <>
            <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
            <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
          </>
        )}
      </svg>
    </button>
  );
}

function MatchRating({ rating }: { rating: number }) {
  const score = Math.max(0, Math.min(10, rating));
  const tone =
    score >= 8
      ? {
          badge: "bg-emerald-500",
          bar: "bg-emerald-500",
          border: "border-emerald-500/30",
          soft: "bg-emerald-50",
          text: "text-emerald-700",
          label: "Strong match",
        }
      : score >= 5
        ? {
            badge: "bg-amber-500",
            bar: "bg-amber-500",
            border: "border-amber-400/40",
            soft: "bg-amber-50",
            text: "text-amber-700",
            label: "Partial match",
          }
        : {
            badge: "bg-red-500",
            bar: "bg-red-500",
            border: "border-red-400/40",
            soft: "bg-red-50",
            text: "text-red-700",
            label: "Weak match",
          };
  return (
    <div className={`flex items-center gap-4 rounded-2xl border bg-white p-5 ${tone.border} ${tone.soft}`}>
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
        <p className={`text-[11px] font-bold uppercase tracking-widest ${tone.text}`}>
          Job match · {tone.label}
        </p>
        <div className="mt-1 flex items-baseline gap-1.5">
          <span className={`font-jura text-5xl font-bold leading-none ${tone.text}`}>{score}</span>
          <span className="text-base font-medium text-black/50">/ 10</span>
        </div>
        <div className="mt-3 h-2 w-full overflow-hidden rounded-full bg-black/5">
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
      className="rounded-lg border border-black/10 px-4 py-2 text-xs font-bold uppercase tracking-widest text-black/70 transition-all hover:bg-black/5 hover:text-black disabled:opacity-50"
    >
      {busy ? "Fetching…" : `${label} · ${file.kind.toUpperCase()}`}
    </button>
  );
}

// A download artifact + the badge showing which provider rendered it.
function Artifact({ file, label }: { file: GeneratedFile; label: string }) {
  return (
    <span className="inline-flex items-center gap-2">
      <DownloadButton file={file} label={label} />
      <ProviderBadge provider={file.provider} model={file.model} />
    </span>
  );
}

const PROVIDER_BADGE_STYLES: Record<string, string> = {
  gemini: "border-blue-200 bg-blue-50 text-blue-700",
  groq: "border-orange-200 bg-orange-50 text-orange-700",
  openrouter: "border-purple-200 bg-purple-50 text-purple-700",
  ollama: "border-green-200 bg-green-50 text-green-700",
};

// Small pill naming the model provider (Gemini / Groq / OpenRouter / Ollama)
// that rendered the artifact next to it. Hidden when unknown (e.g. previews).
function ProviderBadge({ provider, model }: { provider?: string; model?: string }) {
  if (!provider) return null;
  const label = provider === "openrouter" ? "OpenRouter" : provider.charAt(0).toUpperCase() + provider.slice(1);
  const style = PROVIDER_BADGE_STYLES[provider] ?? "border-gray-200 bg-gray-50 text-gray-600";
  return (
    <span
      title={model ? `Rendered by ${model}` : undefined}
      className={`inline-flex items-center whitespace-nowrap rounded-full border px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-widest ${style}`}
    >
      {label}
    </span>
  );
}
