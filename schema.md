# Groundwork — Schema

Source of truth for the data model. **Every schema change (new/renamed/dropped table or column,
constraint, index, relationship) must be recorded here in the same task.** Migrations live in
`supabase/migrations/` (push with the supabase CLI from the repo root).

## Tenant scoping

Two separate tenant chains, both resolved from JWT `app_metadata` custom claims set at onboarding —
no per-request DB id lookups:

| Claim | Table chain | Notes |
|---|---|---|
| `app_metadata.profile_id` | `profiles` ← `applications` | RLS-scoped (select/insert/update/delete own) |
| `app_metadata.service_user_id` | `service_users` ← `module_master_cvs`, `module_brag_docs` | Service-role only; no RLS policies |

`jobs` is NOT user-scoped (shared ingested pool, readable by any authenticated user).

## Relationships

```
profiles (id) 1───* applications (profile_id)
jobs (id)     1───* applications (job_id)      -- unique(profile_id, job_id)

service_users (id) 1───* module_master_cvs (service_user_id)
service_users (id) 1───* module_brag_docs (service_user_id)
```

## Tables

### service_users
One row per authenticated app user. Linked from `auth.users` via
`auth.users.raw_app_meta_data->>'service_user_id'` (soft JSON linkage — no real FK).
`api_key` is server-only (future programmatic/MCP access); the web app authenticates with the
Supabase JWT.

| Column | Type | Notes |
|---|---|---|
| `id` | bigint identity PK | |
| `api_key` | text not null unique | |
| `openrouter_api_key` | text not null default '' | BYOK key, stored server-side |
| `gemini_api_key` | text not null default '' | Google AI Studio (free) key, stored server-side; wins over OpenRouter when set |
| `links` | text[] | nullable, no default (null and `[]` both mean "none") |
| `created_at` | timestamptz not null default now() | |

RLS enabled, no policies (app talks service-role).

### profiles
Extends `auth.users`; linked via `app_metadata.profile_id` claim.
`resume_text`, `structured_profile jsonb`, `embedding vector(384)`, `github_url`, `linkedin_url`,
`portfolio_url`, `work_authorization jsonb`, `created_at`, `updated_at`.
RLS: select/insert/update own via the `profile_id` claim.

### jobs
Ingested postings, shared across users. `source`, `external_id`, `company`, `title`, `location`,
`remote_type`, `description`, `apply_url`, `posted_at`, `first_seen_at`, `seen_on text[]`,
`content_hash` (unique index — dedupe), `embedding vector(384)`, `created_at`.
RLS: select for authenticated; writes service-role only.

### applications
User-scoped via `profile_id`. `status` (drafted|applied|interviewing|rejected|offer), `applied_at`,
`follow_up_due_at`, `notes`. `unique(profile_id, job_id)`; index on `job_id`.
RLS: full CRUD own via the `profile_id` claim.

### module_master_cvs
`file_name`, `storage_path` (in `master-cvs` bucket), `preferred boolean`, `service_user_id`,
`created_at`. Index on `service_user_id`.

### module_brag_docs
`file_name`, `storage_path` (in `brag-docs` bucket), `service_user_id`, `summary text` (LLM
brag-summary cache — **unused since 2026-08-15**, the full brag doc is sent to the model
instead; column kept, not dropped), `created_at`. Index on `service_user_id`.

## Planned (roadmap tables, not yet created)
`resume_evidence, job_requirements, company_briefs, matches, generations, outcomes, eval_runs,
traces, autofill_sessions, interview_preps, mock_sessions, analytics_snapshots, resume_versions`
(see CLAUDE.md Data Model for columns).

## Changelog

- **2026-08-16** — `service_users.gemini_api_key text not null default ''` added
  (migration `20260816000000`). Free Google AI Studio key; provider precedence when set:
  Gemini → OpenRouter → Groq.
- **2026-08-15** — `module_brag_docs.summary` no longer written/read (full brag doc sent to the
  model instead); column retained for now, marked unused.
- **2026-08-13** — `service_users.links text[]` added (migration `20260813200000`), then made
  nullable with no default (`20260813210000`).
- **2026-08-13** — `module_master_cvs.service_user_id`, `module_brag_docs.service_user_id` added +
  indexes (`20260813150000`); tables were empty at migration time.
- **2026-08-13** — `service_users.openrouter_api_key`, `module_brag_docs.summary` added
  (`20260813120000`).
