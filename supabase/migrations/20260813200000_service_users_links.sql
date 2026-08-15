-- Per-user arbitrary links (GitHub/LinkedIn/portfolio etc.), stored on the
-- service_users row the JWT's app_metadata.service_user_id custom claim
-- points at, same as openrouter_api_key.
alter table service_users
  add column if not exists links text[] not null default '{}';
