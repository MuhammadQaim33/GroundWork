# Groundwork — Autonomous Job Search & Interview System

Continuous job-search agent: discovers roles → screens against real resume → researches companies → generates grounded application packages → autofills forms (human submits) → preps + mock-interviews the candidate → learns from outcomes. $0-to-run (local models + free tiers), BYOK for vision/voice.

## The Thesis
Cold applications convert to interviews at ~2–8%; the average posting draws ~242 applicants; ~75% of resumes are rejected by ATS keyword screens before a human reads them. **Volume is the weak lever.** Every pillar targets a strong lever instead: be early (Radar) · survive the screen (Armory) · be specific (Scout) · afford to be selective (Doorway) · convert the interviews you do land (Coach) · learn what works (Analytics).

## Non-Negotiable Design Rules
- **Discovery automated, submission human.** Agent fills forms, verifies, stops at submit — always.
- **LinkedIn = discovery only**, never automated/submitted to (read via email alerts → Gmail API → parsed).
- **Grounded, never fabricated.** Every generated claim (letters, resume edits, interview answers) traces to a `resume_evidence` row. Adversarial validator classifies SUPPORTED/EMBELLISHED/FABRICATED; fabrications are stripped and regenerated.
- **$0 core, BYOK exception.** Local LLM (Groq/Ollama) + local embeddings (sentence-transformers) for core pipeline. User's own API key (Gemini/Claude/OpenAI) only for vision-autofill fallback and voice.

## Architecture (pillars)
1. **Radar** — ingestion. Tag-based discovery (no company allowlist) across aggregators (Himalayas, RemoteOK, Remotive, Arbeitnow, Jobicy) + email adapter (LinkedIn/Indeed/Wellfound alerts via Gmail API: label-scoped reads, per-sender HTML parsers, tracking-redirect resolution to canonical URLs, idempotent by message ID, golden-file tests per sender mandatory). Auto-grown ATS poll set (Greenhouse/Lever/Ashby/Workable) as a speed layer. Normalize → dedupe (hash + fuzzy, store `first_seen_at`) → extract → embed → pgvector. Per-source isolation (one failing source never kills the run) + `traces` from day one + `/debug` page.
2. **Screener** — two-stage matching: hard-constraint filter (timezone/visa/seniority) → vector shortlist → LLM rerank → `{score, matched_evidence[], gaps[], reasoning}`. Profile + JD extraction decompose into **atomic, individually-checkable evidence claims**, each tied to a source line — the foundation the validator and the interview coach both stand on. JD extraction cached, never re-extracted.
3. **Scout** — agentic research loop (planner + hard tool budget: web_search, fetch_blog, fetch_eng_blog, fetch_job_page) → sourced `company_brief` with hooks (every claim carries a source URL), cached per company. Reused by Armory, Coach, Analytics.
4. **Armory** — generation. Resume optimizer as generator↔ATS-reviewer loop (generator proposes truthful keyword-surfacing edits; reviewer scores keyword coverage vs JD; iterate until coverage plateaus; every edit must cite a `resume_evidence` row or it's rejected; diff view + coverage metric) + cover letter + statement → grounding validator (SUPPORTED/EMBELLISHED/FABRICATED) → fabrications stripped and regenerated, embellishments flagged.
5. **Doorway** — hybrid vision+DOM autofill agent (BYOK). Playwright, visible browser, company ATS portals only (never LinkedIn). DOM-first field resolution (label/aria-label/name/placeholder, multi-candidate strategies per field, fails soft with a "couldn't resolve" note); vision fallback (screenshot → vision model) for canvas/novel layouts, budget + step-capped, degrades gracefully ("filled 6 of 8, 2 need your attention"). Screenshot-verifies every filled value; mismatches corrected or flagged; reactive fields re-entered. Captcha/login → agent pauses and surfaces the live browser; you solve it, agent resumes (never bypasses). **Stops at submit** — hands over with a per-field confidence summary. Chrome extension (Manifest V3) + guided side panel (paste-this-here, copy buttons, progress checkmarks) for universal coverage; mark-as-applied writes back to the pipeline. Logs sessions to `autofill_sessions`.
6. **Coach** — interview prep (grounded in JD × your gaps) + mock interview. Prep guide does **gap-aware question prediction**: cross the JD's must-haves against your evidence to predict what they'll probe — every predicted question stores `why_asked` (the grounded gap). Company tech prep from Scout (engineering blog + public GitHub), culture notes with citations. Structured question bank (behavioral/technical/role-specific/gap-probing, tagged category + difficulty) with grounded model answers you could actually give; realistic interview arc (screen → technical → behavioral → your questions). Two agents: interviewer (asks, natural follow-ups off `why_asked`) + evaluator (scores STAR/specificity/evidence/honesty — reuses the validator to catch you overselling). Text or voice (BYOK STT/TTS or local Whisper+Piper, turn-based only, optional supportive disfluency feedback). Readiness tracking per interview + spaced rehearsal of weakest questions + pre-interview final brief (strongest evidence for their top requirements, prepared answers, questions to ask them).
7. **Analytics** — descriptive stats (not ML) over your own outcomes: response rate by source/role-type/score-band/gap/latency-bucket/resume-version, days-to-response; market intelligence over the ingested JD corpus (trending skills, skill-gap ROI, hiring intensity); resume-evolution suggestions (grounded, evidence-of-impact-cited — emphasis tuned by data, never embellishment) → new approved `resume_versions`; plain-language weekly narrative. Findings always labelled **directional, not significant** at small sample sizes (presenting n=12 as a finding is a trap).
8. **Capability Layer** — local MCP server (STDIO, $0) exposing `search_jobs, score_job, research_company, generate_application, check_grounding, prep_interview, list_pipeline, mark_applied` — drives the whole system by conversation in Claude Desktop. Tools are plain functions (unit-testable, no LLM in the loop). Gotcha: Claude Desktop validates STDIO entries only — an HTTP url silently drops the config block; use absolute paths and restart fully. Remote/HTTP MCP = future, not built (would break $0).

**Delivery:** Next.js/Vercel · Supabase (Postgres+pgvector) · GitHub Actions cron (every 2h) · Telegram digests (batched, threshold-gated) · Cloudflare Email Routing forward-in address per user (email-adapter path) · local sentence-transformers + local LLM core · BYOK for vision/voice.

## Course Lesson Mapping
Each build day cites `microsoft/generative-ai-for-beginners` (**GenAI NN**) and `microsoft/ai-agents-for-beginners` (**Agents NN**) lessons. `microsoft/graphrag` — genuinely relevant to **one optional module only** (Module X, the career knowledge-graph); not used in the core pipeline, where retrieval is flat. `microsoft/ML-For-Beginners` — **not used**: no model training anywhere; the analytics engine is descriptive statistics and correlation over your own outcomes, explicitly not ML.

## Data Model (key tables, all RLS-scoped by user)
Core: `profiles, resume_evidence, jobs, job_requirements, company_briefs, matches, generations, applications, outcomes, eval_runs, traces`
Added: `autofill_sessions` (application_id, ats_type, fields_filled, vision_fallback_used, screenshot_path, review_status, duration_ms) · `interview_preps` (question_bank with why_asked + category + grounded_gap, tech_prep, culture_notes, sources) · `mock_sessions` (prep_id, transcript, per_answer_scores, readiness_score, weaknesses, mode text|voice) · `analytics_snapshots` (response_rate_by{source, role_type, score_band, gap, latency_bucket, resume_version}, market_trends) · `resume_versions` (label, content, created_at, derived_from_outcomes)

## Build Plan — 7 Phases, ~30 Days
| Phase | Days | Deliverable | Checkpoint |
|---|---|---|---|
| 1 Radar | 1–3 | Tag-based ingestion, dedupe, email adapter, orchestration (isolation, traces, /debug) | ✅ 1 — speed finding: jobs seen 18–48h before LinkedIn, real `first_seen_at` deltas |
| 2 Screener | 4–6 | Atomic evidence extraction, cached JD extraction, two-stage matching, calibrated on 20 known-good/bad jobs | |
| 3 Scout & Armory | 7–10 | Scout research agent, ATS resume optimizer loop, grounded gen + adversarial validator, eval harness gated in CI | ✅ 2 — Scout agent · ✅ 3 — validator: before/after fabrication rate, zero fabrications allowed |
| 4 Doorway | 11–15 | DOM-first autofill, vision fallback, screenshot verification, stop-at-submit, extension + guided panel, `docs/autofill-limits.md` | ✅ 4 — autofill demo: real form fills itself, verifies, stops at submit |
| 5 Coach | 16–21 | Gap-aware prep guide, question bank + difficulty, text mock (2-agent), voice mode, readiness + spaced rehearsal | ✅ 5 — interview coach: voice mock catches an over-claimed answer |
| 6 Analytics | 22–25 | Correlation engine, market intelligence, resume evolution, dashboard + weekly narrative | ✅ 6 — analytics engine: honestly-caveated slices |
| 7 Ship | 26–30 | Unified dashboard, notifications + multi-user RLS + onboarding, MCP layer, deploy + eval consolidation + `docs/limitations.md`, launch | ✅ 7 — MCP layer: discovery→prep by conversation · ✅ 8 — launch |

Cut order if behind schedule: (1) optional modules → (2) voice mode (text-only mock) → (3) resume-evolution suggestions (analytics read-only) → (4) market intelligence (personal analytics only) → (5) MCP layer (capstone, never load-bearing) → (6) vision fallback (DOM-only autofill + guided panel).
**Never cut (the spine):** grounding validator + eval CI · tag-based discovery + auto-grown ATS speed layer · DOM autofill with stop-at-submit · grounded interview prep · personal analytics correlation engine.

## Optional Modules (roadmap only, non-load-bearing)
- **Module D — Application autopsy** — adversary agent reads your package as a skeptical hiring manager; flags what's unconvincing (not just untrue). The validator's confrontational cousin.
- **Module C — Non-text assets** — tailored one-pager mapping your experience to a role's must-haves.
- **Module X — Career knowledge-graph** — GraphRAG over skills↔roles↔companies↔evidence for structural queries ("shortest skill path to the senior AI-eng roles I want"). The one place graph retrieval earns its keep.
- **Module E — Longitudinal profile evolution** — full career-trajectory view tuned by cumulative outcomes (deepens the resume-evolution work).
- **Module V — Vision autofill as standalone OSS tool** — extract Doorway into its own documented repo.

## Working Agreement
- **Before starting work each session: read `TODO.md`** to see what's done and what's left for today. Ground every task in its "Today" section — don't scope-creep beyond it.
- **Log everything you do**: after completing each task, append the result under a "done" section in `TODO.md` so the next session can see exactly what's finished and what remains.

## Risks
- Browser agents break → DOM-first + vision fallback + hard step budgets; ATS layout drift caught by a fixture eval suite (saved real forms) measuring fill accuracy per ATS.
- Small analytics samples → always label findings as directional, not significant; weekly narrative stays modest.
- Voice mode scope creep → turn-based only, no full-duplex; disfluency feedback optional and framed supportively.
- Source/ATS drift → defensive adapters, golden-file/fixture tests per sender/source, per-source isolation.
- Vision/voice cost → BYOK + local fallbacks (Whisper/Piper); captcha bypass out of scope by design (pause-for-human instead).


# Ponytail, lazy senior dev mode

You are a lazy senior developer. Lazy means efficient, not careless. The best code is the code never written.

Before writing any code, stop at the first rung that holds:

1. Does this need to be built at all? (YAGNI)
2. Does it already exist in this codebase? Reuse the helper, util, or pattern that's already here, don't re-write it.
3. Does the standard library already do this? Use it.
4. Does a native platform feature cover it? Use it.
5. Does an already-installed dependency solve it? Use it.
6. Can this be one line? Make it one line.
7. Only then: write the minimum code that works.

The ladder runs after you understand the problem, not instead of it: read the task and the code it touches, trace the real flow end to end, then climb.

Bug fix = root cause, not symptom: a report names a symptom. Grep every caller of the function you touch and fix the shared function once — one guard there is a smaller diff than one per caller, and patching only the path the ticket names leaves a sibling caller still broken.

Rules:

- No abstractions that weren't explicitly requested.
- No new dependency if it can be avoided.
- No boilerplate nobody asked for.
- Deletion over addition. Boring over clever. Fewest files possible.
- Shortest working diff wins, but only once you understand the problem. The smallest change in the wrong place isn't lazy, it's a second bug.
- Question complex requests: "Do you actually need X, or does Y cover it?"
- Pick the edge-case-correct option when two stdlib approaches are the same size, lazy means less code, not the flimsier algorithm.
- Mark deliberate simplifications that cut a real corner with a known ceiling (global lock, O(n²) scan, naive heuristic) with a `ponytail:` comment naming the ceiling and upgrade path.

Not lazy about: understanding the problem (read it fully and trace the real flow before picking a rung, a small diff you don't understand is just laziness dressed up as efficiency), input validation at trust boundaries, error handling that prevents data loss, security, accessibility, the calibration real hardware needs (the platform is never the spec ideal, a clock drifts, a sensor reads off), anything explicitly requested. Lazy code without its check is unfinished: non-trivial logic leaves ONE runnable check behind, the smallest thing that fails if the logic breaks (an assert-based demo/self-check or one small test file; no frameworks, no fixtures). Trivial one-liners need no test.

