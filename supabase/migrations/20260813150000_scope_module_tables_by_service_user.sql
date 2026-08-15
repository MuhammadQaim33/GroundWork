-- Scope the generator module's user data per service user (multi-user rule:
-- every user's rows carry their service_users.id, resolved from the JWT's
-- app_metadata.service_user_id claim at request time).
-- Tables were empty at migration time, so the FK column is safe as NOT NULL.
alter table module_master_cvs
  add column if not exists service_user_id bigint references service_users(id) on delete cascade;
alter table module_master_cvs
  alter column service_user_id set not null;

alter table module_brag_docs
  add column if not exists service_user_id bigint references service_users(id) on delete cascade;
alter table module_brag_docs
  alter column service_user_id set not null;

create index if not exists module_master_cvs_service_user_idx
  on module_master_cvs(service_user_id);
create index if not exists module_brag_docs_service_user_idx
  on module_brag_docs(service_user_id);
