-- ADempiere InsightAI - Application Dictionary records (Stage 6)
--
-- Adds, under a new entity type INSAI:
--   AD_EntityType      INSAI
--   AD_Form            InsightAI                -> org.insightai.adempiere.InsightAIForm (dashboard inside ADempiere)
--   AD_Process         InsightAI_Launch         -> org.insightai.adempiere.InsightAILauncher (dashboard in the browser)
--   AD_Menu            "InsightAI" (the form) and "InsightAI (browser)" (the process), under Performance Analysis
--   AD_Form_Access and AD_Process_Access for the roles named in :roles only
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
       'Menu entry and launcher process for the InsightAI dashboard. Removable with dictionary_uninstall.sql.', 'N', getuuid()
WHERE NOT EXISTS (SELECT 1 FROM ad_entitytype WHERE entitytype = 'INSAI');

-- Launcher process. Access level 3 = Client+Organization. Not a server process: it must run in the
-- desktop client so it can open the user's browser. ShowHelp S = run on click, without a dialog first.
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

-- Menu entry for the embedded window
INSERT INTO ad_menu (ad_menu_id, ad_client_id, ad_org_id, isactive, created, createdby, updated, updatedby,
                     name, description, issummary, issotrx, isreadonly, action, ad_form_id, entitytype, iscentrallymaintained, uuid)
SELECT nextidfunc((SELECT ad_sequence_id FROM ad_sequence WHERE name = 'AD_Menu' AND istableid = 'Y')::int, 'N'),
       0, 0, 'Y', now(), 100, now(), 100,
       'InsightAI', 'InsightAI analytics dashboard', 'N', 'N', 'N', 'X', f.ad_form_id, 'INSAI', 'Y', getuuid()
FROM ad_form f
WHERE f.classname = 'org.insightai.adempiere.InsightAIForm'
  AND NOT EXISTS (SELECT 1 FROM ad_menu m WHERE m.ad_form_id = f.ad_form_id);

-- Menu entry for the browser launcher
INSERT INTO ad_menu (ad_menu_id, ad_client_id, ad_org_id, isactive, created, createdby, updated, updatedby,
                     name, description, issummary, issotrx, isreadonly, action, ad_process_id, entitytype, iscentrallymaintained, uuid)
SELECT nextidfunc((SELECT ad_sequence_id FROM ad_sequence WHERE name = 'AD_Menu' AND istableid = 'Y')::int, 'N'),
       0, 0, 'Y', now(), 100, now(), 100,
       'InsightAI (browser)', 'Open the InsightAI analytics dashboard in your web browser', 'N', 'N', 'N', 'P', p.ad_process_id, 'INSAI', 'Y', getuuid()
FROM ad_process p
WHERE p.value = 'InsightAI_Launch'
  AND NOT EXISTS (SELECT 1 FROM ad_menu m WHERE m.ad_process_id = p.ad_process_id);

-- An install made before the embedded window existed named the browser entry "InsightAI"
UPDATE ad_menu SET name = 'InsightAI (browser)', description = 'Open the InsightAI analytics dashboard in your web browser', updated = now()
WHERE entitytype = 'INSAI' AND action = 'P' AND name = 'InsightAI';
UPDATE ad_menu_trl t SET name = m.name, description = m.description, updated = now()
FROM ad_menu m WHERE m.ad_menu_id = t.ad_menu_id AND m.entitytype = 'INSAI' AND t.istranslated = 'N' AND t.name <> m.name;

INSERT INTO ad_menu_trl (ad_menu_id, ad_language, ad_client_id, ad_org_id, isactive, created, createdby, updated, updatedby,
                         name, description, istranslated, uuid)
SELECT m.ad_menu_id, l.ad_language, 0, 0, 'Y', now(), 100, now(), 100, m.name, m.description, 'N', getuuid()
FROM ad_menu m CROSS JOIN ad_language l
WHERE m.entitytype = 'INSAI' AND l.isactive = 'Y' AND l.issystemlanguage = 'Y' AND l.isbaselanguage = 'N'
  AND NOT EXISTS (SELECT 1 FROM ad_menu_trl t WHERE t.ad_menu_id = m.ad_menu_id AND t.ad_language = l.ad_language);

-- Place both entries last under Performance Analysis in every menu tree, the embedded window first.
-- Existing nodes are not renumbered.
INSERT INTO ad_treenodemm (ad_tree_id, node_id, ad_client_id, ad_org_id, isactive, created, createdby, updated, updatedby,
                           parent_id, seqno, uuid)
SELECT t.ad_tree_id, m.ad_menu_id, t.ad_client_id, 0, 'Y', now(), 100, now(), 100, pa.ad_menu_id,
       (SELECT COALESCE(MAX(x.seqno), 0) FROM ad_treenodemm x WHERE x.ad_tree_id = t.ad_tree_id AND x.parent_id = pa.ad_menu_id)
         + CASE WHEN m.action = 'X' THEN 1 ELSE 2 END,
       getuuid()
FROM ad_menu m
CROSS JOIN ad_tree t
CROSS JOIN (SELECT ad_menu_id FROM ad_menu WHERE name = 'Performance Analysis' AND issummary = 'Y' AND entitytype = 'D') pa
WHERE m.entitytype = 'INSAI' AND t.treetype = 'MM' AND t.isactive = 'Y'
  AND NOT EXISTS (SELECT 1 FROM ad_treenodemm n WHERE n.ad_tree_id = t.ad_tree_id AND n.node_id = m.ad_menu_id);

-- If the browser entry was installed earlier it sits before the new embedded entry: put the window first
UPDATE ad_treenodemm n SET seqno = n.seqno + 2, updated = now()
FROM ad_menu m
WHERE m.ad_menu_id = n.node_id AND m.entitytype = 'INSAI' AND m.action = 'P'
  AND EXISTS (SELECT 1 FROM ad_treenodemm n2 JOIN ad_menu m2 ON m2.ad_menu_id = n2.node_id
              WHERE n2.ad_tree_id = n.ad_tree_id AND m2.entitytype = 'INSAI' AND m2.action = 'X' AND n2.seqno > n.seqno);

-- Access: exactly the roles in :roles. A role not listed loses access if it had it.
DELETE FROM ad_process_access
WHERE ad_process_id = (SELECT ad_process_id FROM ad_process WHERE value = 'InsightAI_Launch')
  AND ad_role_id NOT IN (SELECT ad_role_id FROM ad_role WHERE name IN (:roles));

INSERT INTO ad_process_access (ad_process_id, ad_role_id, ad_client_id, ad_org_id, isactive, created, createdby, updated, updatedby,
                               isreadwrite, uuid)
SELECT p.ad_process_id, r.ad_role_id, r.ad_client_id, 0, 'Y', now(), 100, now(), 100, 'Y', getuuid()
FROM ad_process p CROSS JOIN ad_role r
WHERE p.value = 'InsightAI_Launch' AND r.isactive = 'Y' AND r.name IN (:roles)
  AND NOT EXISTS (SELECT 1 FROM ad_process_access a WHERE a.ad_process_id = p.ad_process_id AND a.ad_role_id = r.ad_role_id);

-- Move the embedded-window entry to the top level of the menu, directly after Performance Analysis,
-- so it is visible as soon as ADempiere opens. Menu positions are whole numbers, so the top-level
-- entries that follow are each moved down one place (their order is unchanged); the uninstall
-- closes the gap again. Done only while the entry still sits inside the Performance Analysis
-- folder, so a position chosen later by hand in ADempiere is left alone.
WITH target AS (
  SELECT n.ad_tree_id, n.node_id, pa.seqno + 1 AS wanted
  FROM ad_treenodemm n
  JOIN ad_menu m ON m.ad_menu_id = n.node_id AND m.entitytype = 'INSAI' AND m.action = 'X'
  JOIN ad_menu pam ON pam.name = 'Performance Analysis' AND pam.issummary = 'Y' AND pam.entitytype = 'D'
  JOIN ad_treenodemm pa ON pa.ad_tree_id = n.ad_tree_id AND pa.node_id = pam.ad_menu_id AND pa.parent_id = 0
  WHERE n.parent_id = pam.ad_menu_id
), make_room AS (
  UPDATE ad_treenodemm x SET seqno = x.seqno + 1, updated = now()
  FROM target t
  WHERE x.ad_tree_id = t.ad_tree_id AND x.parent_id = 0 AND x.seqno >= t.wanted AND x.node_id <> t.node_id
  RETURNING 1
)
UPDATE ad_treenodemm n SET parent_id = 0, seqno = t.wanted, updated = now()
FROM target t
WHERE n.ad_tree_id = t.ad_tree_id AND n.node_id = t.node_id;

-- The same roles, and only those, may open the embedded window
DELETE FROM ad_form_access
WHERE ad_form_id = (SELECT ad_form_id FROM ad_form WHERE classname = 'org.insightai.adempiere.InsightAIForm')
  AND ad_role_id NOT IN (SELECT ad_role_id FROM ad_role WHERE name IN (:roles));

INSERT INTO ad_form_access (ad_form_id, ad_role_id, ad_client_id, ad_org_id, isactive, created, createdby, updated, updatedby,
                            isreadwrite, uuid)
SELECT f.ad_form_id, r.ad_role_id, r.ad_client_id, 0, 'Y', now(), 100, now(), 100, 'Y', getuuid()
FROM ad_form f CROSS JOIN ad_role r
WHERE f.classname = 'org.insightai.adempiere.InsightAIForm' AND r.isactive = 'Y' AND r.name IN (:roles)
  AND NOT EXISTS (SELECT 1 FROM ad_form_access a WHERE a.ad_form_id = f.ad_form_id AND a.ad_role_id = r.ad_role_id);

-- What is now installed
SELECT 'entity type' AS record, entitytype AS key, ad_entitytype_id AS id FROM ad_entitytype WHERE entitytype = 'INSAI'
UNION ALL SELECT 'form', name, ad_form_id FROM ad_form WHERE classname = 'org.insightai.adempiere.InsightAIForm'
UNION ALL SELECT 'process', value, ad_process_id FROM ad_process WHERE value = 'InsightAI_Launch'
UNION ALL (SELECT 'menu: ' || COALESCE('inside ' || pm.name, 'top level') || ', position ' || n.seqno, m.name, m.ad_menu_id FROM ad_menu m
           JOIN ad_treenodemm n ON n.node_id = m.ad_menu_id LEFT JOIN ad_menu pm ON pm.ad_menu_id = n.parent_id
           WHERE m.entitytype = 'INSAI' ORDER BY n.parent_id, n.seqno)
UNION ALL SELECT 'form access', r.name, r.ad_role_id FROM ad_form_access a JOIN ad_role r ON r.ad_role_id = a.ad_role_id
          JOIN ad_form f ON f.ad_form_id = a.ad_form_id WHERE f.classname = 'org.insightai.adempiere.InsightAIForm' AND a.isactive = 'Y'
UNION ALL SELECT 'process access', r.name, r.ad_role_id FROM ad_process_access a JOIN ad_role r ON r.ad_role_id = a.ad_role_id
          JOIN ad_process p ON p.ad_process_id = a.ad_process_id WHERE p.value = 'InsightAI_Launch' AND a.isactive = 'Y';
