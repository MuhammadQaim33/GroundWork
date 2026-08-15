-- Per-user OpenRouter key, stored on the service_users row the JWT's
-- app_metadata.service_user_id custom claim points at. Replaces the local
-- data/user_settings.json file (multi-user rule: nothing saved locally).
alter table service_users
  add column if not exists openrouter_api_key text not null default '';

-- Brag-doc LLM summary, cached on the doc's row instead of the local
-- data/brag_summary.json file. A re-upload inserts a fresh row, so the cache
-- invalidates naturally with the new storage_path.
alter table module_brag_docs
  add column if not exists summary text;
