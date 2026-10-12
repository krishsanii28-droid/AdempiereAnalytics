-- Enables login for the service role and sets its password.
-- Run as a superuser:  psql -v ON_ERROR_STOP=1 -v ro_password=<secret> -f 02_login_role.sql
-- scripts\db_install.ps1 does this for you and stores the password in .env (never in git).

\set ON_ERROR_STOP on
ALTER ROLE insightai_ro LOGIN PASSWORD :'ro_password';
