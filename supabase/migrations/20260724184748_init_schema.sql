-- Enable pgvector for embeddings
create extension if not exists vector;

-- profiles: one row per user, extends auth.users.
-- bigint surrogate PK keeps internal joins/indexes cheap. No auth.users FK
-- column here: the link is the app_metadata.profile_id JWT claim (set via
-- auth.admin.update_user_by_id at signup), not a stored column.
create table if not exists profiles (
  id bigint generated always as identity primary key,
  resume_text text,
  structured_profile jsonb,
  embedding vector(384), -- adjust dimension to match your embedding model
  github_url text,
  linkedin_url text,
  portfolio_url text,
  work_authorization jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- jobs: ingested postings, NOT user-scoped (shared across all users)
create table if not exists jobs (
  id bigint generated always as identity primary key,
  source text not null,
  external_id text,
  company text not null,
  title text not null,
  location text,
  remote_type text,
  description text,
  apply_url text,
  posted_at timestamptz,
  first_seen_at timestamptz not null default now(),
  seen_on text[] not null default '{}',
  content_hash text not null,
  embedding vector(384),
  created_at timestamptz not null default now()
);

create unique index if not exists jobs_content_hash_idx on jobs(content_hash);
create index if not exists jobs_company_title_location_idx on jobs(company, title, location);

-- applications: user-scoped via profiles.id, references jobs
create table if not exists applications (
  id bigint generated always as identity primary key,
  profile_id bigint not null references profiles(id) on delete cascade,
  job_id bigint not null references jobs(id) on delete cascade,
  status text not null default 'drafted', -- drafted | applied | interviewing | rejected | offer
  applied_at timestamptz,
  follow_up_due_at timestamptz,
  notes text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(profile_id, job_id)
);

-- unique(profile_id, job_id) already indexes the profile_id FK (leading column);
-- the job_id FK needs its own index for cascade deletes and by-job lookups.
create index if not exists applications_job_id_idx on applications(job_id);

-- Row Level Security
alter table profiles enable row level security;
alter table applications enable row level security;
-- jobs is intentionally NOT user-scoped: everyone reads the same ingested pool
alter table jobs enable row level security;

-- profiles: scoped by the same app_metadata.profile_id JWT claim as applications.
-- Note: this makes the insert policy practically unreachable from a client
-- session -- the claim can't exist until the row (and its id) exists, so profile
-- creation happens via the service-role key at signup, before the claim is set.
create policy "profiles_select_own" on profiles
  for select using ((auth.jwt()->'app_metadata'->>'profile_id')::bigint = id);
create policy "profiles_insert_own" on profiles
  for insert with check ((auth.jwt()->'app_metadata'->>'profile_id')::bigint = id);
create policy "profiles_update_own" on profiles
  for update using ((auth.jwt()->'app_metadata'->>'profile_id')::bigint = id);

-- jobs: readable by any authenticated user, writes reserved for the service role (the worker)
create policy "jobs_select_authenticated" on jobs
  for select using (auth.role() = 'authenticated');

-- applications: scoped by the app_metadata.profile_id JWT claim, set at signup.
-- If the claim is absent the comparison is NULL -> row is blocked, so signup MUST
-- create the profiles row and set the claim before the session touches this table.
create policy "applications_select_own" on applications
  for select using ((auth.jwt()->'app_metadata'->>'profile_id')::bigint = profile_id);
create policy "applications_insert_own" on applications
  for insert with check ((auth.jwt()->'app_metadata'->>'profile_id')::bigint = profile_id);
create policy "applications_update_own" on applications
  for update using ((auth.jwt()->'app_metadata'->>'profile_id')::bigint = profile_id);
create policy "applications_delete_own" on applications
  for delete using ((auth.jwt()->'app_metadata'->>'profile_id')::bigint = profile_id);
