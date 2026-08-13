-- Day-1 cover-letter + resume generator module.
-- ponytail: service-role only, no RLS — single-user standalone module. If this
-- ever goes multi-user, scope these tables + buckets by profile and add RLS.

create table if not exists module_master_cvs (
  id bigint generated always as identity primary key,
  file_name text not null,
  storage_path text not null,
  preferred boolean not null default false,
  created_at timestamptz not null default now()
);

create table if not exists module_brag_docs (
  id bigint generated always as identity primary key,
  file_name text not null,
  storage_path text not null,
  created_at timestamptz not null default now()
);

insert into storage.buckets (id, name, public)
values
  ('master-cvs', 'master-cvs', false),
  ('brag-docs', 'brag-docs', false)
on conflict (id) do nothing;
