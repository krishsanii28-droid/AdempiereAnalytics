-- ADempiere InsightAI - Application Dictionary records
--
-- Adds, under a new entity type INSAI:
--   AD_EntityType      INSAI
--   AD_Form            InsightAI          -> org.insightai.adempiere.InsightAIForm (dashboard inside ADempiere)
--   AD_Process         InsightAI_Launch   -> org.insightai.adempiere.InsightAILauncher (dashboard in the browser)
--   AD_Form_Access and AD_Process_Access for the roles named in :roles only
--
-- There is no menu entry. The dashboard is opened from the Performance tab of ADempiere's main
-- window, where the InsightAI launcher adds an option for roles that hold the form. Menu entries
-- made by earlier versions of this script are removed, and the menu order they changed is restored.
--
-- No existing dictionary record is changed. IDs come from ADempiere's own sequences (AD_Sequence),
-- so they land in the customer range (1,000,000 and up). Everything is removed by dictionary_uninstall.sql.
--
-- Run as the adempiere role, in one transaction:
--   psql -v ON_ERROR_STOP=1 -1 -v roles="'GardenWorld Admin','SalesRep(Restricted)'" -f dictionary_install.sql
-- Safe to re-run: existing InsightAI records are left as they are, and :roles is applied again.

\set ON_ERROR_STOP on
SET search_path = adempiere;

-- Entity type
INSERT INTO ad_entitytype (entitytype, ad_client_id, ad_org_id, ad_entitytype_id, isactive, created, createdby, updated, updatedby,
                           name, description, help, processing, uuid)
SELECT 'INSAI', 0, 0, nextidfunc((SELECT ad_sequence_id FROM ad_sequence WHERE name = 'AD_EntityType' AND istableid = 'Y')::int, 'N'),
       'Y', now(), 100, now(), 100, 'InsightAI', 'ADempiere InsightAI analytics module',
       'Form and launcher process for the InsightAI dashboard. Removable with dictionary_uninstall.sql.', 'N', getuuid()
WHERE NOT EXISTS (SELECT 1 FROM ad_entitytype WHERE entitytype = 'INSAI');

-- Browser launcher process. Access level 3 = Client+Organization. Not a server process: it must run in
-- the desktop client so it can open the user's browser. ShowHelp S = run without a dialog first.
INSERT INTO ad_process (ad_process_id, ad_client_id, ad_org_id, isactive, created, createdby, updated, updatedby,
                        value, name, description, help, accesslevel, entitytype, isreport, isdirectprint, classname,
                        isbetafunctionality, isserverprocess, showhelp, copyfromprocess, generateclass, uuid)
SELECT nextidfunc((SELECT ad_sequence_id FROM ad_sequence WHERE name = 'AD_Process' AND istableid = 'Y')::int, 'N'),
       0, 0, 'Y', now(), 100, now(), 100,
       'InsightAI_Launch', 'InsightAI', 'Open the InsightAI analytics dashboard',
       'Opens the InsightAI dashboard in your browser for your current role. You see only the organisations your role can access.',
       '3', 'INSAI', 'N', 'N', 'org.insightai.adempiere.InsightAILauncher', 'N', 'N', 'S', 'N', 'N', getuuid()
WHERE NOT EXISTS (SELECT 1 FROM ad_process WHERE value = 'InsightAI_Launch');

INSERT INTO ad_process_trl (ad_process_id, ad_language, ad_client_id, ad_org_id, isactive, created, createdby, updated, updatedby,
                            name, description, help, istranslated, uuid)
SELECT p.ad_process_id, l.ad_language, 0, 0, 'Y', now(), 100, now(), 100, p.name, p.description, p.help, 'N', getuuid()
FROM ad_process p CROSS JOIN ad_language l
WHERE p.value = 'InsightAI_Launch' AND l.isactive = 'Y' AND l.issystemlanguage = 'Y' AND l.isbaselanguage = 'N'
  AND NOT EXISTS (SELECT 1 FROM ad_process_trl t WHERE t.ad_process_id = p.ad_process_id AND t.ad_language = l.ad_language);

-- The embedded window: an ADempiere form. Access level 3 = Client+Organization.
INSERT INTO ad_form (ad_form_id, ad_client_id, ad_org_id, isactive, created, createdby, updated, updatedby,
                     name, description, help, accesslevel, classname, entitytype, isbetafunctionality, uuid)
SELECT nextidfunc((SELECT ad_sequence_id FROM ad_sequence WHERE name = 'AD_Form' AND istableid = 'Y')::int, 'N'),
       0, 0, 'Y', now(), 100, now(), 100,
       'InsightAI', 'InsightAI analytics dashboard',
       'Shows the InsightAI dashboard inside ADempiere for your current role. You see only the organisations your role can access.',
       '3', 'org.insightai.adempiere.InsightAIForm', 'INSAI', 'N', getuuid()
WHERE NOT EXISTS (SELECT 1 FROM ad_form WHERE classname = 'org.insightai.adempiere.InsightAIForm');

INSERT INTO ad_form_trl (ad_form_id, ad_language, ad_client_id, ad_org_id, isactive, created, createdby, updated, updatedby,
                         name, description, help, istranslated, uuid)
SELECT f.ad_form_id, l.ad_language, 0, 0, 'Y', now(), 100, now(), 100, f.name, f.description, f.help, 'N', getuuid()
FROM ad_form f CROSS JOIN ad_language l
WHERE f.classname = 'org.insightai.adempiere.InsightAIForm' AND l.isactive = 'Y' AND l.issystemlanguage = 'Y' AND l.isbaselanguage = 'N'
  AND NOT EXISTS (SELECT 1 FROM ad_form_trl t WHERE t.ad_form_id = f.ad_form_id AND t.ad_language = l.ad_language);

-- Remove the menu entries earlier versions created. Where one sat at the top level of the menu,
-- the top-level entries after it had been moved down one place: move them back first.
UPDATE ad_treenodemm x SET seqno = x.seqno - 1, updated = now()
FROM ad_treenodemm n JOIN ad_menu m ON m.ad_menu_id = n.node_id AND m.entitytype = 'INSAI'
WHERE n.parent_id = 0 AND x.ad_tree_id = n.ad_tree_id AND x.parent_id = 0 AND x.seqno > n.seqno;
DELETE FROM ad_package_exp_detail WHERE ad_menu_id IN (SELECT ad_menu_id FROM ad_menu WHERE entitytype = 'INSAI');
DELETE FROM ad_recentitem         WHERE ad_menu_id IN (SELECT ad_menu_id FROM ad_menu WHERE entitytype = 'INSAI');
DELETE FROM ad_tree_favorite_node WHERE ad_menu_id IN (SELECT ad_menu_id FROM ad_menu WHERE entitytype = 'INSAI');
DELETE FROM ad_treebar            WHERE node_id IN (SELECT ad_menu_id FROM ad_menu WHERE entitytype = 'INSAI');
DELETE FROM ad_treenodemm         WHERE node_id IN (SELECT ad_menu_id FROM ad_menu WHERE entitytype = 'INSAI');
DELETE FROM ad_menu_trl           WHERE ad_menu_id IN (SELECT ad_menu_id FROM ad_menu WHERE entitytype = 'INSAI');
DELETE FROM ad_menu               WHERE entitytype = 'INSAI';

-- Access: exactly the roles in :roles. A role not listed loses access if it had it.
DELETE FROM ad_form_access
WHERE ad_form_id = (SELECT ad_form_id FROM ad_form WHERE classname = 'org.insightai.adempiere.InsightAIForm')
  AND ad_role_id NOT IN (SELECT ad_role_id FROM ad_role WHERE name IN (:roles));

INSERT INTO ad_form_access (ad_form_id, ad_role_id, ad_client_id, ad_org_id, isactive, created, createdby, updated, updatedby,
                            isreadwrite, uuid)
SELECT f.ad_form_id, r.ad_role_id, r.ad_client_id, 0, 'Y', now(), 100, now(), 100, 'Y', getuuid()
FROM ad_form f CROSS JOIN ad_role r
WHERE f.classname = 'org.insightai.adempiere.InsightAIForm' AND r.isactive = 'Y' AND r.name IN (:roles)
  AND NOT EXISTS (SELECT 1 FROM ad_form_access a WHERE a.ad_form_id = f.ad_form_id AND a.ad_role_id = r.ad_role_id);

DELETE FROM ad_process_access
WHERE ad_process_id = (SELECT ad_process_id FROM ad_process WHERE value = 'InsightAI_Launch')
  AND ad_role_id NOT IN (SELECT ad_role_id FROM ad_role WHERE name IN (:roles));

INSERT INTO ad_process_access (ad_process_id, ad_role_id, ad_client_id, ad_org_id, isactive, created, createdby, updated, updatedby,
                               isreadwrite, uuid)
SELECT p.ad_process_id, r.ad_role_id, r.ad_client_id, 0, 'Y', now(), 100, now(), 100, 'Y', getuuid()
FROM ad_process p CROSS JOIN ad_role r
WHERE p.value = 'InsightAI_Launch' AND r.isactive = 'Y' AND r.name IN (:roles)
  AND NOT EXISTS (SELECT 1 FROM ad_process_access a WHERE a.ad_process_id = p.ad_process_id AND a.ad_role_id = r.ad_role_id);

-- What is now installed
SELECT 'entity type' AS record, entitytype AS key, ad_entitytype_id AS id FROM ad_entitytype WHERE entitytype = 'INSAI'
UNION ALL SELECT 'form', name, ad_form_id FROM ad_form WHERE classname = 'org.insightai.adempiere.InsightAIForm'
UNION ALL SELECT 'process', value, ad_process_id FROM ad_process WHERE value = 'InsightAI_Launch'
UNION ALL SELECT 'menu entries (should be none)', count(*)::text, 0 FROM ad_menu WHERE entitytype = 'INSAI'
UNION ALL SELECT 'form access', r.name, r.ad_role_id FROM ad_form_access a JOIN ad_role r ON r.ad_role_id = a.ad_role_id
          JOIN ad_form f ON f.ad_form_id = a.ad_form_id WHERE f.classname = 'org.insightai.adempiere.InsightAIForm' AND a.isactive = 'Y'
UNION ALL SELECT 'process access', r.name, r.ad_role_id FROM ad_process_access a JOIN ad_role r ON r.ad_role_id = a.ad_role_id
          JOIN ad_process p ON p.ad_process_id = a.ad_process_id WHERE p.value = 'InsightAI_Launch' AND a.isactive = 'Y';
