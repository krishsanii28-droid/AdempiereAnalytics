-- Removes every Application Dictionary record dictionary_install.sql created, and nothing else.
-- Run as the adempiere role:  psql -v ON_ERROR_STOP=1 -1 -f dictionary_uninstall.sql
--
-- Run history (AD_PInstance and its log and parameter rows) for the launcher process is removed too,
-- because those rows reference the process. Sequence counters are not wound back: reusing IDs is unsafe.

\set ON_ERROR_STOP on
SET search_path = adempiere;

CREATE TEMP TABLE insightai_ids ON COMMIT DROP AS
SELECT p.ad_process_id, m.ad_menu_id
FROM ad_process p LEFT JOIN ad_menu m ON m.ad_process_id = p.ad_process_id AND m.entitytype = 'INSAI'
WHERE p.value = 'InsightAI_Launch' AND p.entitytype = 'INSAI';

DELETE FROM ad_package_exp_detail WHERE ad_menu_id IN (SELECT ad_menu_id FROM insightai_ids)
                                     OR ad_process_id IN (SELECT ad_process_id FROM insightai_ids);
-- the 2Pack export definition created by tests\java\PackOutHarness.java, if any
DELETE FROM ad_package_exp_detail WHERE ad_package_exp_id IN (SELECT ad_package_exp_id FROM ad_package_exp WHERE name = 'InsightAI' AND username = 'InsightAI');
DELETE FROM ad_package_exp        WHERE name = 'InsightAI' AND username = 'InsightAI';
DELETE FROM ad_recentitem         WHERE ad_menu_id IN (SELECT ad_menu_id FROM insightai_ids);
DELETE FROM ad_tree_favorite_node WHERE ad_menu_id IN (SELECT ad_menu_id FROM insightai_ids);
DELETE FROM ad_treebar        WHERE node_id IN (SELECT ad_menu_id FROM insightai_ids);
DELETE FROM ad_treenodemm     WHERE node_id IN (SELECT ad_menu_id FROM insightai_ids);
DELETE FROM ad_menu_trl       WHERE ad_menu_id IN (SELECT ad_menu_id FROM insightai_ids);
DELETE FROM ad_menu           WHERE ad_menu_id IN (SELECT ad_menu_id FROM insightai_ids);
DELETE FROM ad_process_access WHERE ad_process_id IN (SELECT ad_process_id FROM insightai_ids);
DELETE FROM ad_pinstance_log  WHERE ad_pinstance_id IN (SELECT ad_pinstance_id FROM ad_pinstance WHERE ad_process_id IN (SELECT ad_process_id FROM insightai_ids));
DELETE FROM ad_pinstance_para WHERE ad_pinstance_id IN (SELECT ad_pinstance_id FROM ad_pinstance WHERE ad_process_id IN (SELECT ad_process_id FROM insightai_ids));
DELETE FROM ad_pinstance      WHERE ad_process_id IN (SELECT ad_process_id FROM insightai_ids);
DELETE FROM ad_process_trl    WHERE ad_process_id IN (SELECT ad_process_id FROM insightai_ids);
DELETE FROM ad_process        WHERE ad_process_id IN (SELECT ad_process_id FROM insightai_ids);
DELETE FROM ad_entitytype     WHERE entitytype = 'INSAI'
  AND NOT EXISTS (SELECT 1 FROM ad_process WHERE entitytype = 'INSAI')
  AND NOT EXISTS (SELECT 1 FROM ad_menu WHERE entitytype = 'INSAI');

SELECT (SELECT count(*) FROM ad_entitytype WHERE entitytype = 'INSAI') AS entity_types_left,
       (SELECT count(*) FROM ad_process WHERE entitytype = 'INSAI') AS processes_left,
       (SELECT count(*) FROM ad_menu WHERE entitytype = 'INSAI') AS menus_left;
