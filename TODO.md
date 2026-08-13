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
