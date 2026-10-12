-- Removes everything 01_install.sql and 02_login_role.sql created.
-- Run as a superuser:  psql -v ON_ERROR_STOP=1 -1 -f 99_uninstall.sql
-- ADempiere's own tables and data are not touched.

\set ON_ERROR_STOP on

DROP SCHEMA IF EXISTS insightai CASCADE;

-- Restore the PostgreSQL 14 defaults that 01_install.sql tightened.
GRANT CREATE ON SCHEMA public TO PUBLIC;
DO $$ BEGIN EXECUTE format('GRANT TEMPORARY ON DATABASE %I TO PUBLIC', current_database()); END $$;

DO $$
DECLARE
  r text;
BEGIN
  FOREACH r IN ARRAY ARRAY['insightai_ro', 'insightai_owner']
  LOOP
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = r) THEN
      EXECUTE format('DROP OWNED BY %I', r);   -- revokes the role's grants in this database
      EXECUTE format('DROP ROLE %I', r);
    END IF;
  END LOOP;
END $$;
