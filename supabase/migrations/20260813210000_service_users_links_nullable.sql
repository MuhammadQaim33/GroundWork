-- Links are optional; null and an empty array both mean "none". Revert the
-- not-null + default added by the prior push.
alter table service_users
  alter column links drop default,
  alter column links drop not null;
