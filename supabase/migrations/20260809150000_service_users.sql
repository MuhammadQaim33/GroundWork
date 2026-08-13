-- service_users: one row per authenticated app user, linked from auth.users
-- via auth.users.raw_app_meta_data->>'service_user_id' (set at onboarding via
-- auth.admin.update_user_by_id). JSONB app_metadata can't hold a real FK
-- constraint -- this is the same soft-JSON linkage `profiles` already uses.
-- api_key is server-only (reserved for future programmatic/MCP access); the
-- web app authenticates with the Supabase JWT instead.
create table if not exists service_users (
  id bigint generated always as identity primary key,
  api_key text not null unique,
  created_at timestamptz not null default now()
);

alter table service_users enable row level security;
