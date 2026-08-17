# Today

Day 1 — Ingestion Foundation: Tag-Based Discovery, Normalization, Dedupe
Course lesson: GenAI 01 (Introduction to Generative AI and LLMs) — light AI day, heavy data engineering
The design principle for this day: you should never miss a good job because you didn't already know the company.
Discovery is tag-driven, not company-driven — you describe the kind of role you want (tags + constraints), and the
system finds companies you've never heard of. A company list is an optional accelerator, never a required input.
Agenda - Supabase project; jobs , profiles , applications schema; pgvector enabled; RLS scaffolding from the first
migration. - The adapter interface, written before the second adapter exists: fetch(searchConfig) → RawJob[] and
normalize(raw) → Job . Adding a tenth source should be a twenty-line file, not a new subsystem. - The search config is the
core input — role tags ("full stack", "AI engineer", "software engineer", "backend") plus constraints (remote, timezone
overlap, seniority, contractor-ok). This, not a company list, is what defines your search. - Primary path — tag-based
aggregator adapters (no company list): Himalayas, RemoteOK, Remotive, Arbeitnow, Jobicy. You pass tags +
constraints; they return matching jobs across every company they know about. This is what casts the wide net and surfaces
companies you'd never have named. - The speed layer — auto-grown ATS polling: the ATS-direct endpoints
(Greenhouse/Lever/Ashby/Workable) are per-company by design, so instead of hand-listing companies, derive the poll set
from discovery: whenever an ingested job resolves to one of those boards, extract the company and add it to the ATS-poll
set automatically. You start with zero named companies; within a week the system is fast-polling dozens it found organically
— recovering the 18–48h speed edge without you ever curating a list. (You may optionally seed a few dream companies to
fast-poll from day one; it's never required and nothing good is excluded for being absent from it.) - Deduplication, two
passes: exact content_hash first (cheap), fuzzy match on (company, title, location) for survivors. Never discard
duplicates — store seen_on[] and keep the earliest first_seen_at .
By end of day: a jobs table filling from tag-based aggregators across companies you didn't have to name, with the autogrow mechanism beginning to populate the ATS speed layer, deduplicated, with working apply URLs and provenance.
How to get there 1. Write the interface first. The temptation is to hack the Greenhouse adapter and generalize later; you
will not generalize later, you will write five bespoke scrapers and hate all of them. 2. Build the tag-based aggregator
adapters first and confirm the wide net works before touching the ATS layer — the aggregators are what guarantee you
never miss a role for not knowing the company. 3. The auto-grow ATS set is just a table ( company_slug, ats_type,
discovered_from, added_at ) written to whenever a job resolves to a known ATS board. ATS polling reads that table; you
never hand-edit it (though you can seed rows for dream companies). This is the elegant part — the speed advantage
becomes an emergent output of discovery, not a curated input. 4. first_seen_at is not bookkeeping — it is the evidence for
your speed claim and later becomes a UI feature ("seen 2 days before it hit LinkedIn"). Set it correctly on first insert and
never overwrite it. 5. Ingestion should deliberately over-collect. A tag search for "AI engineer" will pull noise (prompt
gigs, sales-engineer roles, unrelated ML-ops) — that's correct. The Screener (Days 4–6) does the strict filtering against your
actual resume. Keep the two jobs mentally separate: ingest wide, screen narrow. 4. Rate-limit politely, cache aggressively,
and set a descriptive User-Agent. These are free public endpoints offered in good faith; behave accordingly.

# Done

## 2026-08-16 — Architecture hardening: HTTP decoupled from services (P0) + test seams (P1)

- **P0 — domain errors replace HTTPException in the logic layer.** New `errors.py`:
  `GenerationError` (base, `status_code=502`, clean `str()`), `TokenBudgetError` (400),
  `CompileError` (502). `llm._fit_max_tokens` → `TokenBudgetError`; `compile._compile` and
  `services/resume._fine_tune` → `CompileError`. `services/sse._stream_error` renders
  `GenerationError` message without a class prefix (SSE output unchanged). `main.py`
  registers ONE `GenerationError` exception handler → `{detail, status_code}` — the single
  translation point, so the future MCP server and Radar cron can catch these directly
  instead of sniffing HTTPException.
- **P1 — `_generate_stream` moved routes/generate.py → `services/pipeline.py`** (orchestration
  is transport-neutral; routes/generate.py slimmed 254 → 131 lines, now pure HTTP validation).
  Test monkeypatch targets retargeted `routes.generate.*` → `services.pipeline.*` (the stream
  tests patch at the module where the pipeline resolves its names).
- **P1 — test seams.** New `tests/conftest.py` with `authed_client` fixture (TestClient over the
  real app + `app.dependency_overrides[require_service_user]` → stub user) and
  `tests/test_routes.py` with two route-level tests: one proves the override lets a real route
  run with a faked store; one proves a `CompileError` raised inside a route becomes HTTP 502 via
  the handler. Route-level testing (needed for Radar/Screener/etc.) is now possible.
- Checks: pytest **39 pass** (37 baseline + 2 new route tests; the 1 pre-existing ASD-STE100
  prompt-string failure untouched, verified on baseline earlier), ruff clean on all new/changed
  files (only the pre-existing store.py E501 remains), OpenAPI still lists the same 12 paths,
  domain errors render correct statuses (400/502) via TestClient ASGI stack.
- No schema change (schema.md untouched). Logged per Working Agreement.

## 2026-08-16 — Backend modularization: main.py (1032 lines) → routes/ + services/

- Goal: modular, easy-to-follow backend without breaking anything. Zero behavior
  change — all routes, JSON shapes, `uvicorn main:app` entrypoint identical.
- `main.py` 1032 → ~90 lines: FastAPI app + CORS + `/out` mount + global LLM error
  handler + 4× `include_router`. No endpoints or logic left in it.
- `schemas.py` (new): all Pydantic models (Answer, Credentials, RefreshRequest,
  GenerateRequest, SettingsUpdate, LinksUpdate).
- `routes/` (new, one APIRouter per resource): `auth.py` (/api/auth/*),
  `profile.py` (master-cvs + brag-doc CRUD), `settings.py` (/api/settings, /api/links),
  `generate.py` (/api/generate SSE + /api/screenshot-questions + `_generate_stream`).
- `services/` (new, pure logic): `sse.py`, `text.py` (clamps + JSON-from-LLM helpers),
  `resume.py` (fine-tune/build/pick), `cover_letter.py`, `feedback.py`, `questions.py`.
- Helpers promoted to their owning module: `_fit_max_tokens` → `llm.py` (provider
  budgeting), `_compile`/`_out_name` → `compile.py` (LaTeX).
- `tests/test_main.py` retargeted: imports → new module homes; monkeypatch strings
  (`main.X`) → `services.resume.X` / `routes.generate.X` / `llm.X` per call path;
  the pdf-format stream test now patches `_compile` at both `services.resume` (resume
  path) and `routes.generate` (cover-letter-pdf path).
- Checks: pytest 37 pass (1 pre-existing ASD-STE100 prompt-string failure, verified
  identical on the pre-change baseline via stash), ruff clean on all new files (only
  pre-existing store.py E501 remains), OpenAPI spec lists all 11 path patterns /
  17 endpoints unchanged, `uvicorn main:app` boots and serves /docs 200.
- No schema change (schema.md untouched).

## 2026-08-16 — Fix: "Stuck at Generating…" — provider failover on quota exhaustion

- Symptom: clicking Generate shows "Generating…" forever — the SSE stream emitted
  `used_master_cv` then went silent (no `done`, no `error`).
- Root cause: `GEMINI_API_KEY` is set (apps/api/.env), so Gemini became the primary
  provider, and the **Gemini free tier was quota-exhausted** (429 "limit: 20/day",
  verified live). `chat()` slept 45s and retried *the same dead provider* on 429,
  with no failover — 3 concurrent parts × ~90s+ of futile retries read as "stuck".
- Fix (apps/api/llm.py): `_endpoint()`/`_vision_endpoint()` refactored into
  `_provider_chain()`/`_vision_provider_chain()` (Ollama → Gemini → OpenRouter →
  Groq). New `_post_completion()` walks the chain: quota/rate (429/413) or timeout
  on a non-last provider fails over immediately; only the *last* provider (Groq)
  keeps the sleep-and-retry (its rolling per-minute TPM window actually recovers).
  `chat()` and `vision_chat()` now share it. `_endpoint()` kept as the chain head
  so `active_provider()` semantics and Settings readout are unchanged.
- Tests: `test_chat_fails_over_to_next_provider_on_quota`,
  `test_chat_raises_when_all_providers_exhausted`,
  `test_provider_chain_orders_gemini_openrouter_groq` (test_llm.py).
- Checks: pytest 37 pass (1 pre-existing ASD-STE100 failure untouched), ruff clean.
- Verified end-to-end against the live server: generate now completes with
  `resume` + `feedback` + `done` in ~4.5s (was hanging), via Groq fallback.
  Repro users/CVs/auth cleaned up (service_users 20-23 removed).
- Note: the fix makes the *fallback* work; the Gemini quota itself is a free-tier
  daily cap. If both Gemini and Groq are exhausted, generation fails with a clear
  error instead of hanging.

## 2026-08-16 — Fix: "Model produced invalid LaTeX (no documentclass)" — splice master preamble

- Symptom persisted after the hint-retry fix: resume generation still 502 —
  "Model produced invalid LaTeX (no documentclass). Try again."
- Root cause: the fine-tune prompt asks for keyword-level edits, so the model
  occasionally returns body-only .tex (drops the whole preamble incl. documentclass).
  The hint retry just burned another (rate-limited) LLM call and produced the same.
- Fix: `_repair_missing_preamble` (apps/api/main.py) splices the grounded master
  preamble back on deterministically — prepends the master's text through
  `\begin{document}` (whose commands like \resumeItem the body already relies on),
  and re-appends `\end{document}` if the body dropped it. No extra LLM call.
- Tests: `test_repair_missing_preamble_splices_master_when_body_only`,
  `test_repair_missing_preamble_passthrough_when_documentclass_present`,
  `test_fine_tune_splices_master_preamble_when_documentclass_missing`.
- Checks: pytest 34 pass (1 pre-existing ASD-STE100 failure untouched), ruff clean.

## 2026-08-16 — Fix: "Model produced invalid LaTeX (no documentclass)" retry sent an identical prompt

- Symptom: resume generation 502 — "Model produced invalid LaTeX (no documentclass).
  Try again."
- Root cause: `_fine_tune` retried the same `user` prompt with no hint when the model's
  output lacked `\documentclass`, so the retry failed the same way.
- Fix: `_fine_tune` (apps/api/main.py) appends "Your previous response was missing the
  \documentclass declaration. Start with \documentclass{...}" to the retry prompt.
- Test: `test_fine_tune_retry_hints_documentclass_when_missing` (fake first call returns
  prose, second returns valid LaTeX; asserts the hint reached the second prompt).
- Checks: pytest 32 pass (1 pre-existing ASD-STE100 failure untouched), ruff clean.

## 2026-08-16 — Free provider: Google AI Studio (Gemini) replaces paid OpenRouter

- Root cause of the repeated 402s: the saved OpenRouter key put every generation
  (and screenshot questions) on the **paid** `google/gemini-2.5-flash`; Gemini has
  no `:free` variant on OpenRouter, so credits drained. The same model is **free**
  on Google AI Studio's OpenAI-compatible endpoint — swapped in as the top default.
- `apps/api/llm.py`: new `GEMINI_BASE_URL = https://generativelanguage.googleapis.com/v1beta/openai`.
  `_endpoint()` precedence is now Ollama → **Gemini** (key set) → OpenRouter (key set)
  → Groq. New `_vision_endpoint()` (Gemini wins for screenshot questions, OpenRouter
  BYOK fallback, clear error otherwise); `vision_chat` uses it. `active_provider()`
  gained `"gemini"`. No credit reservation + huge free TPM = the 402 class of bugs is gone.
- `apps/api/config.py`: `gemini_api_key` / `gemini_model` / `gemini_vision_model`
  (defaults `gemini-3.6-flash`); documented in `.env.example`. `GEMINI_API_KEY` set in `.env`.
  Discovery during verification: `gemini-2.5-flash` is **no longer available to new users**
  (404); live-tested `gemini-3.6-flash`, `gemini-3.5-flash`, `gemini-3.1-flash-lite` all 200
  on the free key — picked `gemini-3.6-flash` (current docs default). Verified a real
  `chat()` round-trip returns content (small `max_tokens` can be eaten by the model's
  thinking budget — real budgets ≥800 are fine).
- Migration `20260816000000_service_users_gemini_key.sql` **pushed** ✓:
  `service_users.gemini_api_key text not null default ''` (verified column live).
  `store.py`: `set_service_user_gemini_key`; `user_settings.py`: `get/set_gemini_key`
  (same DB-first, env-fallback pattern as OpenRouter).
- `apps/api/main.py`: `/api/settings` returns `gemini_key_set`; `SettingsUpdate` accepts
  `gemini_api_key` and PUT saves it. `_fit_max_tokens` untouched (non-Groq → floor already).
- `apps/dashboard`: `lib/api.ts` provider union + `geminiKeySet` + `setGeminiKey`;
  `/settings` gets a "Gemini API key (free, from AI Studio)" field + save button, and
  the provider readout shows "Gemini (free)" when active.
- Tests: `test_llm.py` — gemini precedence, gemini-outranks-openrouter, vision
  endpoint preference + no-key error; existing openrouter/groq tests updated to
  neutralize the env gemini key. 31 pass (1 pre-existing ASD-STE100 failure
  untouched); `ruff` clean for changed files; `npm run lint` ✓; `npm run build` ✓.
- Note: user's saved OpenRouter key stays in the DB (dormant fallback); clear the
  Gemini key in Settings to fall back to it.

## 2026-08-16 — Fix: OpenRouter 402 "can only afford N tokens" (credit reservations)

- Symptom: every LLM call failed with `LLM provider error (402)` — "You requested up
  to 5000 tokens, but can only afford 3552".
- Root cause: OpenRouter reserves/bills the full `max_tokens` a request asks for. On
  non-Groq providers `_fit_max_tokens` returned the 5000 cap (`max(floor, MAX_OUT_TOKENS)`)
  for every call, so fine-tune AND feedback each reserved 5000 tokens — exceeding the
  account's remaining credit in one generate.
- Fix: for non-Groq providers `_fit_max_tokens` now returns just the task `floor`
  (fine-tune 3000, feedback 800); cover letter already hardcoded 1500. Total per
  generate reservation drops ~15K → ~5K. Groq TPM-budget path unchanged.
- Test: `test_fit_max_tokens_non_groq_returns_floor_not_ceiling` (27 pass; 1
  pre-existing ASD-STE100 failure untouched). `ruff` ✓.

## 2026-08-16 — Fix: LLM resume with bare `&` broke LaTeX compile

- Symptom: resume generation 502 — "tectonic failed for custom-resume-*: Forbidden
  control sequence found while scanning use of \check@nocorr@".
- Root cause: the model emitted a bare `&` inside `\textbf{...}` in resume body text
  (e.g. `{AI & Full-Stack Engineering Lead}`, `{... Job Search & Interview System}`).
  `\textbf{...}` expands to `\text@command{\bfseries}{...}`; the argument's braces are
  stripped during expansion, so the `&` lands at brace level 0 inside the `tabular*`
  cell and prematurely terminates it → runaway argument. Templates must use `\&`.
- Fixes (apps/api):
  - `FINE_TUNE_SYSTEM` now instructs "Escape special characters in text (use \& not &,
    \% not %, \_ not _, \# not #)".
  - `_fine_tune(master_tex, brag_text, jd, error_hint="")` — when a compile fails, the
    error tail is appended to the next prompt ("Fix this LaTeX error...").
  - New `_build_resume` — fine-tune + compile loop: a failed compile earns one
    re-fine-tune (with the error tail as a hint), then fails loud. Wired into the
    resume branch of `_generate_stream` (replaces the raw fine-tune→compile pair).
- Verified: escaping the body `&`s in the exact failing `custom-resume-5be69d94.tex`
  compiles to a valid 41KB PDF.
- Tests: `test_build_resume_regenerates_once_on_compile_failure` +
  `test_fine_tune_appends_compile_error_hint` (26 pass; 1 pre-existing ASD-STE100
  failure untouched). `ruff` ✓.

## 2026-08-16 — Generate speed: fast model default, parallel artifacts, keyword-only fine-tune

- **Faster model.** Default OpenRouter model `meta-llama/llama-3.3-70b-instruct` →
  `google/gemini-2.5-flash` (`config.py`); the 70B rewrite was the dominant cost.
  Override stays available via `OPENROUTER_MODEL`.
- **Parallel artifacts.** `_generate_stream` is now an async generator: resume, cover
  letter, and feedback run concurrently (`asyncio.create_task` + `asyncio.as_completed`,
  blocking LLM/compile work via `asyncio.to_thread` — which also keeps the per-user
  contextvar propagation intact). Each artifact is still emitted the instant its branch
  finishes; per-part failure isolation unchanged. SSE event order is now completion
  order, so the stream tests assert event *sets* instead of order (frontend already
  dispatches by type, order-independent).
- **Keyword-only fine-tune.** `FINE_TUNE_SYSTEM` rewritten: preserve every section,
  bullet, and metric; make only minimal keyword-level edits to match the JD's
  terminology, add a skill only if it's in the brag doc, no invented experience/metrics.
  Also fixed the prompt's missing-space bug ("preservedDon't", "recruiterKeep").
- Checks: pytest 24 ✓ (1 pre-existing ASD-STE100 failure, untouched), ruff ✓,
  `npm run lint` ✓, `npm run build` ✓. No schema change.

## 2026-08-15 — Feedback: robust JSON parse + prominent rating & formatted list

- Raw-JSON bug: the model sometimes wraps prose around the JSON, so `_parse_feedback`
  fell back to the raw text (shown verbatim). Now `_first_json_object` pulls the first
  `{...}` block out of the output, `_clamp_rating` clamps 1-10, feedback accepts string or
  list-of-strings, and a `"rating": N` regex fallback covers unparseable output. Added
  prose-wrapped + feedback-as-array test cases (23 pass).
- UI: `MatchRating` redesigned to stand out — colored border + soft background card,
  larger 56px logo badge with white ring, big `text-5xl` score, thicker progress bar
  (green/amber/red by score). Feedback card now renders a proper bullet list with green
  dot markers instead of raw pre text.

## 2026-08-15 — Fix: model prose before \\documentclass broke resume compile

- Symptom: resume generation 502 — "LaTeX Error: Missing \begin{document}"; the model
  prepended "Here is the modified LaTeX resume tailored to the job description:" to its
  output, so the prose landed at the top of the .tex (fence-stripping only handled ```).
- Fix: `_extract_latex_document` cuts everything before the first `\documentclass` and
  after `\end{document}` (case-insensitive); `_clean_model_latex` applies fence-stripping
  then extraction, used in both `_fine_tune` attempts (retry path included).
- Tests: `_extract_latex_document` prose/trailing-commentary drop + no-documentclass
  passthrough + `_clean_model_latex` fences+prose (23 pass; 2 pre-existing failures).
  `ruff` clean for new code.

## 2026-08-15 — Feedback non-optional + 1-10 job-match rating with UI

- **Feedback is always generated.** The Feedback toggle is gone from `/generate`; the
  backend emits a `feedback` event unconditionally (no longer gated on `parts`), and the
  master CV is always loaded (feedback always needs it). `GenerateRequest.parts` still
  accepts `"feedback"` for backward compat, but it's ignored.
- **Rating + concise output.** `FEEDBACK_SYSTEM` now asks for JSON `{"rating": 1-10,
  "feedback": "..."}` (max 6 bullets, concise). `_feedback` returns `(rating, text)`
  via new `_parse_feedback` (handles fences, clamps rating 1-10, falls back to
  `(None, raw)` on bad JSON). SSE event: `{"rating": rating, "text": feedback}`.
- **Rating UI.** New `MatchRating` card at the top of the results panel: circular logo
  badge (target icon, green/amber/red by score), `N/10` score, and a progress bar.
  Frontend `GenerateEvent.feedback` now carries `rating`; `rating` state drives the card.
- Tests: `_parse_feedback` (rating/text/clamp/garbage) + stream always-emits-feedback
  added (19 pass; 2 pre-existing prompt-string failures remain). `ruff` clean for new
  code, `npm run lint` ✓, `npm run build` ✓.

## 2026-08-15 — Screenshot questions: vision extracts + answers into the Q&A list

- New `POST /api/screenshot-questions`: accepts up to 6 image uploads, reads them into
  memory, base64s them into the vision call as data URIs — **never saved** to disk, storage,
  or DB. Model extracts every visible question and answers each in the candidate's voice,
  grounded in the master CV + full brag doc (never invents experience/metrics). Returns
  `[{question, answer}, ...]`.
- Vision runs through **OpenRouter (BYOK)** only — `vision_chat` in `llm.py` sends
  `image_url` content parts to `openrouter_vision_model` (default
  `google/gemini-2.5-flash`, overridable via `OPENROUTER_VISION_MODEL`; the earlier
  `gemini-2.0-flash-001` default 404'd — model slug retired). Clear error if no OpenRouter
  key (free-tier Groq is text-only). Images capped at 5MB each.
- Helpers: pure `_screenshot_questions_prompt` + `_parse_question_answers` (handles bare
  array, `{questions:[...]}`, markdown fences, garbage → clamps via `_clamp_answers`).
- Frontend: "Optional questions" card gains a screenshot file-picker + **Extract questions
  & answers** button; extracted Q&A rows are appended to the list (deduped by question).
  `extractScreenshotQuestions` in `lib/api.ts`.
- Checks: `pytest` 18 pass (2 pre-existing prompt-string failures remain), `ruff` clean for
  new code, `npm run lint` ✓, `npm run build` ✓. No schema change.

## 2026-08-15 — Generate streams each artifact as it's ready (SSE)

- `/api/generate` now returns `text/event-stream` and emits each artifact the moment it
  finishes, instead of one JSON blob at the end: `used_master_cv` (immediately), `resume`
  (after fine-tune + compile), `cover_letter_text` → `cover_letter_txt`/`cover_letter_pdf`,
  `feedback`, then `done`. A failed part emits an `error` event and the rest still run
  (per-part try/except in `_generate_stream`). Pre-stream validation (400s) unchanged.
- `FileOut`/`GenerateResult` removed (files now embedded in SSE event data).
- Frontend `generateApplication(req, onEvent)` streams the body via `fetch` + reader,
  parses SSE (`readSSE`/`dispatchEvent`), refreshes on 401 like the rest. `/generate`
  updates each panel as events arrive instead of all-or-nothing.
- Tests: `test_generate_stream_emits_each_part_in_order` +
  `test_generate_stream_partial_failure_isolates_the_part` (4 pass). Lint ✓, build ✓.
  The 2 remaining pytest failures are the pre-existing prompt-string mismatches.

## 2026-08-15 — Generate page: full brag doc + toggles + feedback

- **Full brag doc to model calls.** `api_generate` no longer summarizes the brag doc —
  `_summarize_brag` / `BRAG_SUMMARY_SYSTEM` / `set_brag_summary` deleted; the raw stored
  brag doc is passed verbatim to `_fine_tune` and the new feedback call. Groq free-tier
  budget is still guarded by `_fit_max_tokens` (clear 400 if the full doc overshoots).
  `module_brag_docs.summary` column left in place but unused (noted in schema.md).
- **New `feedback` part.** `GenerateRequest.parts` now accepts `"feedback"`; new
  `_feedback` + pure `_feedback_prompt` (grounded only in resume + brag doc + JD, always
  bullet-point output). Returns as `GenerateResult.feedback`. Test added:
  `test_feedback_prompt_grounded_in_resume_and_brag_and_bullets`.
- **Cover letter now emits both formats.** `cover_letter_format` (single) → `cover_letter_formats`
  (list); result splits into `cover_letter_pdf` / `cover_letter_txt` so one request can return
  PDF and plain-text versions of the same letter.
- **Frontend `/generate`:** the two buttons replaced by four option toggles (Resume · Cover
  letter PDF · Cover letter text · Feedback) + one **Generate** button (disabled when nothing
  selected). Feedback renders as a bullet list in its own card; results reset between runs so
  stale files never linger. `lib/api.ts` types/request/result mapping updated to match.
- Checks: `poetry run pytest` 14 pass (+1 new feedback test); the 2 failures are
  pre-existing (prompt strings the uncommitted `main.py` no longer contains — untouched here).
  `ruff` clean for new code (2 pre-existing E501 nits remain). `npm run lint` ✓, `npm run build` ✓.
- Schema: no migration; `summary` column usage retired (schema.md updated).

## 2026-08-13 — Resume fine-tune: preserve content and metrics

- `FINE_TUNE_SYSTEM` rewritten: "PRESERVE ALL CONTENT: keep every section, bullet, and metric —
  never delete, condense, summarize, or shorten anything. Numbers and metrics must appear EXACTLY
  as written in the source. The tailored resume must be at least as detailed as the master."
  Reorder/re-emphasize only.
- `_fine_tune` output token floor raised 1500 → 3000 so the model isn't forced to truncate a full
  resume on limited budgets (checked: still fits the Groq free-tier TPM budget).
- Test: `test_fine_tune_prompt_never_trims_content_or_metrics` pins the preservation clauses
  (15 pass). Ruff clean for new code.

## 2026-08-13 — Cover letter: ASD-STE100 prompt + PDF download button

- `_cover_letter_prompt` system prompt now instructs ASD-STE100 (Simplified Technical English):
  short sentences, one idea per sentence, simple unambiguous vocabulary. Test asserts
  `ASD-STE100` in the prompt.
- Fixed the missing PDF cover-letter download: `lib/api.ts` `generateApplication` always mapped
  the cover letter to the text version (backend returns `cover_letter_text` even in PDF mode), so
  the download button never produced the PDF. Now maps the server's actual `cover_letter` file
  (PDF with url in pdf mode, text file in text mode); `text` populated only as the fallback
  content. Button now shows `Cover letter · PDF` in pdf mode.
- Checks: pytest 14 ✓, ruff clean for new code, lint ✓, build ✓.

## 2026-08-13 — Cover letter: model gets user name + links

- `auth.py` `require_service_user` now returns `name` from the JWT's `n` claim
  (`user_metadata.n` preferred, fallback `app_metadata.n`).
- `main.py` `api_generate` passes `_sv["name"]` + `get_links()` into `_cover_letter`.
- `_cover_letter` refactored: prompt building extracted to `_cover_letter_prompt(job, answers,
  cv_name, name, links)` (pure, testable). System prompt signs with the real name when present
  (else keeps `[Your Name]`) and instructs listing the links at the bottom under a "Links:"
  heading; name + links are injected into the user message. No name/links → prior behavior.
- Tests: `_cover_letter_prompt` includes name/links and drops placeholder when name present (14
  pass). Ruff clean for new code (baseline 3 E501 nits remain in main.py, pre-existing).
- No schema change; no frontend change.

## 2026-08-13 — CLAUDE.md schema discipline + schema.md

- CLAUDE.md Working Agreement: added "Schema changes: always update `schema.md`" and "Read
  `schema.md` to understand the data model" rules.
- Created `schema.md` (repo root) documenting the current tables, relationships, tenant-scoping
  claims, RLS status, and a changelog; recorded the `service_users.links` changes.

## 2026-08-13 — Links on service_users + settings section

- Migration `20260813200000_service_users_links.sql` (PUSHED ✓ via `supabase db push`):
  `service_users.links text[] not null default '{}'`, same row the JWT's
  `app_metadata.service_user_id` claim points at. Remote `migration list` confirms all 6 versions
  applied. (Note: run the CLI from repo root — from `supabase/` it resolves the wrong project root.)
- `store.py`: `set_service_user_links(user_id, links)`; `get_service_user` already selects `*`.
- `user_settings.py`: `get_links` / `set_links` scoped to `current_service_user_id` (contextvar set
  by `auth.require_service_user` from the JWT claim — no per-request DB id lookup).
- `main.py`: `GET /api/links` + `PUT /api/links` with `_clamp_links` (trim, drop blanks, cap 2048
  chars / 50 links).
- `apps/dashboard/lib/api.ts`: `getLinks` / `setLinks`.
- `/settings`: "Links" card (same add/remove-row UX as generate-page optional questions) + Save
  links button with saved/error state; loaded alongside CVs/brag/LLM settings.
- Checks: `poetry run pytest` 12 ✓ (new `_clamp_links` test), `ruff` (5 pre-existing E501 nits,
  none new), `npm run lint` ✓, `npm run build` ✓.

## 2026-08-13 — Generate page: improved UX layout

- Reordered `/generate`: Job description → **sticky "Generate" panel** (two side-by-side buttons,
  cover-letter format toggle, error line, green "Ready — review and download" block) → Optional
  questions → Cover letter preview card (full text shown outside the sticky panel so it never
  overflows the viewport).
- Generate panel is `lg:sticky lg:top-4` so the actions + downloads stay visible while filling in a
  long Q&A list. Format toggle moved into the panel (it only affects the cover letter). Letter
  preview moved to its own card below the form instead of living in the download block.
- No logic changes — pure JSX rearrangement. Checks: `npm run lint` ✓, `npm run build` ✓.

## 2026-08-13 — Generate page: split into two async buttons (resume / cover letter)

- `apps/api/main.py`: `GenerateRequest.parts` (`["resume", "cover_letter"]`, defaults to both for
  backward compat); `GenerateResult.resume`/`cover_letter` now nullable; `/api/generate` branches —
  resume-only skips the Groq 18KB master-CV guard (that limit only applies to fine-tuning).
- `apps/dashboard/lib/api.ts`: `GenerateRequest.parts`, `GenerateResult.resume`/`coverLetter` now
  `GeneratedFile | null`, `generateApplication` forwards `parts`.
- `apps/dashboard/app/generate/page.tsx`: two buttons — **Generate resume** and **Generate cover
  letter** — each fires its own request with independent busy/result state, so both can run in
  parallel and complete independently; results panel shows only what has been generated.
- Checks: `npm run lint` ✓, `npm run build` ✓, `poetry run pytest` 11 ✓.

## 2026-08-13 — Scoped generator module data per service user

- Migration `20260813150000_scope_module_tables_by_service_user.sql` (pushed): `module_master_cvs` +
  `module_brag_docs` get `service_user_id bigint not null references service_users(id) on delete cascade`
  + index. Tables were empty at migration time (verified remote), so no backfill needed.
- `store.py`: `upload_cv`/`list_cvs`/`get_cv`/`delete_cv`/`set_cv_preferred`/`get_brag`/`upload_brag`/
  `delete_brag`/`set_brag_summary` now take/scope by `service_user_id`; `main.py` passes `_sv["id"]`
  from the JWT-resolved claim.
- Smoke-tested via service role: user 19 round-trips upload→list→delete; an unrelated id (99) sees
  no rows. `pytest` 11 ✓, `ruff` ✓.
- Known follow-ups: buckets still shared (no per-user storage folders yet, fine while service-role);
  no RLS policies on these tables (app only talks service-role today).

## 2026-08-13 — Moved settings storage off disk into Supabase (multi-user rule)

- Migration `20260813120000_user_settings_in_db.sql` (pushed): `service_users.openrouter_api_key text not null default ''`
  + `module_brag_docs.summary text`. Deleted local `data/user_settings.json` and `data/brag_summary.json`.
- `user_settings.py` rewritten: `current_service_user_id` ContextVar (set per-request by
  `auth.require_service_user`, which reads the `app_metadata.service_user_id` claim from the JWT);
  `get/set_openrouter_key` read/write the service_users row, env var stays a deploy-time default.
- `auth.require_service_user` is now async (blocking auth/DB calls via `run_in_threadpool`) and sets
  the contextvar, so provider resolution deep in the generation pipeline stays per-user.
  Follow-up: dropped the per-request `service_users` row fetch — the id comes straight from the
  validated JWT's `app_metadata.service_user_id` claim; `get_service_user` remains only for the
  OpenRouter-key read in `user_settings.py`.
- `store.py`: `set_service_user_openrouter_key`, `set_brag_summary`; `main.py` brag-summary cache now
  lives on the doc's row instead of a local JSON file.
- Tests: `test_llm.py` rewritten to fake the store + contextvar instead of the JSON file; `pytest` 11 ✓,
  `ruff` ✓ (5 pre-existing E501 line-length nits remain, untouched).
- Known follow-up (not done): `module_master_cvs`/`module_brag_docs` are still single-user (no user
  column, no RLS); compiled PDFs still go to `apps/api/data/out/` (ephemeral output, not state).

## 2026-08-13 — Cleanup: removed unused code

- Deleted Radar/ingestion scaffolding that nothing imports: `apps/api/adapters/` (`remoteok.py`,
  `__init__.py`) + `apps/api/models.py` (`SearchConfig`/`RawJob`/`Job`/`SourceAdapter`).
  Re-creatable from the Day-1 agenda when Radar resumes.
- Deleted mock-phase leftovers superseded by the real backend: `apps/dashboard/lib/pdf.ts`
  (`makePdf`) + `scripts/selfcheck.mjs` + the `check:mock` npm script.
- Removed unused `isExpired` export in `apps/dashboard/lib/session.ts`.
- Deleted stray 12-byte `50` file at repo root.
- Checks: `poetry run pytest` 11 ✓, `npm run lint` ✓, `npm run build` ✓.

## 2026-08-10 — Fix: signup "This page couldn't load" (infinite re-render loop)

- Symptom: registering works on the backend (auth user created + onboarded,
  tokens returned) but the frontend crashes with "This page couldn't load".
- Root cause: `apps/dashboard/lib/session.ts` `getSession()` built a brand-new
  object on every call. `lib/use-session.ts` feeds it to
  `useSyncExternalStore`, whose getSnapshot result must be referentially stable
  between renders. A fresh object each render → "The result of getSnapshot
  should be cached to avoid an infinite loop" → "Maximum update depth exceeded"
  → Next.js error page. Triggers the moment a session exists, i.e. right after
  signup/login.
- Fix: module-level cache in `session.ts` (`cachedSession` + `cachedRaw`);
  `getSession()` returns the same reference until localStorage raw values
  change. set/clear already dispatch `groundwork:session-changed` to re-render.
- Verified: CDP browser repro (headless Chrome) — before: signup 200 +
  exception + error page; after: signup 200 → `/generate` renders with session,
  no exceptions. `npm run lint` ✓, `npm run build` ✓, `poetry run pytest` 11 ✓.
  Test users cleaned up (service_users + auth.users).

## 2026-08-09 — Login feature (server-side auth, no supabase-js)

- Migration `20260809150000_service_users.sql` pushed (service_users: `id bigint generated
  always as identity primary key`, `api_key text not null unique`, `created_at`; RLS enabled;
  linked from `auth.users.raw_app_meta_data->>'service_user_id'` set at onboarding via
  `auth.admin.update_user_by_id`).
- `apps/api/auth.py`: `signup`/`login`/`refresh`/`logout`, idempotent `_onboard`,
  `require_service_user` (validates Supabase JWT via `auth.get_user`, resolves service_user,
  used as FastAPI dependency on every `/api/*` route), `_clean_auth_error`.
- `apps/api/main.py`: `POST /api/auth/{signup,login,refresh,logout}`; all existing endpoints
  now require `Authorization: Bearer <jwt>`.
- `apps/dashboard`: `app/login` + `app/signup` pages, `components/auth-guard.tsx`,
  `components/header-nav.tsx` (sign in/out), `lib/session.ts` (localStorage
  `gw_access_token`/`gw_refresh_token`/`gw_expires_at`), `lib/use-session.ts`
  (`useSyncExternalStore`), `lib/api.ts` token attach + refresh + `groundwork:unauthorized`
  event. Removed `@supabase/supabase-js` + `@supabase/ssr`.
- Bug fixed during E2E: `sign_in_with_password`/`refresh_session`/`sign_out` on the shared
  `store.client()` singleton replace its JWT with a user token, breaking subsequent
  `admin.create_user` ("User not allowed"). All user-auth calls now use a throwaway
  `create_client` so the admin client keeps the service-role JWT.
- Checks: `poetry run pytest` 11 pass (auth tests updated to mock `auth.create_client`),
  `ruff check auth.py tests/test_auth.py` ✓, `npm run lint` ✓, `npm run build` ✓,
  live E2E (signup → settings 200 → bad token 401 → login → refresh → logout) ✓.
  Test users cleaned up (service_users + auth.users).

## 2026-08-09 — OpenRouter BYOK support (Groq stays as free fallback)

- `apps/api/config.py`: added `openrouter_api_key` (env default) + `openrouter_model`
  (default `meta-llama/llama-3.3-70b-instruct`).
- `apps/api/user_settings.py`: key saved from the Settings UI persisted to
  `data/user_settings.json` (gitignored); UI-saved key wins over env var.
- `apps/api/llm.py`: `_endpoint()` resolves provider precedence — Ollama
  (`LLM_PROVIDER=ollama`) → OpenRouter (key present) → Groq (free fallback). Added
  `active_provider()`; clearer error when no key at all.
- `apps/api/main.py`: `GET /api/settings` + `PUT /api/settings` (save/clear key). Groq-only
  TPM budget (`_fit_max_tokens`) and 18KB master-CV guard now gated on `active_provider() == "groq"`
  — BYOK users get no free-tier ceilings.
- `apps/dashboard`: settings page "AI provider" section (password field, Save key, saved
  confirmation, active-provider readout with "for more accurate results, bring your own key"
  copy); `lib/api.ts` `getLlmSettings` / `setOpenRouterKey`.
- `apps/api/.env.example`: documented `OPENROUTER_API_KEY` / `OPENROUTER_MODEL`.
- Checks: `poetry run pytest` 8 pass (2 new: provider resolution incl. fallback), TestClient
  round-trip on `/api/settings`, `npm run lint` ✓, `npm run build` ✓.


## 2026-08-09 — Day-1 cover-letter + resume generator module (frontend)

> Deviation: parked the Day-1 Radar/ingestion agenda above and built the user-requested standalone
> **Cover Letter + Resume Generator** module instead. Radar work resumes whenever requested.

- Scaffolded `apps/dashboard` (Next.js 16 App Router, React 19, Tailwind v4, npm, TS). Uber color
  scheme theme in `app/globals.css` (black `#000000`, Uber green `#06c167`, gray `#f5f5f5` bg).
- App shell: black header nav (Generate / Settings), root `/` redirects to `/generate`.
- `/generate` — job-description textarea, infinite optional Q&A rows (add/remove), cover-letter
  format toggle (PDF / plain text), Generate button, results panel with download buttons + inline
  text view when in text mode, plus "master CV matched" note.
- `/settings` — master CV manager (upload `.tex`, list with size/date, mark Preferred, remove) and
  brag document (upload `.md`, view, remove). Persisted to localStorage (metadata only).
- `lib/api.ts` — the backend contract (types + `listMasterCVs/addMasterCV/removeMasterCV/
  setPreferredMasterCV/getBragDoc/setBragDoc/clearBragDoc/generateApplication`); all mock now.
- `lib/pdf.ts` — minimal valid single-page PDF builder so mock downloads actually open.
- `scripts/selfcheck.mjs` + `npm run check:mock` — verifies the PDF xref offsets match byte positions.
- Verified: `npm run lint` ✓, `npm run build` ✓, `npm run check:mock` ✓, smoke test of `/generate`
  and `/settings` (200) ✓.
- Backend next session: tectonic install, Groq key, FastAPI endpoints (auto-pick master CV from JD,
  fine-tune chosen .tex with brag doc, compile to PDF, real upload storage), then swap mock bodies
  in `lib/api.ts` for fetch calls.

## 2026-08-09 — Day-1 generator module (backend) — DONE

- Supabase: migration `20260809120000_generator_module.sql` pushed (buckets `master-cvs`, `brag-docs`
  + tables `module_master_cvs`, `module_brag_docs`, service-role only / no RLS / single-user ponytail).
  Existing `init_schema` confirmed applied locally + remotely.
- tectonic 0.17.0 → `apps/api/bin/tectonic.exe` (gitignored). First compile pre-warmed package cache.
- `apps/api`: `config.py` (pydantic-settings reads `.env`), `llm.py` (OpenAI-compatible chat;
  Groq default via `LLM_PROVIDER`, Ollama switch available), `store.py` (supabase-py service-role
  storage + metadata CRUD), `compile.py` (tectonic compile, log-tail errors), `main.py` (CORS :3000,
  CV/brag CRUD, `POST /api/generate`: auto-pick CV → LLM fine-tune .tex → cover letter → tectonic
  compile; `/out` static for generated PDFs). Added `python-multipart`; `package-mode = false`.
- `apps/dashboard`: `lib/api.ts` mock bodies swapped to `fetch :8000/api` (snake→camel mapping);
  `NEXT_PUBLIC_API_URL` in `.env.local`; settings page now async with upload/delete/preferred wired
  to the API (size display dropped — server doesn't store it); download buttons fetch URL → blob.
- Checks: `poetry run pytest` (2 pass: tectonic compile minimal + unicode/specials), server boots
  with all 5 endpoints, `npm run lint` + `npm run build` ✓.
- E2E verified (real Groq + Supabase): uploaded `.tex` + `.md`, generated text + PDF cover letters,
  both resumes PDF-valid (`%PDF-`), fine-tuned resume confirmed grounded in brag doc (60% on-call
  drop, p99 45ms — no fabrication). Test data cleaned up.
- Run locally: `poetry run uvicorn main:app --port 8000` (apps/api) + `npm run dev` (apps/dashboard).

## 2026-08-09 — tectonic XeTeX compile failure (pdfTeX-only primitives)

Symptom: generate → 500 `RuntimeError: tectonic failed for custom-resume-*`. Root cause: the
master CV template (Jake's-Resume fork) `\input`s `glyphtounicode.tex`, which uses
`\pdfglyphtounicode{..}{..}` and `\pdfgentounicode=1` — **pdfTeX-only primitives** that tectonic's
XeTeX engine doesn't define. The real error was hidden because `compile_tex` only surfaced stdout.

Fixes (all in `apps/api`):
- `compile.py`: `XETEX_SHIM` injected at the top of every compile — defines `\pdfglyphtounicode`
  as a 2-arg no-op and `\pdfgentounicode` as a count register (guarded by `\ifdefined`), so
  pdfLaTeX-targeted templates compile unchanged. Narrow on purpose: add primitives only as real
  failures appear. Failure tail now includes stderr too.
- `main.py`: `_compile()` wraps `compile_tex` and turns failures into a readable **502** with the
  log tail instead of a 500 traceback (used for both resume and cover letter).
- Tests: `tests/test_compile.py::test_compile_pdftex_template_shim` — `\input glyphtounicode`
  compiles under the shim. 6/6 passing.
- Verified: the exact failing file (`custom-resume-12496849.tex`) now compiles to a valid 32KB PDF.

Symptom: generate failed with `413 Payload Too Large` in `_fine_tune`. Root cause: Groq free tier
caps `llama-3.3-70b-versatile` at **12,000 TPM** (rolling/minute, counts input + `max_tokens`); the
user's real 62KB brag doc stuffed verbatim into the fine-tune prompt made one request request
~13.2K tokens.

Fixes (all in `apps/api`):
- `llm.py`: `chat()` retries 429/413 (recoverable rate-limit) with a 45s backoff, bounded (3 attempts).
- `main.py`: `_fit_max_tokens()` sizes output so each request stays under the ~11K budget, else a
  clear 400; brag doc is **summarized to ~4KB first** and cached in `data/brag_summary.json` keyed by
  storage path (skip re-summarizing on repeat generates); JD clamped to 6K chars; master CV guarded
  at 18KB with a message pointing at `LLM_PROVIDER=ollama` for no limits.
- Tests: `tests/test_main.py` (clamp + answer caps), all 5 pass.

Verified with the user's real data (62KB brag + Ai-focused.tex): generate → 200 OK in ~11.6s,
auto-picked the right CV, resume PDF valid (`%PDF-`, 41KB), cover letter grounded, summary cached.
